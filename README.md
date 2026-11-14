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
- **디스코드에서 말로 요청하기:** 말투 해석·쉬운 말 보고 로직(`src/chat.py`)은 만들어져 있지만 아직 봇/웹에 연결되지 않았습니다. 현재 봇은 알림과 `상태`/`목록` 명령만 처리합니다.
- **디스코드로 파일 주고받기:** 개인정보 정책상 의도적으로 제거했습니다. 파일은 웹 화면에서만 올리고 내려받습니다.
- **서버 배포:** Oracle Cloud + Tailscale 배포 가이드(`docs/DEPLOY_ORACLE.md`)는 있으나 실제 서버 배포·운영 검증은 아직 안 됐습니다.
- **AI 상품명 제안:** 사람이 확인(`status: ok`)해야 확정되며, 완전 자동은 아닙니다.
- 새 상품·새 운임 규칙은 아직 사람이 알려줘야 `config/`에 추가됩니다.

## 실행 방법

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -I src/run_all.py input/<주문원본>.xlsx      # 전체 변환 + 검증
.venv/bin/python src/serve.py                                  # 웹 업로드 화면
```

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
- 다른 PC나 서버에 설치할 때도 같은 순서입니다(위 3가지는 따로 복사).

디스코드 알림은 `.env` 파일을 만들어 `DISCORD_TOKEN`, `DISCORD_CHANNEL_ID`, `DISCORD_OWNER_ID`를 채우면 켜집니다(파일명용 `BRAND_NAME`도 여기에). 종료코드: 0 정상 / 2 경고(파일은 생성됨) / 1 오류·검증 실패.
