"""중간파일(주문원본1 변환 결과) -> 공장 전달용 엑셀.

사용법:
    .venv/bin/python src/factory.py output/주문원본1_변환.xlsx
    .venv/bin/python src/factory.py output/주문원본1_변환.xlsx -o output/공장.xlsx

컬럼 매핑 (중간파일 -> 공장파일)
    받는고객   <- 수령자 다음의 헤더 없는 컬럼 (수령자(주소3자))
    우편번호   <- 우편번호 (5자리 미만이면 앞을 0으로 채움)
    받는고객주소 <- 주소 (앞뒤 공백 제거)
    전화번호   <- 수령자전화번호
    핸드폰번호 <- 수령자휴대전화
    수량       <- 수량
    택배운임   <- 규칙(config/factory.yaml shipping_rules)
    결제조건   <- 고정값 (선불)
    상품명     <- 상품명
    상품옵션   <- 선택사항 + ", " + 추가구성
    비고       <- 배송메모
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import naming  # noqa: E402
import xlsxkit as xk  # noqa: E402
from convert import KEY, active_rows, header_map  # noqa: E402

DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "factory.yaml"
REQUIRED = ["수령자", "우편번호", "주소", "수령자전화번호", "수령자휴대전화",
            "수량", "상품명", "선택사항", "추가구성", "배송메모", "택배사", KEY]


def local_path(path: Path = DEFAULT_CFG) -> Path:
    """실제 운임 등 커밋하지 않는 값을 두는 파일: factory.yaml 옆의 factory.local.yaml (.gitignore 대상)."""
    p = Path(path)
    return p.with_name(f"{p.stem}.local{p.suffix}")


def _merge(base, over):
    """딕셔너리는 항목별로 덮어쓰고, 그 밖(리스트 포함)은 통째로 교체한다."""
    if isinstance(base, dict) and isinstance(over, dict):
        return {**base, **{k: _merge(base.get(k), v) if k in base else v for k, v in over.items()}}
    return over


def load_cfg(path: Path = DEFAULT_CFG) -> dict:
    """factory.yaml 을 읽고, factory.local.yaml 이 있으면 그 값으로 덮어쓴다 (예: shipping_rules, default_fee, carriers.cj_fee).
    환경변수 FACTORY_IGNORE_LOCAL=1 이면 로컬 파일을 무시한다 (샘플값 기준 테스트용)."""
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    local = local_path(path)
    if local.exists() and not os.environ.get("FACTORY_IGNORE_LOCAL"):
        cfg = _merge(cfg, yaml.safe_load(local.read_text(encoding="utf-8")) or {})
    return cfg


def _s(v) -> str:
    return "" if v is None else str(v).strip()


def is_assembled(option, cfg: dict) -> bool:
    return cfg["assembled_marker"] in _s(option)


def shipping_fee_info(product, option, cfg: dict) -> tuple[int, bool]:
    """(운임, 규칙 일치 여부). 일치하는 규칙이 없으면 (default_fee, False)."""
    assembled = is_assembled(option, cfg)
    for rule in cfg["shipping_rules"]:
        if "assembled" in rule and rule["assembled"] != assembled:
            continue
        if "product_contains" in rule and rule["product_contains"] not in _s(product):
            continue
        return rule["fee"], True
    return cfg["default_fee"], False


def shipping_fee(product, option, cfg: dict) -> int:
    return shipping_fee_info(product, option, cfg)[0]


def fee_warnings(ws, h: dict, rows: list[int], cfg: dict) -> list[str]:
    """운임표에 없는 상품(기본값 적용) 목록 - 상품명만 반환(개인정보 없음)."""
    out = set()
    for r in rows:
        name, opt = ws.cell(r, h["상품명"]).value, ws.cell(r, h["선택사항"]).value
        if not shipping_fee_info(name, opt, cfg)[1]:
            out.add(_s(name))
    return sorted(out)


def product_option(option, extra, cfg: dict) -> str | None:
    """선택사항 + 추가구성. 추가구성에 쉼표로 구분된 여러 단어가 있으면 각각 ', '로 이어 붙인다."""
    extras = [w.strip() for w in re.split(r"[,，]", _s(extra)) if w.strip()]
    parts = [p for p in (_s(option), *extras) if p]
    return cfg["option_joiner"].join(parts) or None


def zip_text(v) -> str | None:
    if v in (None, ""):
        return None
    if isinstance(v, (int, float)):
        return str(int(v)).zfill(5)
    return _s(v)


def qty(v):
    return int(v) if isinstance(v, (int, float)) and float(v).is_integer() else v


def carrier_kind(value, cfg: dict) -> str | None:
    """택배사 값 -> 'kd'(경동) / 'cj' / None(모르는 값). 대소문자·앞뒤 공백 무시."""
    v = _s(value).casefold()
    car = cfg["carriers"]
    if v in {x.casefold() for x in car["cj"]}:
        return "cj"
    if v in {x.casefold() for x in car["kyungdong"]}:
        return "kd"
    return None


def split_rows(ws, h: dict, rows: list[int], cfg: dict) -> tuple[list[int], list[int], list[str]]:
    """(경동 행들, CJ 행들, 모르는 택배사 값들). 모르는 값은 경동 쪽에 두고 경고한다."""
    kd, cj, unknown = [], [], set()
    for r in rows:
        kind = carrier_kind(ws.cell(r, h["택배사"]).value, cfg)
        if kind == "cj":
            cj.append(r)
        else:
            kd.append(r)
            if kind is None:
                unknown.add(_s(ws.cell(r, h["택배사"]).value) or "(빈칸)")
    return kd, cj, sorted(unknown)


def cj_path(dst: Path, cfg: dict) -> Path:
    return dst.with_name(naming.cj_stem(dst.stem, cfg["carriers"]["cj_suffix"]) + dst.suffix)


def build_row(ws, r: int, h: dict[str, int], extra_col: int, cfg: dict, fee: int | None = None) -> list:
    g = lambda name: ws.cell(r, h[name]).value  # noqa: E731
    return [
        ws.cell(r, extra_col).value,                 # 받는고객
        zip_text(g("우편번호")),                      # 우편번호
        _s(g("주소")) or None,                        # 받는고객주소
        g("수령자전화번호"),                          # 전화번호
        g("수령자휴대전화"),                          # 핸드폰번호
        qty(g("수량")),                               # 수량
        fee if fee is not None else shipping_fee(g("상품명"), g("선택사항"), cfg),  # 택배운임(CJ는 고정값)
        cfg["payment_term"],                          # 결제조건
        g("상품명"),                                  # 상품명
        product_option(g("선택사항"), g("추가구성"), cfg),  # 상품옵션
        g("배송메모"),                                # 비고
    ]


def locate(ws) -> tuple[dict[str, int], int]:
    h = header_map(ws)
    miss = [n for n in REQUIRED if n not in h]
    if miss:
        raise SystemExit(f"중간파일에 필수 컬럼 없음: {', '.join(miss)}")
    extra_col = h["수령자"] + 1
    if ws.cell(1, extra_col).value not in (None, ""):
        raise SystemExit("수령자 다음 컬럼이 헤더 없는 컬럼(수령자(주소3자))이 아닙니다. 중간파일이 맞는지 확인하세요.")
    return h, extra_col


def write_file(ws, h: dict, extra_col: int, src_rows: list[int], cfg: dict, dst: Path, cj: bool = False) -> None:
    fee = cfg["carriers"]["cj_fee"] if cj else None
    heads = cfg["headers"]
    wb, o = xk.open_template(cfg["template"], heads)
    fee_col = heads.index("택배운임") + 1
    text_cols = {heads.index(n) + 1 for n in ("우편번호", "전화번호", "핸드폰번호")}
    for i, r in enumerate(src_rows, start=2):
        for c, v in enumerate(build_row(ws, r, h, extra_col, cfg, fee), start=1):
            o.cell(i, c).value = v
        xk.style_data(o, i, len(heads), text_cols)
        if not cj and not shipping_fee_info(ws.cell(r, h["상품명"]).value, ws.cell(r, h["선택사항"]).value, cfg)[1]:
            xk.mark_warning(o.cell(i, fee_col), cfg["warning"])
    xk.normalize_cf(o)
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)


def build(src: Path, dst: Path, cfg: dict) -> dict:
    """경동 주문은 dst, CJ 주문이 있으면 별도 CJ 파일로 만든다."""
    ws = load_workbook(src).active
    h, extra_col = locate(ws)
    all_rows = active_rows(ws, h)
    kd, cj, unknown = split_rows(ws, h, all_rows, cfg)

    write_file(ws, h, extra_col, kd, cfg, dst)
    cjp = cj_path(dst, cfg)
    if cj:
        write_file(ws, h, extra_col, cj, cfg, cjp, cj=True)
    return {"kd": len(kd), "cj": len(cj), "cj_path": cjp, "unknown": unknown,
            "stale_cj": (not cj) and cjp.exists(),
            "unmatched": fee_warnings(ws, h, kd, cfg)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일(주문원본1 변환 결과)")
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CFG)
    a = p.parse_args()
    if not a.src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1
    out_root = Path("output")
    dst = a.output or out_root / naming.factory_name(out_root)
    if dst.resolve() == a.src.resolve():
        print("출력 경로가 입력과 같습니다.", file=sys.stderr)
        return 1
    r = build(a.src, dst, load_cfg(a.config))
    print(f"공장용 파일 생성: {dst} (경동 {r['kd']}행)")
    if r["cj"]:
        print(f"CJ용 공장 파일 생성: {r['cj_path']} (CJ {r['cj']}행, 택배운임 고정)")
    warn = False
    for name in r["unmatched"]:
        warn = True
        print(f"  경고: 운임표에 없는 상품 '{name}' - 기본운임 적용됨. config/factory.yaml shipping_rules 에 추가 필요")
    for v in r["unknown"]:
        warn = True
        print(f"  경고: 알 수 없는 택배사 '{v}' - 경동 주문으로 처리됨. config/factory.yaml carriers 에 추가 필요")
    if r["stale_cj"]:
        warn = True
        print(f"  경고: 이번에는 CJ 주문이 없는데 이전 CJ 파일이 남아 있습니다 ({r['cj_path']}). 공장에 보내지 않도록 확인/삭제하세요")
    return 2 if warn else 0

if __name__ == "__main__":
    sys.exit(main())
