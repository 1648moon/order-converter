"""디스코드 알림 전용 봇.

- 파일은 절대 주고받지 않는다. 텍스트 알림과 간단한 일반 메시지 명령('상태', '목록', '웹')만 처리한다.
  '웹' 은 이 맥의 브라우저에서 업로드 페이지를 열 뿐, 디스코드로 파일을 받지 않는다.
- 위 명령이 아닌 말은 agent_handler(src/agent_chat.py)로 넘긴다: 변경을 '제안'하고 사람이 '승인 번호'라고 답하면 적용.
  승인·거절은 LLM 이 아니라 코드가 처리한다. 파일을 받지 않고 개인정보도 다루지 않는 점은 그대로다.
- 명령은 DISCORD_OWNER_ID 본인과 DISCORD_ALLOWED_IDS(쉼표로 구분한 추가 사용자 ID)에 적은 사람의 메시지에만 반응한다.
  그 밖의 사용자는 어떤 말에도 무반응이다.
- DISCORD_TOKEN / DISCORD_CHANNEL_ID 가 없으면 알림을 콘솔에만 출력한다(봇 없이도 웹은 동작).
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Callable

import runinfo

def parse_ids(value: str | None) -> tuple[set[int], list[str]]:
    """'111, 222 333' 같은 문자열에서 디스코드 ID(숫자)를 뽑는다. (ID 집합, 숫자가 아니라 버린 항목들)."""
    ids: set[int] = set()
    bad: list[str] = []
    for tok in (value or "").replace(",", " ").split():
        if tok.isdigit():
            ids.add(int(tok))
        else:
            bad.append(tok)
    return ids, bad


WEB_WORDS = ("웹", "web", "업로드")        # 이 말을 보내면 맥에서 업로드 페이지를 연다 (파일은 디스코드로 보내지 않음)
DISCORD_LIMIT = 1900                        # 디스코드 메시지 최대 2000자


def split_message(text: str, limit: int = DISCORD_LIMIT) -> list[str]:
    """긴 문장을 줄 단위로 limit 이하로 나눈다."""
    out, cur = [], ""
    for line in text.split("\n"):
        while len(line) > limit:
            if cur:
                out.append(cur); cur = ""
            out.append(line[:limit]); line = line[limit:]
        if len(cur) + len(line) + 1 > limit and cur:
            out.append(cur); cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        out.append(cur)
    return out


class Notifier:
    def __init__(self, output_root, token: str | None, channel_id: int | None, owner_id: int | None,
                 open_web: Callable[[], str] | None = None, allowed_ids=(),
                 agent_handler: Callable[[str], list[str]] | None = None):
        """open_web: '웹' 명령을 받으면 호출. 맥에서 업로드 페이지를 열고 안내 문구(주소 등)를 돌려준다.
        agent_handler: 위 명령이 아닌 말(허용된 사용자만)을 받아 보낼 문장 목록을 돌려준다 (agent_chat.default_handler)."""
        self.open_web = open_web
        self.agent_handler = agent_handler
        self.output_root = output_root
        self.token, self.channel_id, self.owner_id = token, channel_id, owner_id
        self.allowed_ids = {int(i) for i in allowed_ids}          # 본인 외에 명령을 허용할 사용자 ID
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._ready = threading.Event()

    @classmethod
    def from_env(cls, output_root, open_web: Callable[[], str] | None = None,
                 agent_handler: Callable[[str], list[str]] | None = None) -> "Notifier":
        def to_int(v):
            return int(v) if v and v.strip().isdigit() else None
        allowed, bad = parse_ids(os.environ.get("DISCORD_ALLOWED_IDS"))
        if bad:
            print(f"[디스코드] DISCORD_ALLOWED_IDS 에서 숫자가 아닌 항목을 무시했습니다: {', '.join(bad)}")
        return cls(output_root, os.environ.get("DISCORD_TOKEN") or None,
                   to_int(os.environ.get("DISCORD_CHANNEL_ID")),
                   to_int(os.environ.get("DISCORD_OWNER_ID")), open_web=open_web, allowed_ids=allowed,
                   agent_handler=agent_handler)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.channel_id)

    def is_allowed(self, user_id: int) -> bool:
        """명령을 써도 되는 사용자인가: 본인(DISCORD_OWNER_ID) 또는 허용 목록(DISCORD_ALLOWED_IDS)."""
        return user_id == self.owner_id or user_id in self.allowed_ids

    # ---- 명령 처리 (순수 함수라 테스트 가능) ----
    def reply_for(self, content: str) -> str | None:
        word = content.strip()
        if word in WEB_WORDS:
            if self.open_web is None:
                return "웹 열기를 지원하지 않는 상태입니다."
            try:
                return self.open_web()
            except Exception as e:                   # 브라우저를 못 열어도 봇은 계속 동작
                return f"웹 페이지를 열지 못했습니다 ({type(e).__name__})."
        if word in ("상태", "목록"):
            if self.output_root is None:             # 서버(Streamlit)는 결과를 저장하지 않는다
                return "이 서버는 변환 결과를 저장하지 않아 상태·목록을 알려드릴 수 없습니다. 변환이 끝나면 알림이 옵니다."
            runs = runinfo.recent_runs(self.output_root, limit=1 if word == "상태" else 5)
            return runinfo.status_text(runs)
        return None

    def _safe_agent(self, content: str) -> list[str]:
        """에이전트 오류가 봇 전체를 멈추지 않게 한다 (오류 내용은 값 노출을 피해 종류만 알린다)."""
        try:
            return self.agent_handler(content)
        except Exception as e:
            print(f"[에이전트] 처리 중 오류: {type(e).__name__}")
            return ["처리 중 문제가 생겼어요. 잠시 뒤 다시 말씀해 주세요."]

    # ---- 봇 실행 ----
    def start(self) -> None:
        if not self.enabled:
            missing = [n for n, v in (("DISCORD_TOKEN", self.token), ("DISCORD_CHANNEL_ID", self.channel_id)) if not v]
            print(f"[디스코드] {', '.join(missing)} 가 비어 있거나 올바르지 않습니다 - 알림은 콘솔에만 출력합니다. "
                  "(ID 는 17~20자리 숫자, 값 앞에 설명 문구를 두지 마세요)")
            return
        if not self.owner_id and not self.allowed_ids:
            print("[디스코드] DISCORD_OWNER_ID 와 DISCORD_ALLOWED_IDS 가 비어 있어 '상태'/'웹' 같은 명령은 어떤 메시지에도 반응하지 않습니다 (알림만 전송).")
        elif self.allowed_ids:
            print(f"[디스코드] 명령 허용 사용자: 본인 + 추가 {len(self.allowed_ids)}명")
        threading.Thread(target=self._run, daemon=True, name="discord-bot").start()
        if not self._ready.wait(timeout=20):
            print("[디스코드] 봇 연결이 지연되고 있습니다. 토큰/인텐트 설정을 확인하세요.")

    def _run(self) -> None:
        import discord

        intents = discord.Intents.default()
        intents.message_content = True            # 일반 메시지 명령용 (Developer Portal 에서도 켜야 함)
        client = discord.Client(intents=intents)
        self._client = client

        @client.event
        async def on_ready():
            self._loop = asyncio.get_running_loop()
            self._ready.set()
            print(f"[디스코드] 로그인: {client.user}")

        @client.event
        async def on_message(msg):
            if msg.author.bot or msg.channel.id != self.channel_id:
                return
            if not self.is_allowed(msg.author.id):
                return                              # 허용되지 않은 사용자의 명령 무시
            reply = self.reply_for(msg.content)
            if reply:
                await msg.channel.send(reply)
            elif self.agent_handler is not None:
                async with msg.channel.typing():           # AI 응답을 기다리는 동안 '입력 중' 표시
                    texts = await asyncio.to_thread(self._safe_agent, msg.content)
                for t in texts:
                    for chunk in split_message(t):
                        await msg.channel.send(chunk)

        client.run(self.token, log_handler=None)

    # ---- 알림 ----
    def notify(self, text: str) -> None:
        print(f"[알림] {text}")
        if not (self.enabled and self._loop and self._client):
            return

        async def _send():
            ch = self._client.get_channel(self.channel_id) or await self._client.fetch_channel(self.channel_id)
            await ch.send(text)

        fut = asyncio.run_coroutine_threadsafe(_send(), self._loop)
        try:
            fut.result(timeout=15)
        except Exception as e:                      # 알림 실패가 변환 결과에 영향 주지 않게
            print(f"[디스코드] 알림 전송 실패: {type(e).__name__}")


_server_notifier: Notifier | None = None


def server_notifier() -> Notifier:
    """서버(Streamlit)용 알림봇. 프로세스당 한 번만 만들어 접속한다 (Streamlit 은 화면마다 스크립트를 다시 실행).
    서버는 결과를 저장하지 않으므로 output_root 는 None (상태·목록 명령은 안내 문구로 응답).
    '웹' 명령은 WEB_REMOTE_URL 이 http(s) 로 시작하면 그 주소를 안내한다."""
    global _server_notifier
    if _server_notifier is None:
        remote = (os.environ.get("WEB_REMOTE_URL") or "").strip().rstrip("/")
        open_web = (lambda: f"웹 페이지입니다. 파일은 여기서 올려 주세요: {remote}") \
            if remote.startswith(("http://", "https://")) else None
        handler = None
        try:
            import agent_chat
            handler = agent_chat.default_handler()
        except Exception as e:                      # 에이전트를 못 켜도 알림봇은 그대로 동작
            print(f"[에이전트] 켜지 못했습니다 ({type(e).__name__}) - 알림과 기본 명령만 동작합니다.")
        _server_notifier = Notifier.from_env(None, open_web=open_web, agent_handler=handler)
        _server_notifier.start()
    return _server_notifier
