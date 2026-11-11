"""디스코드 봇의 '말로 하는' 부분: 말투 해석, 쉬운 말 보고, LLM 제안 확인, 운임 규칙 추가.

디스코드 접속과 무관한 순수 함수 위주라 네트워크 없이 테스트할 수 있다 (tests/test_chat.py).
개인정보(수령자·주소·전화번호)는 다루지 않는다. 상품명·행 번호·건수만 사용한다.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import factory as F
import rules
import llm_fallback

FACTORY_YAML = Path(__file__).resolve().parent.parent / "config" / "factory.yaml"

YES = {"네", "넵", "넹", "예", "응", "ㅇㅇ", "ok", "okay", "오케이", "맞아", "맞아요", "좋아", "좋아요", "그래", "그래요", "y", "yes"}
NO = {"아니", "아니요", "아뇨", "아님", "ㄴㄴ", "틀려", "틀렸어", "틀렸어요", "no", "n"}
SKIP = {"건너뛰기", "건너뛰어", "나중에", "패스", "스킵", "skip", "보류"}


def _norm(text: str) -> str:
    return re.sub(r"[\s.!?~,]+", "", text.strip().lower())


def answer_kind(text: str) -> str | None:
    """확인 질문에 대한 답: 'yes' | 'no' | 'skip' | None(그 밖의 말)."""
    t = _norm(text)
    if t in YES:
        return "yes"
    if t in NO or t.startswith("아니"):
        return "no"
    if t in SKIP or t.startswith("건너뛰"):
        return "skip"
    return None


def parse_ampm(text: str) -> str | None:
    if re.search(r"오후|午後|pm\b", text, re.I):
        return "오후"
    if re.search(r"오전|am\b", text, re.I):
        return "오전"
    return None


def default_ampm(now: datetime | None = None) -> str:
    return "오전" if (now or datetime.now()).hour < 12 else "오후"


def is_start(text: str) -> bool:
    """'오늘 오전 주문 처리할게요' 같은 시작 인사 (파일 없이 온 글). 요청·질문 문장은 시작으로 보지 않는다."""
    t = text.strip()
    if len(t) > 60 or parse_fee_rule(t) is not None or re.search(r"[?？]|줘|주세요|알려|보내|뭐|어떻게|왜", t):
        return False
    return bool(re.search(r"(주문|변환|작업|처리).{0,12}(할게|할께|하자|할래|하려|해야|하겠|할\s*거|시작)|시작|안녕|^(start|hi|hello)$", t, re.I))


# ── 운임 규칙을 말로 추가 ───────────────────────────────────────────────
_FEE = re.compile(r"^(?P<p>.+?)\s*(?P<a>미조립|조립)?\s*(?:택배\s*)?운임(?:은|이|를|을)?\s*(?P<fee>\d[\d,]*)\s*원?\s*(?:으?로|이야|야|입니다|예요|요|추가|등록|해줘|해\s*주세요|\.|!|\s)*$")


def parse_fee_rule(text: str) -> tuple[str, int] | None:
    """'시애틀F28 미조립 운임 16000' -> ('시애틀F28', 16000). 미조립 규칙만 지원."""
    m = _FEE.match(text.strip())
    if not m or m.group("a") == "조립":
        return None
    product = re.sub(r"\s+", "", m.group("p"))
    product = re.sub(r"(은|는|이|가)$", "", product)
    fee = int(m.group("fee").replace(",", ""))
    if not product or len(product) > 30 or re.search(r"""["'{}\\:#\n]""", product) or not (0 < fee < 1_000_000):
        return None
    return product, fee


def add_fee_rule(product: str, fee: int, path: Path = FACTORY_YAML) -> str:
    """config/factory.yaml 의 shipping_rules 맨 위(조립 규칙 바로 아래)에 미조립 규칙 한 줄을 넣는다.
    factory.local.yaml 에 shipping_rules 가 있으면(실제 운임) 그쪽이 샘플을 덮어쓰므로 거기에 넣는다.
    돌려주는 값: 사용자에게 보여 줄 한 줄 결과."""
    local = F.local_path(path)
    if local.exists() and re.search(r"^shipping_rules:", local.read_text(encoding="utf-8"), re.M):
        path = local
    text = path.read_text(encoding="utf-8")
    if re.search(rf'product_contains:\s*"{re.escape(product)}"', text):
        return f"'{product}' 운임은 이미 등록돼 있어요. 바꾸려면 config/{path.name} 에서 직접 고쳐 주세요."
    lines = text.splitlines(keepends=True)
    idx = next((i for i, ln in enumerate(lines) if ln.startswith("shipping_rules:")), None)
    if idx is None:
        return "운임표(shipping_rules)를 찾지 못해 추가하지 못했어요."
    # 첫 규칙(assembled: true)은 모델 무관 규칙이라, 그 다음 줄에 넣어야 구체적인 상품이 위쪽에 온다
    insert_at = idx + 1
    while insert_at < len(lines) and lines[insert_at].lstrip().startswith("- {assembled: true"):
        insert_at += 1
    lines.insert(insert_at, f'  - {{assembled: false, product_contains: "{product}", fee: {fee}}}\n')
    path.write_text("".join(lines), encoding="utf-8")
    return f"'{product}' 미조립 운임 {fee:,}원을 운임표에 추가했어요."


# ── LLM 제안 확인 ───────────────────────────────────────────────────────
def pending_items(map_path: Path = rules.DEFAULT_MAP) -> list[tuple[str, str, str]]:
    """확인이 필요한 LLM 제안: [(맵 키, 원본 상품명, 템플릿)]"""
    return [(k, v["name"], v["template"]) for k, v in rules.load_product_map(map_path).items()
            if v.get("status") != "ok"]


def question(name: str, template: str, i: int, n: int) -> str:
    example = template.replace("{color}", "블랙")
    return (f"({i}/{n}) '{name}' 은(는) 공장 표기로 **{example}** 라고 바꿨어요. 맞나요?\n"
            f"맞으면 '네', 틀리면 '아니요', 나중에 볼 거면 '건너뛰기'라고 답해 주세요.")


def resolve(key: str, kind: str, new_template: str | None = None, map_path: Path = rules.DEFAULT_MAP) -> bool:
    """답에 따라 매핑을 확정한다. 내용이 바뀌었으면 True (다시 변환 필요)."""
    entries = rules.load_product_map(map_path)
    if key not in entries or kind == "skip":
        return False
    if kind == "yes":
        entries[key]["status"] = "ok"
        rules.save_product_map(entries, map_path)
        return False
    if kind == "edit" and new_template and llm_fallback.valid_template(new_template):
        entries[key].update(template=new_template.strip(), status="ok")
        rules.save_product_map(entries, map_path)
        return True
    return False


def color_hint(text: str) -> str:
    """직접 입력 템플릿에서 '색상'/'블랙' 같은 말 대신 {color} 를 쓰도록 안내하는 문구."""
    return "색상이 들어갈 자리는 {color} 라고 써 주세요. 예: 시애틀F28/{color}"


# ── 쉬운 말 보고 ────────────────────────────────────────────────────────
def count_orders(path: Path) -> int:
    from convert import KEY, data_rows, header_map
    from openpyxl import load_workbook
    wb = load_workbook(path, read_only=False)
    ws = wb.active
    h = header_map(ws)
    return len(data_rows(ws, h[KEY])) if KEY in h else 0


def file_product_keys(path: Path) -> set[str]:
    """이 주문 파일에 들어 있는 상품명(공백 제거) 집합 - LLM 제안 중 이번 파일에 해당하는 것만 묻기 위함."""
    from convert import KEY, data_rows, header_map
    from openpyxl import load_workbook
    ws = load_workbook(path).active
    h = header_map(ws)
    if KEY not in h or "상품명" not in h:
        return set()
    return {str(ws.cell(r, h["상품명"]).value or "").replace(" ", "") for r in data_rows(ws, h[KEY])}


def friendly_summary(code: int, lines: list[str], n_orders: int | None = None) -> str:
    """run_all 출력 -> 쉬운 말. 종료코드·경로 같은 개발용 표현은 쓰지 않는다."""
    if code not in (0, 2):
        tail = "\n".join(f"  {ln.strip()}" for ln in lines[-8:])
        return ("❌ 변환하지 못했어요. 파일 양식이나 필수 열이 맞는지 확인해 주세요.\n"
                f"참고용 메시지:\n{tail}")
    head = f"주문 {n_orders}건" if n_orders else "주문"
    unmatched = sum("변환 표에 없는 상품" in ln for ln in lines)
    ship = sorted({m.group(1) for ln in lines if (m := re.search(r"운임표에 없는 상품 '([^']+)'", ln))})
    llm_applied = sum(rules.LLM_WARN in ln for ln in lines)
    known = ("변환 표에 없는 상품", "운임표에 없는 상품", rules.LLM_WARN)
    other = [ln for ln in lines if ln.strip().startswith("경고") and not any(k in ln for k in known)]
    out = [f"✅ {head} 변환을 마쳤어요. 공장용·택배용·내부보관용 파일을 준비했어요."
           if code == 0 else f"✅ {head} 변환을 마쳤어요. 다만 확인할 게 있어요."]
    if unmatched:
        out.append(f"• 상품명 {unmatched}건은 자동으로 바꾸지 못해 원본 그대로 두었어요.")
    if llm_applied:
        out.append(f"• 상품명 {llm_applied}건은 AI가 제안한 표기로 바꿨어요 (아래에서 확인해 주세요).")
    if ship:
        out.append("• 운임을 모르는 상품: " + ", ".join(ship)
                   + "\n  → '시애틀F28 미조립 운임 16000' 처럼 말해 주시면 운임표에 추가하고 다시 변환할게요.")
    if other:
        out.append(f"• 그 밖에 확인할 경고가 {len(other)}건 있어요. 궁금하면 '경고 알려줘'라고 말해 주세요.")
    return "\n".join(out)


AGENT_STYLE = (
    "[답변 지침] 사용자는 개발자가 아니다. 쉬운 한국어로 짧게 답하고, 종료코드·스크립트 이름·파일 경로 같은 "
    "개발 용어는 쓰지 마라. 확인이 필요한 건 한 번에 하나씩 물어라. 개인정보(이름·전화·주소)는 말하지 마라."
)
