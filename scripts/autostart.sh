#!/bin/bash
# 맥에 로그인하면 업로드 웹 + 디스코드 봇(src/serve.py)이 자동으로 켜지게 한다. (launchd 사용자 에이전트)
#
#   scripts/autostart.sh install     등록하고 지금 바로 시작
#   scripts/autostart.sh uninstall   해제
#   scripts/autostart.sh status      실행 중인지 확인
#   scripts/autostart.sh logs        최근 로그 보기
#
# 반드시 "메인 저장소 폴더"에서 실행하세요 (워크트리는 지워질 수 있어 자동 실행 대상으로 부적합).
# 이 폴더의 .venv 와 .env 를 사용합니다. 개인정보는 로그에 남지 않습니다(알림 문구만 기록).
set -euo pipefail

LABEL="com.jimini.serve"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
LOG="$HOME/Library/Logs/jimini-serve.log"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DOMAIN="gui/$(id -u)"

case "${1:-}" in
  install)
    if [ -f "$ROOT/.git" ]; then
      echo "워크트리에서는 등록하지 않습니다. 메인 저장소 폴더에서 실행하세요." >&2; exit 1
    fi
    [ -x "$ROOT/.venv/bin/python" ] || { echo ".venv 가 없습니다: python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2; exit 1; }
    [ -f "$ROOT/.env" ] || echo "안내: .env 가 없어 디스코드 없이 웹만 켜집니다 (.env.example 참고)."
    mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
    cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>$ROOT/.venv/bin/python</string><string>$ROOT/src/serve.py</string>
  </array>
  <key>WorkingDirectory</key><string>$ROOT</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>ThrottleInterval</key><integer>30</integer>
  <key>StandardOutPath</key><string>$LOG</string>
  <key>StandardErrorPath</key><string>$LOG</string>
</dict></plist>
EOF
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    launchctl bootstrap "$DOMAIN" "$PLIST"
    echo "등록 완료. 지금 시작했고, 맥에 로그인할 때마다 자동으로 켜집니다."
    echo "웹: http://127.0.0.1:8765   로그: $LOG"
    ;;
  uninstall)
    launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "자동 실행을 해제했습니다."
    ;;
  status)
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo "등록됨"; launchctl print "$DOMAIN/$LABEL" | grep -E "state|pid" | head -3
    else echo "등록되어 있지 않습니다."; fi
    ;;
  logs)
    tail -n 40 "$LOG"
    ;;
  *)
    sed -n '2,9p' "${BASH_SOURCE[0]}"; exit 1
    ;;
esac
