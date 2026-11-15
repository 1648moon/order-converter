"""에이전트가 제안한 변경의 검증과 적용.

적용(apply)은 사람이 승인했을 때만 agent_chat 이 호출한다. 에이전트(LLM)에게는 이 함수를 도구로 주지 않는다.
제안 값은 모델이 만든 것이라 신뢰하지 않고, 여기서 형식·범위를 다시 검증한다.

바꿀 수 있는 것 (v1):
  - fee_rule : 미조립 상품의 택배운임 한 줄 -> rules.agent_fee_path() (factory.agent.yaml)
  - mapping  : 규칙에 없는 상품명의 공장 표기 -> product_map.yaml (status: ok)
terms.yaml 의 상품 규칙, 파일 양식, 조립 운임 같은 것은 코드/설정 PR 로만 바꾼다.
"""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

import llm_fallback
import rules

KEYWORD_OK = re.compile(r"^[0-9A-Za-z가-힣._+\-]{1,30}$")      # 모델명 조각: 따옴표·콜론·중괄호·슬래시 등 금지
MAX_FEE = 1_000_000


def validate_fee_rule(product, fee) -> tuple[str, int]:
    """('시애틀F28', 16000). 잘못된 값이면 ValueError (메시지는 사용자에게 보여도 되는 문장)."""
    name = re.sub(r"\s+", "", str(product or ""))
    if not KEYWORD_OK.match(name):
        raise ValueError("모델명은 한글·영문·숫자 30자 이내로, 색상 없이 모델 이름만 적어 주세요. 예: 시애틀F28")
    if isinstance(fee, str) and re.fullmatch(r"\d[\d,]*", fee.strip()):
        fee = int(fee.replace(",", ""))
    if isinstance(fee, float) and fee.is_integer():
        fee = int(fee)
    if isinstance(fee, bool) or not isinstance(fee, int) or not (0 < fee < MAX_FEE):
        raise ValueError("운임은 1원 이상 100만원 미만의 숫자여야 해요.")
    return name, fee


def validate_mapping(original_name, template) -> tuple[str, str]:
    name = str(original_name or "").strip()
    if not name or len(name) > 200 or "\n" in name:
        raise ValueError("원본 상품명이 올바르지 않아요.")
    if not llm_fallback.valid_template(template):
        raise ValueError("표기는 {color}(색상 자리)와 {count}(수량 자리)만 쓸 수 있어요. 예: 시애틀F28/{color}")
    return name, str(template).strip()


def describe_fee(product: str, fee: int) -> str:
    return f"'{product}' 미조립 택배운임을 {fee:,}원으로 추가"


def describe_mapping(name: str, template: str) -> str:
    return f"상품 '{name}' 의 공장 표기를 '{template.replace('{color}', '색상')}' 로 확정"


# ---- 적용 ----
def apply_fee_rule(product: str, fee: int, path: Path | None = None) -> str:
    product, fee = validate_fee_rule(product, fee)
    p = Path(path) if path else rules.agent_fee_path()
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    extra = [r for r in (data.get("shipping_rules_extra") or [])
             if not (isinstance(r, dict) and r.get("product_contains") == product and r.get("assembled") is False)]
    replaced = len(extra) != len(data.get("shipping_rules_extra") or [])
    extra.insert(0, {"assembled": False, "product_contains": product, "fee": fee})
    _atomic_write(p, "# 에이전트가 사람의 승인을 받아 추가한 미조립 운임 (코드가 운임표 위쪽에 끼워 넣는다)\n"
                  + yaml.safe_dump({"shipping_rules_extra": extra}, allow_unicode=True, sort_keys=False))
    return f"'{product}' 미조립 운임을 {fee:,}원으로 " + ("바꿨어요." if replaced else "추가했어요.")


def apply_mapping(name: str, template: str, map_path: Path | None = None) -> str:
    name, template = validate_mapping(name, template)
    p = Path(map_path) if map_path else rules.rules_dir() / "product_map.yaml"
    entries = rules.load_product_map(p)
    entries[name.replace(" ", "")] = {"name": name, "template": template, "status": "ok"}
    p.parent.mkdir(parents=True, exist_ok=True)
    rules.save_product_map(entries, p)
    return f"'{name}' 의 공장 표기를 확정했어요."


def apply(proposal: dict) -> str:
    """승인된 제안 하나를 적용하고 사용자에게 보여줄 한 줄 결과를 돌려준다. 실패하면 예외."""
    kind, params = proposal["kind"], proposal["params"]
    if kind == "fee_rule":
        return apply_fee_rule(params["product"], params["fee"])
    if kind == "mapping":
        return apply_mapping(params["name"], params["template"])
    raise ValueError(f"알 수 없는 제안 종류: {kind}")


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)
