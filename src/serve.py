"""웹 업로드 페이지 + 디스코드 알림 봇을 함께 실행한다.

    .venv/bin/python src/serve.py        ->  http://127.0.0.1:8765

.env (커밋 금지)에 DISCORD_TOKEN, DISCORD_CHANNEL_ID, DISCORD_OWNER_ID, BRAND_NAME 을 적는다.
OUTPUT_ROOT / INPUT_ROOT (절대경로, 선택)를 적으면 어느 폴더(워크트리 포함)에서 실행해도
결과·업로드 파일이 그 경로에 저장된다. 이 폴더에 .env 가 없으면 메인 저장소의 .env 를 읽는다.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

import discord_notify  # noqa: E402
import webapp  # noqa: E402


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            v = v.strip()
            if v[:1] not in ("'", '"'):
                v = re.split(r"\s+#", " " + v, maxsplit=1)[0].strip()   # 값 뒤 같은 줄 주석(# …) 제거
            os.environ.setdefault(k.strip(), v.strip('"').strip("'"))


def main_checkout_root() -> Path:
    """워크트리에서 실행해도 메인 저장소 폴더를 돌려준다(.git 공용 폴더의 부모)."""
    try:
        out = subprocess.run(["git", "rev-parse", "--path-format=absolute", "--git-common-dir"],
                             cwd=ROOT, capture_output=True, text=True, timeout=10, check=True).stdout.strip()
        return Path(out).parent
    except Exception:
        return ROOT


def env_path(name: str, default: Path) -> Path:
    v = os.environ.get(name)
    if not v:
        return default
    p = Path(v).expanduser()
    if not p.is_absolute():
        raise SystemExit(f"{name} 는 절대경로로 적어주세요: {v}")
    return p


def main() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        env_file = main_checkout_root() / ".env"
    load_env(env_file)
    input_dir = env_path("INPUT_ROOT", ROOT / "input")
    output_root = env_path("OUTPUT_ROOT", ROOT / "output")
    print(f"결과 저장 위치: {output_root}")
    port = int(os.environ.get("WEB_PORT", "8765"))
    url = f"http://127.0.0.1:{port}"

    def open_web() -> str:
        """디스코드 '웹' 명령: 이 맥의 기본 브라우저에서 업로드 페이지를 연다."""
        webbrowser.open(url)
        return f"웹 페이지를 열었습니다. 맥 화면에서 파일을 올려 주세요 ({url})"

    notifier = discord_notify.Notifier.from_env(output_root, open_web=open_web)
    notifier.start()
    app = webapp.create_app(ROOT, notify=notifier.notify, input_dir=input_dir, output_root=output_root)
    print(f"웹 페이지: {url}  (이 컴퓨터에서만 접속 가능)")
    app.run(host="127.0.0.1", port=port, debug=False, threaded=True)


if __name__ == "__main__":
    main()
