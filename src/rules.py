"""변환 규칙 (convert.py, validate.py 공용). 규칙 데이터는 config/terms.yaml."""
from __future__ import annotations

import os
import re
from pathlib import Path

import yaml

DEFAULT_TERMS = Path(__file__).resolve().parent.parent / "config" / "terms.yaml"


def rules_dir() -> Path:
    """사람이 승인해 늘어나는 규칙(상품명 매핑, 에이전트가 추가한 운임)을 두는 폴더.
    서버(Docker)에서는 ORDER_RULES_DIR=/state/rules 처럼 재시작·재빌드에도 남는 볼륨을 가리킨다.
    환경변수가 없으면 예전처럼 config/ 폴더."""
    env = os.environ.get("ORDER_RULES_DIR")
    return Path(env) if env else DEFAULT_TERMS.parent


DEFAULT_MAP = rules_dir() / "product_map.yaml"
AGENT_FEE_NAME = "factory.agent.yaml"


def agent_fee_path() -> Path:
    return rules_dir() / AGENT_FEE_NAME


def load_agent_fee_rules(path: Path | None = None) -> list[dict]:
    """에이전트가 사람의 승인을 받아 추가한 미조립 운임 규칙: [{assembled, product_contains, fee}, ...]."""
    p = Path(path) if path else agent_fee_path()
    if not p.exists():
        return []
    data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    return [dict(r) for r in (data.get("shipping_rules_extra") or [])
            if isinstance(r, dict) and r.get("product_contains") and isinstance(r.get("fee"), int)]
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


def _second_color(text: str, end: int, terms: dict) -> str:
    """'색상:블랙/레드' 처럼 색상 뒤에 '/다른색' 이 붙으면 '레드' 를 돌려줘 '블랙레드' 로 합친다.
    '/2개', '/완전조립' 처럼 색상 목록(terms.yaml color_words)에 없는 값은 합치지 않는다."""
    words = terms.get("color_words") or []
    # 색상 패턴이 구분자('/')까지 소비했을 수 있어 직전 문자도 확인한다
    for pos in (end - 1, end):
        if 0 <= pos < len(text) and text[pos] == "/":
            m = re.match(r"\s*([가-힣]+)\s*(?:[,/(]|-?\d|$)", text[pos + 1:])
            if m and m.group(1) in words:
                return m.group(1)
    return ""


def _color_in_name(text: str, terms: dict) -> str:
    """상품명 안의 색상 단어(terms.yaml color_words). 서로 다른 색상이 정확히 하나일 때만 돌려준다.
    둘 이상 적혀 있으면('블랙/화이트 중 택1' 같은 색상 목록) 추측하지 않고 빈 문자열.
    긴 단어 우선('스카이블루' 안의 '블루' 는 따로 세지 않는다)."""
    found, rest = [], text
    for w in sorted(terms.get("color_words") or [], key=len, reverse=True):
        if w in rest:
            found.append(w)
            rest = rest.replace(w, " ")
    return found[0] if len(found) == 1 else ""


def extract_color(option, terms: dict) -> str | None:
    text = _s(option)
    for pat in terms["color_patterns"]:
        m = re.search(pat, text)
        if m:
            color = re.sub(r"\(.*?\)", "", m.group(1))          # 라이트핑크(무광) -> 라이트핑크
            color = re.sub(r"[-\s]*\d+\s*개$", "", color)       # 블루-1개 -> 블루
            if color.strip():
                return color.strip() + _second_color(text, m.end(), terms)
            # 비었으면(예: '미조립 1개' 에서 '1개' 만 잡힘) 다음 패턴을 계속 시도한다
    # 선택사항이 색상 단어만 적힌 경우: '블랙', '블랙/레드' (color_words 에 있는 단어만 인정)
    words = terms.get("color_words") or []
    parts = [w.strip() for w in re.sub(r"\(.*?\)", "", text).split("/")]
    if parts and 1 <= len(parts) <= 2 and all(w in words for w in parts):
        return "".join(parts)
    return None


def _known_colors(terms: dict) -> set[str]:
    """색상 단어 집합: terms.yaml color_words + 내부보관용 목록(product_list)의 '/색상' 부분."""
    known = set(terms.get("color_words") or [])
    for b in terms.get("_bikes") or []:
        m = re.search(r"/([가-힣]+)", b)      # '시애틀키즈18/라이트블루' -> 라이트블루 ('엑스퍼트/380블랙화이트' 처럼 숫자 낀 건 제외)
        if m and not re.match(r"/\d", b[b.find("/"):]):
            known.add(m.group(1))
    return known


def color_from_name(name, terms: dict) -> str:
    """선택사항에 색상이 없을 때 상품명에서 찾는다. '빅마운틴/블랙(2025)', '시애틀MT24/레드' 의 '/블랙' 처럼
    '/' 뒤에 알려진 색상 단어가 오거나, '다크실버/미조립' 처럼 조립 표기 앞에 색상이 있는 경우."""
    text = _s(name)
    known = _known_colors(terms)
    for pat in (r"/\s*([가-힣]+)", r"([가-힣]+)\s*/\s*(?:완전조립|미조립)"):
        for m in re.finditer(pat, text):
            if m.group(1) in known:
                return m.group(1) + _second_color(text, m.end(), terms)
    return ""


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
            values["color"] = extract_color(option, terms) or color_from_name(text, terms)   # 선택사항 우선, 없으면 상품명
            values["count"] = count_suffix(option)
            if not values["color"]:
                values["color"] = _color_in_name(text, terms)   # 선택사항에 색상이 없으면 상품명에서 (모든 상품)
            if not values["count"] and rule.get("color_from_name"):
                values["count"] = count_suffix(text)            # 수량도 상품명에서: 이 플래그가 켜진 규칙만
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
                    if plain in {b.replace(" ", "") for b in terms.get("_bikes") or []}:
                        return name, None     # 이미 내부보관용 목록과 같은 축약명(예: '시애틀키즈18/라이트블루')이면 그대로
                    return name, f"상품명에서 '{var}' 값을 찾지 못함"
            if skip:
                continue
            return render(rule["template"], **values), None
    hit = (terms.get("_map") or {}).get(plain)
    if hit:
        value = render(hit["template"], color=extract_color(option, terms) or color_from_name(name, terms), count=count_suffix(option))
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
    # 선택사항에 조립 여부가 없어도 상품명에 '완전조립'/'미조립'이 있으면 그것으로 본다 (선택사항에 있는 조립 표기가 우선)
    if name is not None:
        plain = _s(name).replace(" ", "")
        for rule in terms["options"]:
            if rule["keyword"] in plain:
                return (rule["value"] or None), None
    return option, "변환 표에 없는 선택사항"


def unit_price(v) -> float | None:
    """'단가' 셀 값 -> 숫자. 숫자가 아니거나 비었으면 None ('12,000원' 같은 문자열도 허용)."""
    if isinstance(v, bool) or v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r"[,\s원]", "", str(v))
    try:
        return float(t)
    except ValueError:
        return None


def is_part(price, terms: dict) -> bool:
    """단가가 parts_rule.max_unit_price 이하면 부품. 단가를 읽을 수 없으면 부품으로 보지 않는다."""
    rule = terms.get("parts_rule") or {}
    p = unit_price(price)
    return bool(rule) and p is not None and p <= rule["max_unit_price"]


def is_part_name(name, terms: dict) -> bool:
    """상품명에 parts_rule.carrier_by_name 의 단어(예: '보호대')가 있으면 단가와 무관하게 부품."""
    words = (terms.get("parts_rule") or {}).get("carrier_by_name") or []
    plain = _s(name).replace(" ", "")
    return any(w.replace(" ", "") in plain for w in words)


def expected_carrier(carrier, price, terms: dict, name=None):
    """부품(단가 기준 또는 상품명 기준)이면 parts_rule.carrier, 아니면 원래 택배사 값 그대로."""
    if is_part(price, terms) or is_part_name(name, terms):
        return terms["parts_rule"]["carrier"]
    return carrier


def make_extra(receiver, address, terms: dict) -> str:
    n = terms["insert_column"]["address_chars"]
    return f"{_s(receiver)}({_s(address).strip()[:n]})"
