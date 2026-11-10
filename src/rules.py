"""변환 규칙 (convert.py, validate.py 공용). 규칙 데이터는 config/terms.yaml."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_TERMS = Path(__file__).resolve().parent.parent / "config" / "terms.yaml"


def load_terms(path: Path = DEFAULT_TERMS) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


def _s(v) -> str:
    return "" if v is None else str(v)


def extract_color(option, terms: dict) -> str | None:
    text = _s(option)
    for pat in terms["color_patterns"]:
        m = re.search(pat, text)
        if m:
            return m.group(1).strip()
    return None


def convert_product(name, option, terms: dict):
    """(변환값, 경고). 변환 불가 시 (원본값, 경고메시지)."""
    text = _s(name)
    plain = text.replace(" ", "")
    for rule in terms["products"]:
        if all(k.replace(" ", "") in plain for k in rule["contains"]):
            values = {}
            color = extract_color(option, terms)
            if color is None:
                return name, "색상을 선택사항에서 찾지 못함"
            values["color"] = color
            for var, pats in (rule.get("vars") or {}).items():
                for pat in pats:
                    m = re.search(pat, text)
                    if m:
                        values[var] = m.group(1)
                        break
                else:
                    return name, f"상품명에서 '{var}' 값을 찾지 못함"
            return rule["template"].format(**values), None
    return name, "변환 표에 없는 상품"


def convert_option(option, terms: dict):
    text = _s(option)
    for rule in terms["options"]:
        if rule["keyword"] in text:
            return (rule["value"] or None), None
    return option, "변환 표에 없는 선택사항"


def make_extra(receiver, address, terms: dict) -> str:
    n = terms["insert_column"]["address_chars"]
    return f"{_s(receiver)}({_s(address).strip()[:n]})"
