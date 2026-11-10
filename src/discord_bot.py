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
    - "오늘 오전 주문 처리할게요" -> 파일을 올리라고 안내 (오전/오후는 말한 대로, 없으면 현재 시각)
    - .xlsx 를 첨부해 보내면 -> src/run_all.py 로 전체 변환·검증 -> 쉬운 말 요약 + 결과 xlsx 3종
      (ANTHROPIC_API_KEY 가 있으면 규칙에 없는 상품명을 AI가 제안 -> 봇이 하나씩 "맞나요?" 물어 확정한 뒤 파일 전송)
    - "시애틀F28 미조립 운임 16000" -> 운임표(config/factory.yaml)에 추가하고 다시 변환
    - 그 밖의 글            -> `claude -p --agent order-converter` 에게 전달 (대화는 채널/DM 별로 이어짐)
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
import chat  # noqa: E402
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


def run_all(src: Path, output_root: Path | None = None, use_llm: bool = False,
            ampm: str | None = None) -> tuple[int, list[str], Path | None]:
    """run_all.py 실행. (종료코드, 출력 줄들, 결과 폴더)"""
    cmd = [sys.executable, "-I", str(ROOT / "src" / "run_all.py"), str(src)]
    if output_root:
        cmd += ["--output-root", str(output_root)]
    if use_llm:
        cmd.append("--llm")
    if ampm:
        cmd += ["--ampm", ampm]
    p = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True, timeout=PIPELINE_TIMEOUT)
    lines = [ln.rstrip() for ln in (p.stdout + p.stderr).strip().splitlines() if ln.strip()]
    run_dir = None
    for ln in lines:
        if ln.startswith("결과:") and "->" in ln:
            run_dir = Path(ln.split("->", 1)[1].strip())
    return p.returncode, lines, run_dir


def result_files(run_dir: Path | None) -> list[Path]:
    files = sorted(run_dir.glob("*.xlsx")) if run_dir and run_dir.exists() else []
    return [f for f in files if not f.name.endswith("_변환.xlsx")]    # 중간파일은 보내지 않음


def run_pipeline(src: Path, output_root: Path | None = None, use_llm: bool = False,
                 ampm: str | None = None) -> tuple[int, str, list[Path]]:
    """(종료코드, 사용자에게 보낼 쉬운 말 요약, 보낼 파일들). run_all 은 개인정보 없는 형태로만 출력한다."""
    code, lines, run_dir = run_all(src, output_root, use_llm, ampm)
    try:
        n = chat.count_orders(src)
    except Exception:
        n = None
    return code, chat.friendly_summary(code, lines, n), result_files(run_dir)


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
    cmd = ["claude", "-p", (chat.AGENT_STYLE + "\n" + context + "\n" + text).strip(), "--agent", "order-converter",
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

    file_env = load_env(ROOT / ".env")
    env = {**file_env, **{k: v for k, v in os.environ.items() if k.startswith(("DISCORD_", "ANTHROPIC_"))}}
    if env.get("ANTHROPIC_API_KEY"):
        os.environ["ANTHROPIC_API_KEY"] = env["ANTHROPIC_API_KEY"]   # run_all -> convert --llm 에서 사용
    use_llm = bool(env.get("ANTHROPIC_API_KEY"))
    token = env.get("DISCORD_BOT_TOKEN")
    allowed = parse_ids(env.get("DISCORD_ALLOWED_USER_IDS", ""))
    channels = parse_ids(env.get("DISCORD_CHANNEL_IDS", ""))
    if not token:
        print("DISCORD_BOT_TOKEN 이 없습니다. 파일 상단 사용법의 .env 설정을 확인하세요.", file=sys.stderr)
        return 1
    print(f"허용 사용자 {len(allowed)}명, 허용 채널 {len(channels)}개, 상품명 AI 제안 {'사용' if use_llm else '미사용(ANTHROPIC_API_KEY 없음)'}")

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)
    lock = asyncio.Lock()      # 한 번에 한 작업만 (같은 output 폴더·세션 충돌 방지)
    last_run: dict[int, str] = {}        # 채널 -> 에이전트에게 줄 직전 작업 설명
    last_job: dict[int, dict] = {}       # 채널 -> {"src": Path, "ampm": str} (규칙 추가 후 재변환용)
    want_ampm: dict[int, str] = {}       # 채널 -> 말로 시작하며 정한 오전/오후
    confirm: dict[int, dict] = {}        # 채널 -> 진행 중인 "맞나요?" 확인 상태

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

    async def process(msg: discord.Message, src: Path, ampm: str, skipped: set[str] | None = None) -> None:
        """변환 실행 -> 쉬운 말 요약 -> (AI 제안 확인이 있으면 질문, 없으면 파일 전송)."""
        skipped = skipped or set()
        code, lines, run_dir = await asyncio.to_thread(run_all, src, None, use_llm, ampm)
        try:
            n = chat.count_orders(src)
        except Exception:
            n = None
        files = result_files(run_dir)
        cid = msg.channel.id
        last_job[cid] = {"src": src, "ampm": ampm}
        last_run[cid] = (f"[방금 처리한 파일: {src.relative_to(ROOT)} / {ampm} / {'정상' if code == 0 else '경고' if code == 2 else '실패'}. "
                         "단계별 경고는 output/latest/실행요약.txt 에 있다]")
        await say(msg, chat.friendly_summary(code, lines, n))
        if code not in (0, 2):
            return
        keys = chat.file_product_keys(src)
        queue = [it for it in chat.pending_items() if it[0] in keys and it[0] not in skipped]
        if queue:
            confirm[cid] = {"src": src, "ampm": ampm, "queue": queue, "total": len(queue), "edited": False,
                            "await_edit": None, "files": files, "skipped": set(skipped)}
            await say(msg, "AI가 제안한 상품명은 확인이 끝나면 파일을 보내드릴게요.")
            await say(msg, chat.question(queue[0][1], queue[0][2], 1, len(queue)))
        else:
            await send_files(msg, files)

    async def finish_confirm(msg: discord.Message, st: dict) -> None:
        cid = msg.channel.id
        confirm.pop(cid, None)
        if st["edited"]:
            await say(msg, "고치신 표기로 다시 변환할게요…")
            await process(msg, st["src"], st["ampm"], st["skipped"])
        else:
            if st["skipped"]:
                await say(msg, f"건너뛴 {len(st['skipped'])}건은 AI 제안 그대로 들어갔어요. 나중에 config/product_map.yaml 에서 확인할 수 있어요.")
            await send_files(msg, st["files"])

    async def advance(msg: discord.Message, st: dict) -> None:
        st["queue"].pop(0)
        if st["queue"]:
            i = st["total"] - len(st["queue"]) + 1
            await say(msg, chat.question(st["queue"][0][1], st["queue"][0][2], i, st["total"]))
        else:
            await finish_confirm(msg, st)

    async def handle_confirm(msg: discord.Message, st: dict) -> None:
        key, name, _tpl = st["queue"][0]
        text = msg.content.strip()
        kind = chat.answer_kind(text)
        if st["await_edit"]:
            if kind == "skip":
                st["skipped"].add(key)
                st["await_edit"] = None
                await advance(msg, st)
            elif chat.llm_fallback.valid_template(text):
                chat.resolve(key, "edit", text)
                st["edited"] = True
                st["await_edit"] = None
                await advance(msg, st)
            else:
                await say(msg, chat.color_hint(text))
            return
        if kind == "yes":
            chat.resolve(key, "yes")
            await advance(msg, st)
        elif kind == "no":
            st["await_edit"] = key
            await say(msg, f"'{name}' 을(를) 어떻게 바꿀까요? 원하는 표기를 그대로 써 주세요. " + chat.color_hint(text))
        elif kind == "skip":
            st["skipped"].add(key)
            await advance(msg, st)
        else:
            await say(msg, "'네', '아니요', '건너뛰기' 중 하나로 답해 주세요.")

    async def handle_xlsx(msg: discord.Message, att: discord.Attachment) -> None:
        if att.size > MAX_BYTES:
            await say(msg, f"{att.filename}: 파일이 너무 큽니다 (10MB 이하).")
            return
        cid = msg.channel.id
        confirm.pop(cid, None)                      # 새 파일이 오면 이전 확인은 접는다
        ampm = chat.parse_ampm(msg.content) or want_ampm.pop(cid, None) or chat.default_ampm()
        await say(msg, f"{att.filename} 받았어요. {ampm} 주문으로 변환할게요. 잠시만 기다려 주세요…")
        dest_dir = ROOT / "input" / "discord"
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / f"{datetime.now():%y%m%d-%H%M%S}_{safe_name(att.filename)}"
        await att.save(dest)
        await process(msg, dest, ampm)

    async def handle_fee_rule(msg: discord.Message, product: str, fee: int) -> None:
        await say(msg, chat.add_fee_rule(product, fee))
        job = last_job.get(msg.channel.id)
        if job and job["src"].exists():
            await say(msg, "운임표를 반영해서 다시 변환할게요…")
            await process(msg, job["src"], job["ampm"])

    async def handle_text(msg: discord.Message) -> None:
        before = snapshot_xlsx(ROOT / "output")
        try:
            reply = await asyncio.to_thread(ask_agent, msg.channel.id, msg.content, last_run.get(msg.channel.id, ""))
        except subprocess.TimeoutExpired:
            reply = "시간이 너무 오래 걸려 중단했어요."
        except FileNotFoundError:
            reply = "claude 명령을 찾을 수 없어요 (서버 PC에 Claude Code 설치 필요)."
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
                await say(msg, "엑셀(.xlsx) 파일만 처리해요.")
            elif msg.content.strip() and not xlsx:
                text = msg.content.strip()
                st = confirm.get(msg.channel.id)
                fee = chat.parse_fee_rule(text)
                if st:
                    await handle_confirm(msg, st)
                elif fee:
                    await handle_fee_rule(msg, *fee)
                elif chat.is_start(text):
                    ampm = chat.parse_ampm(text) or chat.default_ampm()
                    want_ampm[msg.channel.id] = ampm
                    await say(msg, f"네, {ampm} 주문 처리할게요. 주문 엑셀(.xlsx) 파일을 이 대화에 올려 주세요. "
                                   "올려 주시면 변환부터 공장용·택배용·내부보관용 파일까지 만들어 드려요.")
                else:
                    await handle_text(msg)

    client.run(token)
    return 0


if __name__ == "__main__":
    sys.exit(main())
