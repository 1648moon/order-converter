"""디스코드 알림 전용 봇.

- 파일은 절대 주고받지 않는다. 텍스트 알림과 간단한 일반 메시지 명령('상태', '목록', '웹')만 처리한다.
  '웹' 은 이 맥의 브라우저에서 업로드 페이지를 열 뿐, 디스코드로 파일을 받지 않는다.
- 명령은 DISCORD_OWNER_ID 로 지정한 본인의 메시지에만 반응한다.
- DISCORD_TOKEN / DISCORD_CHANNEL_ID 가 없으면 알림을 콘솔에만 출력한다(봇 없이도 웹은 동작).
"""
from __future__ import annotations

import asyncio
import os
import threading
from typing import Callable

import runinfo

WEB_WORDS = ("웹", "web", "업로드")        # 이 말을 보내면 맥에서 업로드 페이지를 연다 (파일은 디스코드로 보내지 않음)


class Notifier:
    def __init__(self, output_root, token: str | None, channel_id: int | None, owner_id: int | None,
                 open_web: Callable[[], str] | None = None):
        """open_web: '웹' 명령을 받으면 호출. 맥에서 업로드 페이지를 열고 안내 문구(주소 등)를 돌려준다."""
        self.open_web = open_web
        self.output_root = output_root
        self.token, self.channel_id, self.owner_id = token, channel_id, owner_id
        self._loop: asyncio.AbstractEventLoop | None = None
        self._client = None
        self._ready = threading.Event()

    @classmethod
    def from_env(cls, output_root, open_web: Callable[[], str] | None = None) -> "Notifier":
        def to_int(v):
            return int(v) if v and v.strip().isdigit() else None
        return cls(output_root, os.environ.get("DISCORD_TOKEN") or None,
                   to_int(os.environ.get("DISCORD_CHANNEL_ID")),
                   to_int(os.environ.get("DISCORD_OWNER_ID")), open_web=open_web)

    @property
    def enabled(self) -> bool:
        return bool(self.token and self.channel_id)

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
            runs = runinfo.recent_runs(self.output_root, limit=1 if word == "상태" else 5)
            return runinfo.status_text(runs)
        return None

    # ---- 봇 실행 ----
    def start(self) -> None:
        if not self.enabled:
            print("[디스코드] 토큰/채널 미설정 - 알림은 콘솔에만 출력합니다.")
            return
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
            if self.owner_id is None or msg.author.id != self.owner_id:
                return                              # 본인 외 명령 무시
            reply = self.reply_for(msg.content)
            if reply:
                await msg.channel.send(reply)

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
