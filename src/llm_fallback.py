"""규칙으로 못 바꾼 상품명을 LLM 으로 변환 제안한다 (폴백).

- 상품명(고유값)만 LLM 에 보낸다. 수령자·주소·전화번호 등 개인정보는 보내지 않는다.
- 결과는 템플릿 문자열("빅마운틴/{color}(2026)")이고, 색상은 기존처럼 선택사항에서 코드가 채운다.
- 제안은 config/product_map.yaml 에 status: llm 으로 저장된다. 사람이 확인해 ok 로 바꾸면 확정.
  한 번 저장된 상품은 다시 LLM 을 부르지 않는다.
- 환경변수 ANTHROPIC_API_KEY 필요. 모델은 환경변수 ORDER_LLM_MODEL 로 바꿀 수 있다.
"""
from __future__ import annotations

import json
import os
import re
import string

MODEL = os.environ.get("ORDER_LLM_MODEL", "claude-haiku-5-5")
BATCH = 40          # 한 번에 보낼 상품명 수
MAX_EXAMPLES = 30   # 프롬프트에 넣는 확정 예시 수


def _examples(terms: dict) -> list[tuple[str, str]]:
    """확정(ok) 매핑을 few-shot 예시로 사용."""
    return [(v["name"], v["template"]) for v in (terms.get("_map") or {}).values()
            if v.get("status") == "ok"][:MAX_EXAMPLES]


def build_prompt(names: list[str], terms: dict) -> str:
    rules = "\n".join(f'- 원본 상품명에 {r["contains"]} 포함 -> 템플릿 {r["template"]!r}'
                      for r in terms["products"])
    ex = "\n".join(f"{a!r} -> {b!r}" for a, b in _examples(terms)) or "(아직 없음)"
    items = json.dumps(names, ensure_ascii=False)
    return f"""쇼핑몰 주문의 상품명을 공장 전달용 표기로 바꾸는 템플릿을 만든다.

기존 규칙 예시(이 표기 스타일을 따를 것):
{rules}

확정된 매핑 예시:
{ex}

규칙:
- 템플릿에서 색상 자리는 반드시 {{color}} 로 쓴다 (색상은 코드가 따로 채운다). 다른 중괄호 변수는 쓰지 말 것.
- 상품명에 색상이 안 들어 있으면 {{color}} 만 넣고, 원본에 없는 정보(연식·사이즈)를 지어내지 말 것.
- 확신이 없으면 그 상품은 null 로 둔다. 틀린 값을 내는 것보다 null 이 낫다.
- 출력은 JSON 객체 하나만: {{"원본 상품명": "템플릿 또는 null", ...}}. 설명 금지.

변환할 상품명:
{items}"""


def valid_template(t) -> bool:
    """str.format(color=...) 로 안전하게 쓸 수 있는 템플릿인지. {color} 외 필드·인덱싱 금지."""
    if not isinstance(t, str) or not t.strip():
        return False
    try:
        fields = [f for _, f, _, _ in string.Formatter().parse(t) if f is not None]
    except ValueError:
        return False
    return all(f == "color" for f in fields)


def parse_response(text: str, names: list[str]) -> dict[str, str]:
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return {}
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError:
        return {}
    return {n: data[n] for n in names if valid_template(data.get(n))}


def _client():
    try:
        import anthropic
    except ImportError:
        raise SystemExit("anthropic 패키지가 없습니다: pip install anthropic")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise SystemExit("ANTHROPIC_API_KEY 환경변수가 필요합니다.")
    return anthropic.Anthropic()


def suggest(names: list[str], terms: dict) -> dict[str, str]:
    """고유 상품명 목록 -> {상품명: 템플릿}. 못 바꾼 상품은 결과에서 빠진다."""
    client = _client()
    out: dict[str, str] = {}
    for i in range(0, len(names), BATCH):
        chunk = names[i:i + BATCH]
        msg = client.messages.create(
            model=MODEL, max_tokens=4096,
            messages=[{"role": "user", "content": build_prompt(chunk, terms)}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        out.update(parse_response(text, chunk))
    return out
