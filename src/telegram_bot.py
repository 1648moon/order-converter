"""텔레그램으로 주문 엑셀을 변환하고, order-converter 에이전트와 대화한다.

사용법:
    1) BotFather 에서 봇을 만들고 토큰을 받는다.
    2) 프로젝트 루트에 .env 파일을 만든다 (git 에 올라가지 않음):
           TELEGRAM_BOT_TOKEN=123456:ABC...
           TELEGRAM_ALLOWED_CHAT_IDS=111111111,222222222
       허용 목록이 비어 있으면 아무도 쓸 수 없다. 처음엔 봇에게 말을 걸면 내 chat id 가 답장으로 나온다.
    3) .venv/bin/python src/telegram_bot.py      (PC 가 켜져 있는 동안만 동작)

동작:
    - .xlsx 파일을 보내면 -> src/run_all.py 로 전체 변환·검증 -> 요약 + 결과 xlsx 4종을 답장으로 보냄
    - 글을 보내면        -> `claude -p --agent order-converter` 에게 전달 (대화는 chat 별로 이어짐)
      에이전트가 새로 만든 xlsx 도 함께 보내 줌

주의: 주문 엑셀(개인정보)이 텔레그램 서버를 거친다. 허용된 chat id 외에는 어떤 처리도 하지 않는다.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MAX_BYTES = 20 * 1024 * 1024          # 텔레그램 봇이 받을 수 있는 최대 크기
CLAUDE_TIMEOUT = 600
PIPELINE_TIMEOUT = 600
SESSIONS = ROOT / ".telegram_sessions.json"
AGENT_TOOLS = ["Bash(.venv/bin/python:*)", "Read", "Edit"]


def load_env(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip("'\"")
    return env


def parse_ids(raw: str) -> set[int]:
    return {int(x) for x in re.split(r"[,\s]+", raw) if x.strip().lstrip("-").isdigit()}


def safe_name(name: str) -> str:
    return re.sub(r"[^\w.\-가-힣]", "_", name)


def run_pipeline(src: Path, output_root: Path | None = None) -> tuple[int, str, list[Path]]:
    """run_all.py 실행. (종료코드, 사용자에게 보낼 요약, 보낼 파일들) 을 돌려준다."""
    cmd = [sys.executable, "-I", str(ROOT / "src" / "run_all.py"), str(src)]
    if output_root:
        cmd += ["--output-root", str(output_root)]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=PIPELINE_TIMEOUT)
    out = (p.stdout + p.stderr).strip()
    lines = [ln.rstrip() for ln in out.splitlines() if ln.strip()]
    run_dir = None
    for ln in lines:
        if ln.startswith("결과:") and "->" in ln:
            run_dir = Path(ln.split("->", 1)[1].strip())
    files = sorted(run_dir.glob("*.xlsx")) if run_dir and run_dir.exists() else []
    files = [f for f in files if not f.name.endswith("_변환.xlsx")]    # 중간파일은 보내지 않음
    head = {0: "✅ 변환 완료", 2: "⚠️ 변환 완료 (경고 있음)"}.get(p.returncode, "❌ 변환 실패")
    # 단계 상태·경고만 보낸다 (run_all 이 개인정보 없는 형태로 출력)
    keep = [ln for ln in lines if ln.startswith("[") or ln.strip().startswith("경고")]
    if run_dir:
        keep.append(f"폴더: {run_dir.name}")
    if p.returncode not in (0, 2):
        keep = lines[-20:]
    return p.returncode, head + "\n" + "\n".join(keep), files


def snapshot_xlsx(output_root: Path) -> dict[Path, float]:
    return {p: p.stat().st_mtime for p in output_root.rglob("*.xlsx")} if output_root.exists() else {}


def new_xlsx(before: dict[Path, float], output_root: Path) -> list[Path]:
    after = snapshot_xlsx(output_root)
    return sorted(p for p, m in after.items() if before.get(p) != m and not p.name.endswith("_변환.xlsx"))


def load_sessions() -> dict:
    try:
        return json.loads(SESSIONS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def ask_agent(chat_id: int, text: str, context: str = "") -> str:
    """claude -p --agent order-converter 호출. chat 마다 세션을 이어 간다."""
    sessions = load_sessions()
    sid = sessions.get(str(chat_id))
    cmd = ["claude", "-p", (context + "\n" + text).strip(), "--agent", "order-converter",
           "--permission-mode", "acceptEdits", "--allowedTools", *AGENT_TOOLS]
    if sid:
        cmd += ["--resume", sid]
    else:
        sid = str(uuid.uuid4())
        cmd += ["--session-id", sid]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=CLAUDE_TIMEOUT)
    if p.returncode == 0:
        sessions[str(chat_id)] = sid
        SESSIONS.write_text(json.dumps(sessions), encoding="utf-8")
    return (p.stdout.strip() or p.stderr.strip() or "(응답 없음)")[:3800]


def main() -> int:
    from telegram import Update
    from telegram.ext import Application, ContextTypes, MessageHandler, CommandHandler, filters

    env = {**load_env(ROOT / ".env"), **{k: v for k, v in os.environ.items() if k.startswith("TELEGRAM_")}}
    token = env.get("TELEGRAM_BOT_TOKEN")
    allowed = parse_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", ""))
    if not token:
        print("TELEGRAM_BOT_TOKEN 이 없습니다. 파일 상단 사용법의 .env 설정을 확인하세요.", file=sys.stderr)
        return 1
    print(f"허용 chat id {len(allowed)}개로 시작합니다.")
    lock = asyncio.Lock()      # 한 번에 한 작업만 (같은 output 폴더·세션 충돌 방지)
    last_run: dict[int, str] = {}

    async def authorized(update: Update) -> bool:
        cid = update.effective_chat.id
        if cid in allowed:
            return True
        await update.effective_message.reply_text(
            f"권한이 없습니다. 관리자에게 이 번호를 알려 주세요: {cid}")
        return False

    async def send_files(update: Update, files: list[Path]) -> None:
        for f in files:
            with f.open("rb") as fh:
                await update.effective_message.reply_document(fh, filename=f.name)

    async def on_start(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if await authorized(update):
            await update.effective_message.reply_text(
                "주문 엑셀(.xlsx)을 보내면 변환·검증 후 공장용/택배용/내부보관용 파일을 돌려드립니다.\n"
                "그 외에는 글로 물어보세요 (예: 방금 경고가 뭐야?, 새 상품 규칙 추가해줘).")

    async def on_document(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(update):
            return
        doc = update.effective_message.document
        if not doc.file_name.lower().endswith(".xlsx"):
            await update.effective_message.reply_text("엑셀(.xlsx) 파일만 처리합니다.")
            return
        if doc.file_size and doc.file_size > MAX_BYTES:
            await update.effective_message.reply_text("파일이 너무 큽니다 (20MB 이하).")
            return
        async with lock:
            await update.effective_message.reply_text("받았습니다. 변환 중입니다…")
            dest_dir = ROOT / "input" / "telegram"
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / f"{datetime.now():%y%m%d-%H%M%S}_{safe_name(doc.file_name)}"
            await (await doc.get_file()).download_to_drive(dest)
            code, summary, files = await asyncio.to_thread(run_pipeline, dest)
            last_run[update.effective_chat.id] = f"[방금 받은 파일: {dest.relative_to(ROOT)} / 종료코드 {code}]"
            await update.effective_message.reply_text(summary[:3800])
            await send_files(update, files)

    async def on_text(update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not await authorized(update):
            return
        cid = update.effective_chat.id
        async with lock:
            await update.effective_message.chat.send_action("typing")
            before = snapshot_xlsx(ROOT / "output")
            try:
                reply = await asyncio.to_thread(ask_agent, cid, update.effective_message.text, last_run.get(cid, ""))
            except subprocess.TimeoutExpired:
                reply = "시간이 너무 오래 걸려 중단했습니다."
            except FileNotFoundError:
                reply = "claude 명령을 찾을 수 없습니다 (서버 PC에 Claude Code 설치 필요)."
            await update.effective_message.reply_text(reply)
            await send_files(update, new_xlsx(before, ROOT / "output"))

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler(["start", "help"], on_start))
    app.add_handler(MessageHandler(filters.Document.ALL, on_document))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))
    app.run_polling()
    return 0


if __name__ == "__main__":
    sys.exit(main())
