"""에이전트(LLM)에게 주는 도구. 읽기 도구와 '제안' 도구만 있고, 적용(apply) 도구는 없다.

- 모든 출력은 개인정보 없는 값(상품명·건수·단계 이름)뿐이고, 마지막에 전화번호 모양을 한 번 더 걸러 낸다.
- 제안 도구는 agent_state 에 '대기 중' 제안을 저장할 뿐이다. 실제 적용은 사람이 승인한 뒤 agent_chat 이 한다.
- 운임 금액은 에이전트가 직접 제안한 것(사람이 대화에서 말한 값)만 보여 주고, 기존 운임표 금액은 보여 주지 않는다.
- 상품명은 주문 파일에서 온 '믿을 수 없는 텍스트'다. 그래서 값 검증은 agent_rules 가 코드로 다시 한다.
"""
from __future__ import annotations

import re

import agent_rules
import rules
from agent_state import Store
from run_report import PHONE_RE

TOOLS = [
    {
        "name": "get_latest_run",
        "description": "가장 최근에 웹에서 변환한 결과 요약을 본다. 주문 건수, 전체 결과, 확인이 필요한 상품명"
                       "(변환 표에 없는 상품, 운임표에 없는 상품)이 들어 있다. 개인정보는 없다.",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "get_naming_examples",
        "description": "기존 상품명 변환 규칙의 예시(원본 상품명에 들어 있는 말 -> 공장 표기 템플릿). "
                       "새 상품의 표기를 제안할 때 같은 스타일을 따르기 위해 본다.",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
    {
        "name": "check_fee_rule",
        "description": "이 모델 이름에 대해 미조립 운임 규칙이 이미 있는지 확인한다. 기존 금액은 알려 주지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"product": {"type": "string", "description": "모델 이름만(색상 없이). 예: 시애틀F28"}},
            "required": ["product"], "additionalProperties": False},
    },
    {
        "name": "propose_fee_rule",
        "description": "미조립 상품의 택배운임 규칙 추가를 '제안'한다. 사람이 승인해야 적용된다. "
                       "사용자가 운임 금액을 직접 말한 경우에만 호출하고, 금액을 추측하지 않는다.",
        "input_schema": {
            "type": "object",
            "properties": {"product": {"type": "string", "description": "모델 이름만(색상 없이). 예: 시애틀F28"},
                           "fee": {"type": "integer", "description": "택배운임(원)"}},
            "required": ["product", "fee"], "additionalProperties": False},
    },
    {
        "name": "propose_product_mapping",
        "description": "변환 표에 없는 상품의 공장 표기 확정을 '제안'한다. 사람이 승인해야 적용된다. "
                       "original_name 은 get_latest_run 의 '변환 표에 없는 상품' 목록에 있는 이름 그대로여야 한다. "
                       "template 의 색상 자리는 {color}, 수량 자리는 {count} 로 쓴다. 예: 시애틀F28/{color}",
        "input_schema": {
            "type": "object",
            "properties": {"original_name": {"type": "string"}, "template": {"type": "string"}},
            "required": ["original_name", "template"], "additionalProperties": False},
    },
    {
        "name": "list_pending_proposals",
        "description": "아직 사람이 승인하지 않은 변경 제안 목록.",
        "input_schema": {"type": "object", "properties": {}, "required": [], "additionalProperties": False},
    },
]


def scrub(obj):
    """출력에서 전화번호 모양의 숫자열을 지운다 (상품명에 섞여 들어오는 경우 대비)."""
    if isinstance(obj, str):
        return PHONE_RE.sub("[숨김]", obj)
    if isinstance(obj, list):
        return [scrub(x) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v) for k, v in obj.items()}
    return obj


def _fee_rule_exists(product: str) -> bool:
    import factory as F
    return F.shipping_fee_info(product, None, F.load_cfg())[1]


def _agent_fee(product: str):
    for r in rules.load_agent_fee_rules():
        if r["product_contains"] == product and r.get("assembled") is False:
            return r["fee"]
    return None


def run_tool(name: str, args: dict, store: Store) -> dict:
    try:
        return scrub(_run(name, args or {}, store))
    except ValueError as e:                      # 검증 실패: 모델에게 이유를 알려 다시 묻게 한다
        return {"error": str(e)}
    except Exception as e:                       # 예상 못한 오류는 종류만 알린다 (경로·값 노출 방지)
        return {"error": f"도구 실행 중 오류({type(e).__name__})"}


def _run(name: str, args: dict, store: Store) -> dict:
    if name == "get_latest_run":
        run = store.latest_run()
        if not run:
            return {"available": False, "message": "아직 서버에서 변환한 기록이 없어요. 웹에서 파일을 올려 주세요."}
        return {"available": True, **{k: run[k] for k in (
            "run", "overall", "files", "orders", "warn_stages", "fail_stages",
            "unmatched_products", "fee_missing_products", "partial") if k in run}}

    if name == "get_naming_examples":
        terms = rules.load_terms()
        pairs = [{"원본에_들어_있는_말": r["contains"], "템플릿": r["template"]} for r in terms["products"]][:40]
        return {"rules": pairs, "note": "{color}=색상 자리, {count}=수량 자리"}

    if name == "check_fee_rule":
        product, _ = agent_rules.validate_fee_rule(args.get("product"), 1)
        out = {"product": product, "has_rule": _fee_rule_exists(product)}
        added = _agent_fee(product)
        if added is not None:
            out["added_by_agent_fee"] = added
        return out

    if name == "propose_fee_rule":
        product, fee = agent_rules.validate_fee_rule(args.get("product"), args.get("fee"))
        summary = agent_rules.describe_fee(product, fee)
        if _fee_rule_exists(product):
            summary += " (같은 모델의 기존 운임표 규칙보다 먼저 적용돼요)"
        p = store.add_proposal("fee_rule", {"product": product, "fee": fee}, summary)
        return {"proposal_id": p["id"], "status": "awaiting_human_approval", "summary": p["summary"]}

    if name == "propose_product_mapping":
        orig, template = agent_rules.validate_mapping(args.get("original_name"), args.get("template"))
        run = store.latest_run() or {}
        known = {re.sub(r"\s+", "", n): n for n in run.get("unmatched_products", [])}
        exact = known.get(re.sub(r"\s+", "", orig))
        if exact is None:
            raise ValueError("이 상품명은 최근 변환에서 '변환 표에 없는 상품'으로 나온 이름이 아니에요. "
                             "get_latest_run 의 목록에 있는 이름을 그대로 써 주세요.")
        p = store.add_proposal("mapping", {"name": exact, "template": template},
                               agent_rules.describe_mapping(exact, template))
        return {"proposal_id": p["id"], "status": "awaiting_human_approval", "summary": p["summary"]}

    if name == "list_pending_proposals":
        return {"pending": [{"id": p["id"], "summary": p["summary"]} for p in store.pending()]}

    raise ValueError(f"없는 도구: {name}")
