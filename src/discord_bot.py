"""디스코드로 주문 엑셀을 변환하고, order-converter 에이전트와 대화한다.

사용법:
    1) https://discord.com/developers/applications 에서 앱을 만들고 Bot 탭에서 토큰을 받는다.
       같은 화면에서 "Message Content Intent" 를 반드시 켠다.
       OAuth2 > URL Generator (scope: bot, 권한: Send Messages, Attach Files, Read Message History)
       로 만든 링크로 봇을 내 서버에 초대한다.
    2) 프로젝트 루트에 .env 파일을 만든다 (git 에 올라가지 않음):
           DISCORD_BOT_TOKEN=...
           DISCORD_ALLOWED_USER_IDS=111111111111111111,222222222222222222
           DISCORD_CHANNEL_IDS=333333333333333333        (선택: 서버 채널에서도 쓰려면)
       허용 목록이 비어 있으면 아무도 쓸 수 없다. 봇에게 DM 을 보내면 내 사용자 id 가 답장으로 나온다.
    3) .venv/bin/python src/discord_bot.py      (PC 가 켜져 있는 동안만 동작)

동작 (DM 또는 허용한 채널에서, 허용된 사용자만):
    - .xlsx 를 첨부해 보내면 -> src/run_all.py 로 전체 변환·검증 -> 요약 + 결과 xlsx 3종을 답장으로 보냄
    - 글을 보내면            -> `claude -p --agent order-converter` 에게 전달 (대화는 채널/DM 별로 이어짐)
      에이전트가 새로 만든 xlsx 도 함께 보내 줌

주의: 주문 엑셀(개인정보)이 디스코드 서버를 거친다. 허용된 사용자 외에는 어떤 처리도 하지 않는다.
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
MAX_BYTES = 10 * 1024 * 1024          # 디스코드 기본 업로드 한도 (서버 부스트 없을 때)
CLAUDE_TIMEOUT = 600
PIPELINE_TIMEOUT = 600
SESSIONS = ROOT / ".discord_sessions.json"
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


def chunks(text: str, n: int = 1900) -> list[str]:
    return [text[i:i + n] for i in range(0, len(text), n)] or [""]


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
    import discord

    env = {**load_env(ROOT / ".env"), **{k: v for k, v in os.environ.items() if k.startswith("DISCORD_")}}
    token = env.get("DISCORD_BOT_TOKEN")
    allowed = parse_ids(env.get("DISCORD_ALLOWED_USER_IDS", ""))
    channels = parse_ids(env.get("DISCORD_CHANNEL_IDS", ""))
    if not token:
        print("DISCORD_BOT_TOKEN 이 없습니다. 파일 상단 사용법의 .env 설정을 확인하세요.", file=sys.stderr)
        return 1
    print(f"허용 사용자 {len(allowed)}명, 허용 채널 {len(channels)}개로 시작합니다.")

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    lock = asyncio.Lock()      # 한 번에 한 작업만 (같은 output 폴더·세션 충돌 방지)
    last_run: dict[int, str] = {}

    async def say(msg: discord.Message, text: str) -> None:
        for part in chunks(text):
            if part.strip():
                await msg.reply(part, mention_author=False)

    async def send_files(msg: discord.Message, files: list[Path]) -> None:
        ok = [f for f in files if f.stat().st_size <= MAX_BYTES]
        for f in files:
            if f not in ok:
                await say(msg, f"{f.name} 은(는) 크기가 커서 보내지 못했습니다. PC 의 output 폴더에서 받아 주세요.")
        for i in range(0, len(ok), 10):            # 메시지당 첨부 최대 10개
            await msg.reply(files=[discord.File(f, filename=f.name) for f in ok[i:i + 10]], mention_author=False)

    async def handle_xlsx(msg: discord.Message, att: discord.Attachment) -> None:
        if att.size > MAX_BYTES:
            await say(msg, f"{att.filename}: 파일이 너무 큽니다 (10MB 이하).")
            return
        await say(msg, f"{att.filename} 받았습니다. 변환 중입니다…")
        dest_dir = ROOT / "input" / "discord"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{datetime.now():%y%m%d-%H%M%S}_{safe_name(att.filename)}"
        await att.save(dest)
        code, summary, files = await asyncio.to_thread(run_pipeline, dest)
        last_run[msg.channel.id] = f"[방금 받은 파일: {dest.relative_to(ROOT)} / 종료코드 {code}]"
        await say(msg, summary)
        await send_files(msg, files)

    async def handle_text(msg: discord.Message) -> None:
        before = snapshot_xlsx(ROOT / "output")
        try:
            reply = await asyncio.to_thread(ask_agent, msg.channel.id, msg.content, last_run.get(msg.channel.id, ""))
        except subprocess.TimeoutExpired:
            reply = "시간이 너무 오래 걸려 중단했습니다."
        except FileNotFoundError:
            reply = "claude 명령을 찾을 수 없습니다 (서버 PC에 Claude Code 설치 필요)."
        await say(msg, reply)
        await send_files(msg, new_xlsx(before, ROOT / "output"))

    @client.event
    async def on_ready() -> None:
        print(f"로그인: {client.user}")

    @client.event
    async def on_message(msg: discord.Message) -> None:
        if msg.author.bot:
            return
        is_dm = msg.guild is None
        if not is_dm and msg.channel.id not in channels:
            return                                     # 허용하지 않은 채널은 무시
        if msg.author.id not in allowed:
            if is_dm:                                  # DM 에서만 안내 (채널에서는 조용히 무시)
                await msg.reply(f"권한이 없습니다. 관리자에게 이 번호를 알려 주세요: {msg.author.id}")
            return
        async with lock, msg.channel.typing():
            xlsx = [a for a in msg.attachments if a.filename.lower().endswith(".xlsx")]
            for att in xlsx:
                await handle_xlsx(msg, att)
            if msg.attachments and not xlsx:
                await say(msg, "엑셀(.xlsx) 파일만 처리합니다.")
            elif msg.content.strip() and not xlsx:
                await handle_text(msg)

    client.run(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
