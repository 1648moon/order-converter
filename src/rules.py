"""변환 규칙 (convert.py, validate.py 공용). 규칙 데이터는 config/terms.yaml."""
from __future__ import annotations

import re
from pathlib import Path

import yaml

DEFAULT_TERMS = Path(__file__).resolve().parent.parent / "config" / "terms.yaml"
DEFAULT_MAP = DEFAULT_TERMS.with_name("product_map.yaml")
STORAGE_CFG = DEFAULT_TERMS.with_name("storage.yaml")   # 내부 정산(내부보관용)의 축약 자전거명 목록(product_list)
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


def load_bike_names(path: Path = STORAGE_CFG) -> list[str]:
    """내부 정산 파일에 쓰는 축약 자전거명 목록 (예: '시애틀MT24/블랙'). 파일이 없으면 빈 리스트."""
    p = Path(path)
    data = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}) if p.exists() else {}
    return [str(x) for x in (data.get("product_list") or [])]


def load_terms(path: Path = DEFAULT_TERMS, map_path: Path = DEFAULT_MAP) -> dict:
    terms = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    terms["_map"] = load_product_map(map_path)
    terms["_bikes"] = load_bike_names()
    return terms


def _s(v) -> str:
    return "" if v is None else str(v)


def extract_color(option, terms: dict) -> str | None:
    text = _s(option)
    for pat in terms["color_patterns"]:
        m = re.search(pat, text)
        if m:
            color = re.sub(r"\(.*?\)", "", m.group(1))          # 라이트핑크(무광) -> 라이트핑크
            color = re.sub(r"[-\s]*\d+\s*개$", "", color)       # 블루-1개 -> 블루
            if color.strip():
                return color.strip()
            # 비었으면(예: '미조립 1개' 에서 '1개' 만 잡힘) 다음 패턴을 계속 시도한다
    return None


def count_suffix(option) -> str:
    """선택사항의 'N개'가 2 이상이면 '/N개', 아니면 빈 문자열. 템플릿의 {count} 자리에 들어간다."""
    nums = [int(n) for n in re.findall(r"(\d+)\s*개", _s(option))]
    return f"/{nums[0]}개" if nums and nums[0] > 1 else ""


def find_rule(name, terms: dict):
    plain = _s(name).replace(" ", "")
    for rule in terms["products"]:
        if all(k.replace(" ", "") in plain for k in rule["contains"]):
            return rule
    return None


def render(template: str, **values) -> str:
    """템플릿 채우기. 색상이 비면(선택사항에 색상 없음) '/색상' 자리를 적지 않는다.
    '삼천리SL360사슬형번호키자물쇠/{color}{count}' + color='' -> '삼천리SL360사슬형번호키자물쇠' (count 가 있으면 '…/2개')."""
    if not values.get("color"):
        template = template.replace("/{color}", "{color}")   # '빅마운틴/{color}(2026)' -> '빅마운틴(2026)'
    for var in [k for k, v in values.items() if not v]:       # 값이 빈 변수의 '({var})' 괄호째 생략
        template = template.replace(f"({{{var}}})", "")       # '빅마운틴/{color}({year})' + year='' -> '빅마운틴/{color}'
    return template.format(**values)


def convert_product(name, option, terms: dict):
    """(변환값, 경고). 변환 불가 시 (원본값, 경고메시지). 색상이 없으면 '/색상' 부분은 생략한다."""
    text = _s(name)
    plain = text.replace(" ", "")
    if plain in {_s(x).replace(" ", "") for x in terms.get("passthrough_products") or []}:
        return name, None       # 이름을 바꾸지 않는 상품(예: 추가상품). 경고 없이 원본 유지
    for rule in terms["products"]:
        if all(k.replace(" ", "") in plain for k in rule["contains"]):
            values = {}
            values["color"] = extract_color(option, terms) or ""
            values["count"] = count_suffix(option)
            skip = False
            for var, pats in (rule.get("vars") or {}).items():
                for pat in pats:
                    m = re.search(pat, text)
                    if m:
                        values[var] = m.group(1)
                        break
                else:
                    if var in (rule.get("defaults") or {}):
                        values[var] = str(rule["defaults"][var])   # 상품명에 없으면 기본값 (예: 연식 -> 2026)
                        continue
                    if var in (rule.get("optional_vars") or []):
                        values[var] = ""      # 없어도 되는 값: 공란으로 두고 템플릿에서 괄호째 생략
                        continue
                    if rule.get("fallthrough"):
                        skip = True           # 값을 못 찾으면 경고 대신 아래의 다음 규칙으로 넘어간다
                        break
                    return name, f"상품명에서 '{var}' 값을 찾지 못함"
            if skip:
                continue
            return render(rule["template"], **values), None
    hit = (terms.get("_map") or {}).get(plain)
    if hit:
        value = render(hit["template"], color=extract_color(option, terms) or "", count=count_suffix(option))
        return value, (LLM_WARN if hit["status"] != "ok" else None)
    return name, "변환 표에 없는 상품"


def convert_option(option, terms: dict, name=None):
    """name 을 주면, blank_option 이 켜진 상품(소품: 색상·수량이 상품명에 들어감)은 선택사항을 빈칸으로."""
    if name is not None and _s(name).replace(" ", "") in {_s(x).replace(" ", "") for x in terms.get("passthrough_products") or []}:
        return option, None     # 추가상품: 선택사항('┗삼천리흙받이')도 그대로. 공장용에서 상품옵션으로 들어간다
    rule = find_rule(name, terms) if name is not None else None
    if rule and rule.get("blank_option"):
        return None, None
    text = _s(option)
    for rule in terms["options"]:
        if rule["keyword"] in text:
            return (rule["value"] or None), None
    # 선택사항에 조립 여부가 없어도 상품명에 '완전조립'이 있으면 완전조립으로 본다 (선택사항에 있는 조립 표기가 우선)
    # 미조립도 같다 (예: 상품명 '[미조립/박스] …'). 둘 다 있으면 완전조립 우선.
    if name is not None:
        plain_name = _s(name).replace(" ", "")
        for kw in ("완전조립", "미조립"):
            if kw in plain_name:
                for rule in terms["options"]:
                    if rule["keyword"] == kw:
                        return (rule["value"] or None), None
    return option, "변환 표에 없는 선택사항"


def make_extra(receiver, address, terms: dict) -> str:
    n = terms["insert_column"]["address_chars"]
    return f"{_s(receiver)}({_s(address).strip()[:n]})"
