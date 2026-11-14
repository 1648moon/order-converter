# Order Converter — 주문 엑셀 변환 에이전트

## 1. 누구를 위한 에이전트이고, 어떤 일을 하나요?

**대상:** 브랜드에서 하루 두 번(오전/오후) 쇼핑몰 주문 엑셀을 받아 공장·택배사에 전달할 파일을 만드는 담당자.
개발자가 아니어도 쓸 수 있도록, 웹 화면에 파일을 올리거나 에이전트에게 말로 요청하는 방식을 목표로 합니다.

**하는 일:** 주문 원본 엑셀 1개를 넣으면 아래 파일을 자동으로 만들고, 단계마다 원본과 결과가 같은지 검증합니다.

| 단계 | 결과 파일 | 내용 |
|---|---|---|
| 변환 | 중간파일 | 상품명을 `모델/색상`으로 축약, 선택사항을 `100%조립요청`으로 정리, 수령자 주소 앞 3글자 추가 |
| 공장용 | `YY-MM-DD 브랜드주문(1\|2)-버전` | 택배운임(조립/미조립 등)·결제조건 반영, 경동 기준 |
| 공장용(CJ) | `… 브랜드주문(1\|2)-CJ` | 택배사가 CJ대한통운인 주문만 따로 (고정 운임) |
| 택배용 | `YY-MM-DD 브랜드주문(합동)-신안-오전\|오후` | 택배 접수용 고정값·운임 매핑 |
| 내부보관용 | `YY-MM-DD 발송내역` | 접수일자, 수화주명, 상품별 집계표 |

- 파일명은 요청 시각(12시 전=오전, 후=오후)과 같은 날 재작업 횟수에 따라 자동으로 정해집니다.
- 파일명에 들어가는 브랜드명은 소스에 두지 않고 `.env`의 `BRAND_NAME`에서 읽습니다(없으면 "브랜드").
- `config/factory.yaml`의 택배운임은 샘플값입니다. 실제 운임은 같은 폴더의 `config/factory.local.yaml`(커밋 금지, `.gitignore`)에 `shipping_rules`·`default_fee`·`carriers: {cj_fee: …}`를 적으면 샘플 위에 덮어씁니다. 딕셔너리는 항목별로, `shipping_rules` 같은 리스트는 통째로 교체되니 전체 목록을 적으세요. 이 파일은 저장소에 없으니 따로 백업하세요.
- 클레임 주문은 산출물에서 제외됩니다.
- 규칙은 코드가 아니라 `config/*.yaml`(상품 변환표, 운임표, 택배 고정값 등)에서 관리합니다.
- **개인정보 원칙:** 이름·전화번호·주소가 든 파일은 외부로 보내지 않습니다. 디스코드에는 건수·상품명 같은 개인정보 없는 알림만 보냅니다.

## 2. 진행 상황

### 지금 되는 것
- 주문 엑셀 → 중간파일 → 공장용(경동/CJ) → 택배용 → 내부보관용 변환 (`src/run_all.py` 한 번 실행)
- 단계별 원본 대비 검증 (`validate*.py`), 결과를 `output/YYYY-MM-DD_vN/`에 모으고 `실행요약.txt` 생성
- 파일명 규칙 자동 적용 (`src/naming.py`), 공장/택배 템플릿 서식 유지 (`templates/`)
- 변환표에 없는 상품·운임표에 없는 모델은 경고로 알려주고 주황색으로 표시
- 규칙에 없는 상품명을 AI가 제안 (`--llm`, `ANTHROPIC_API_KEY` 필요). 제안은 사람이 확인하기 전까지 "미확인"으로 표시
- 내 맥에서 쓰는 웹 업로드 화면 (`src/serve.py` → http://127.0.0.1:8765)과 디스코드 알림 전용 봇
- Streamlit 웹앱(`app.py`, 비밀번호 보호)과 Docker 구성
- 테스트 통과 (`tests/test_*.py` 13개, assert 방식 스크립트라 `unittest discover`로는 안 잡힙니다. 아래 '깃허브 코드로 확인하기'의 반복문으로 실행)

### 아직 안 되는 것 / 남은 일
- **디스코드에서 말로 요청하기:** 말투 해석·쉬운 말 보고 로직(`src/chat.py`)은 만들어져 있지만 아직 봇/웹에 연결되지 않았습니다. 현재 봇은 알림과 `상태`/`목록`/`웹` 명령만 처리합니다.
- **디스코드로 파일 주고받기:** 개인정보 정책상 의도적으로 제거했습니다. 파일은 웹 화면에서만 올리고 내려받습니다.
- **서버 배포:** Oracle Cloud(AMD 무료 VM) + Tailscale 로 배포해 사설망에서 접속되는 것까지 확인했습니다(`docs/DEPLOY_ORACLE.md`). 실제 주문 파일로 장기간 운영하며 검증하는 것은 앞으로 할 일입니다.
- **AI 상품명 제안:** 사람이 확인(`status: ok`)해야 확정되며, 완전 자동은 아닙니다.
- 새 상품·새 운임 규칙은 아직 사람이 알려줘야 `config/`에 추가됩니다.

## 실행 방법

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I src/run_all.py input/<주문원본>.xlsx      # 전체 변환 + 검증
.venv/bin/python src/serve.py                                  # 웹 업로드 화면 (http://127.0.0.1:8765)
```

### 디스코드에서 `웹` 한 마디로 업로드 화면 열기
- 알림 채널에서 본인이 `웹`(또는 `web`, `업로드`)이라고 보내면 이 맥의 브라우저에서 업로드 화면이 열립니다. 디스코드로는 텍스트 안내만 오가고 파일은 올리지 않습니다. 정확히 그 단어만 인식합니다.
- 맥이 켜져 있고 `serve.py`가 실행 중이어야 합니다. 로그인할 때마다 자동으로 켜지게 하려면 **메인 저장소 폴더**에서 한 번 실행하세요.
  ```bash
  scripts/autostart.sh install      # 해제: uninstall, 확인: status, 로그: logs
  ```

## 깃허브에서 받아 내 컴퓨터에 설치하기 (기존 로컬 파일이 있는 사용자)

이미 이 프로그램을 쓰고 있어서 깃허브에 없는 파일(실제 운임, `.env`, 지난 작업 기록)을 갖고 있는 경우의 순서입니다. 코드는 깃허브에서, 비공개 파일은 기존 폴더에서 가져옵니다.

### 1) 깃허브에 없는 파일 (기존 폴더에서 옮길 것)

| 파일/폴더 | 내용 | 없으면 |
|---|---|---|
| `.env` | 브랜드명(`BRAND_NAME`), 디스코드 설정, 입출력 폴더 경로 | 파일명이 `브랜드주문`으로 나오고 디스코드 알림이 꺼집니다 |
| `config/factory.local.yaml` | 실제 택배운임 (샘플 운임 위에 덮어씀) | 운임이 샘플값으로 나옵니다 (금액이 틀림) |
| `output/` | 이전 결과 폴더 (공장용 파일명 버전 `-1`, `-2`…은 이 폴더 안의 기존 파일을 보고 이어서 매깁니다) | 같은 날 버전 번호가 `-1`부터 다시 시작해 이미 보낸 파일과 이름이 겹칠 수 있습니다 |
| `input/` | 주문 원본 (개인정보 파일, 깃허브 업로드 금지) | 새로 올리면 되므로 필수는 아닙니다 |
| `state/` | Streamlit 앱(`app.py`)의 파일명 기록 | Streamlit 앱을 쓸 때만 필요합니다 |

이 파일들은 저장소에 없으므로 **따로 백업**하세요. 폴더를 지우기 전에 위 파일들을 복사해 두세요.

### 2) 설치 순서

```bash
# ① 코드 받기
git clone <저장소 주소> jimini && cd jimini

# ② 파이썬 환경 만들고 패키지 설치 (Python 3.10 이상 권장)
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# ③ 기존 폴더에서 비공개 파일 복사 (경로는 본인 것으로)
OLD=~/기존/jimini폴더
cp "$OLD/.env" .
cp "$OLD/config/factory.local.yaml" config/
cp -R "$OLD/output" .      # 버전 번호 이어가기용 (용량이 크면 최근 며칠 치만)
```

### 3) `.env` 내용

`.env`는 `KEY=값` 한 줄씩 적는 텍스트 파일입니다. 새로 만든다면 아래 항목을 채우세요(모두 선택, 필요한 것만).

```
BRAND_NAME=내브랜드          # 파일명에 들어가는 이름 (없으면 "브랜드")
DISCORD_TOKEN=...            # 디스코드 알림 봇 (세 개가 모두 있어야 켜집니다)
DISCORD_CHANNEL_ID=...
DISCORD_OWNER_ID=...
INPUT_ROOT=/절대/경로/input    # 업로드 파일 저장 폴더 (기본: 저장소 안 input/)
OUTPUT_ROOT=/절대/경로/output  # 결과 폴더 (기본: 저장소 안 output/)
# WEB_PORT=8765              # 웹 화면 포트 (기본 8765)
# ANTHROPIC_API_KEY=...      # --llm 옵션(AI 상품명 제안)을 쓸 때만
```

옛 `INPUT_ROOT`/`OUTPUT_ROOT`가 이전 PC의 경로(`/Users/…`)라면 새 PC 경로로 **꼭 고치세요.** 그대로 두면 없는 폴더를 가리킵니다.

### 4) 제대로 설정됐는지 확인

```bash
# 테스트 (하나라도 FAIL이면 코드/환경 문제)
for f in tests/test_*.py; do PYTHONPATH=src .venv/bin/python -I "$f" >/dev/null 2>&1 && echo "pass $f" || echo "FAIL $f"; done

# 주문 원본 1개로 실제 변환 (종료코드 0, 8단계 모두 [정상]이면 통과)
.venv/bin/python -I src/run_all.py input/<주문원본>.xlsx; echo "exit=$?"
```

- 생성된 파일명에 내 브랜드명이 보이면 `.env`가 적용된 것이고, 운임이 실제 값이면 `factory.local.yaml`이 적용된 것입니다.
- 샘플 운임으로만 확인하고 싶으면 `FACTORY_IGNORE_LOCAL=1`을 앞에 붙여 실행하세요.

### 5) 코드 업데이트 받기

```bash
git pull
.venv/bin/pip install -r requirements.txt    # 패키지가 바뀌었을 수 있음
```

비공개 파일은 `.gitignore` 대상이라 `git pull`로 덮어써지거나 지워지지 않습니다. 단, `config/factory.yaml`의 샘플 운임 항목이 바뀌어도 `factory.local.yaml`이 그 위에 덮어쓰므로, 새로 생긴 규칙 항목이 있으면 `factory.local.yaml`에도 반영해야 하는지 확인하세요(리스트 항목은 통째로 교체됩니다).

## 깃허브에 올린 코드만으로 되는지 확인하기 (클린 클론 검증)

내 컴퓨터에서는 저장소에 없는 파일(`.env`, `config/factory.local.yaml`, `input/`) 덕분에 돌아가는 것일 수 있습니다. 아래처럼 깃허브에서 새로 받은 폴더에서 돌려 보면, 올라간 코드만으로 되는지 확인됩니다.

```bash
git clone <저장소 주소> /tmp/jimini-check && cd /tmp/jimini-check
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# 1) 테스트: 파일마다 직접 실행 (하나라도 FAIL이면 문제)
for f in tests/test_*.py; do PYTHONPATH=src .venv/bin/python -I "$f" >/dev/null 2>&1 && echo "pass $f" || echo "FAIL $f"; done

# 2) 실제 변환: 주문 원본을 input/ 에 복사해서 실행 (종료코드 0 이면 정상)
mkdir -p input && cp ~/내주문원본.xlsx input/
.venv/bin/python -I src/run_all.py input/내주문원본.xlsx; echo "exit=$?"
```

- 결과는 `output/YYYY-MM-DD_vN/`(최신본은 `output/latest/`)에 생기고, 8단계가 모두 `[정상]`이면 통과입니다.
- **깃허브에 없는 것(클론에 따로 옮겨야 같은 결과):** 주문 원본(`input/`, 개인정보라 커밋 금지), `.env`(브랜드명·디스코드 설정), `config/factory.local.yaml`(실제 운임).
  - 클론에서 그냥 돌리면 파일명은 `브랜드주문`, 택배운임은 샘플값으로 나옵니다. 변환 자체는 되지만 운임 금액은 실제와 다릅니다. 실제 운임까지 같은지 보려면 `factory.local.yaml`을 복사해 넣고 다시 돌려 비교하세요.
- 다른 PC나 서버에 설치할 때는 바로 위 "깃허브에서 받아 내 컴퓨터에 설치하기" 순서를 따르세요.

디스코드 알림은 `.env` 파일을 만들어 `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_OWNER_ID`를 채우면 켜집니다(파일명용 `BRAND_NAME`도 여기에). 종료코드: 0 정상 / 2 경고(파일은 생성됨) / 1 오류·검증 실패.
