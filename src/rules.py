"""변환 규칙 (convert.py, validate.py 공용). 규칙 데이터는 config/terms.yaml."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_TERMS = Path(__file__).resolve().parent.parent / "config" / "terms.yaml"
DEFAULT_MAP = DEFAULT_TERMS.with_name("product_map.yaml")
LLM_WARN = "LLM 제안값 적용(미확인)"   # convert_product 경고 접두어. 확인 후 product_map.yaml 의 status 를 ok 로


def load_product_map(path: Path = DEFAULT_MAP) -> dict:
    """{원본 상품명(공백제거): {"template", "status", "name"}}. 파일이 없으면 빈 dict."""
    p = Path(path)
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    return {k.replace(" ", ""): {**v, "name": k} for k, v in (data.get("map") or {}).items()}


def save_product_map(entries: dict, path: Path = DEFAULT_MAP) -> None:
    out = {v["name"]: {"template": v["template"], "status": v["status"]} for v in entries.values()}
    header = ("# 규칙(terms.yaml)으로 못 바꾸는 상품명의 1:1 매핑. LLM 제안은 status: llm 으로 저장된다.\n"
              "# 내용을 확인해 맞으면 status 를 ok 로 바꾼다. 틀리면 template 을 고치고 ok 로 둔다.\n"
              "# template 의 {color} 는 선택사항에서 뽑은 색상으로 치환된다.\n")
    Path(path).write_text(header + yaml.safe_dump({"map": out}, allow_unicode=True, sort_keys=False),
                          encoding="utf-8")


def load_terms(path: Path = DEFAULT_TERMS, map_path: Path = DEFAULT_MAP) -> dict:
    terms = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    terms["_map"] = load_product_map(map_path)
    return terms


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
    hit = (terms.get("_map") or {}).get(plain)
    if hit:
        color = extract_color(option, terms)
        if color is None and "{color}" in hit["template"]:
            return name, "색상을 선택사항에서 찾지 못함"
        value = hit["template"].format(color=color)
        return value, (LLM_WARN if hit["status"] != "ok" else None)
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
