"""서버 시작 스크립트: 디스코드 알림봇을 먼저 띄운 뒤 Streamlit 을 실행한다.

Streamlit 은 누가 페이지를 열어야 app.py 를 실행하므로, 그때까지 기다리면 봇이 꺼져 있다.
같은 프로세스에서 봇을 먼저 접속시키면 서버가 켜지는 즉시 '웹' 같은 명령에 응답한다.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

import discord_notify  # noqa: E402

discord_notify.server_notifier()

from streamlit.web.cli import main  # noqa: E402

sys.argv = ["streamlit", "run", str(ROOT / "app.py"), "--server.address=0.0.0.0", "--server.port=8501",
            "--server.headless=true", "--browser.gatherUsageStats=false"]
main()
