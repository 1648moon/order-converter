"""웹 업로드 페이지 + 디스코드 알림 봇을 함께 실행한다.

    .venv/bin/python src/serve.py        ->  http://127.0.0.1:8765

.env (커밋 금지) 예시는 .env.example 참고.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import discord_bot  # noqa: E402
import webapp  # noqa: E402


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main() -> None:
    load_env(ROOT / ".env")
    notifier = discord_bot.Notifier.from_env(ROOT / "output")
    notifier.start()
    app = webapp.create_app(ROOT, notify=notifier.notify)
    port = int(os.environ.get("WEB_PORT", "8765"))
    print(f"웹 페이지: http://127.0.0.1:{port}  (이 컴퓨터에서만 접속 가능)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
