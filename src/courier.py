"""중간파일(주문원본1 변환 결과) -> 택배 접수용 엑셀.

사용법:
    .venv/bin/python src/courier.py output/주문원본1_변환.xlsx
    .venv/bin/python src/courier.py output/주문원본1_변환.xlsx -o output/택배.xlsx

종료코드: 0 정상 / 2 경고(수량이 1이 아닌 주문 있음 - 택배 수량은 1로 고정되므로 확인 필요)
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import naming  # noqa: E402
import factory as F  # noqa: E402
import xlsxkit as xk  # noqa: E402
from convert import KEY, data_rows  # noqa: E402

DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "courier.yaml"
TEXT_COLS = ("우편번호", "전화번호", "기타전화번호")  # 문자열 유지(앞자리 0, 긴 숫자)


def load_cfg(path: Path = DEFAULT_CFG) -> dict:
    return yaml.safe_load(Path(path).read_text(encoding="utf-8"))


_FACTORY = None


def factory_cfg() -> dict:
    global _FACTORY
    if _FACTORY is None:
        _FACTORY = F.load_cfg()
    return _FACTORY


def text(v):
    """숫자로 저장된 값(주문번호 등)은 지수표기 없이 문자열로."""
    if v in (None, ""):
        return None
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    return str(v).strip() or None


def phone(ws, r: int, h: dict, cfg: dict):
    for name in cfg["phone_sources"]:
        v = text(ws.cell(r, h[name]).value)
        if v:
            return v
    return None


def build_row(ws, r: int, h: dict, extra_col: int, cfg: dict) -> dict:
    row = {name: None for name in cfg["headers"]}
    row["받는분"] = ws.cell(r, extra_col).value
    for out_name, src_name in cfg["copy"].items():
        v = ws.cell(r, h[src_name]).value
        row[out_name] = F.zip_text(v) if out_name == "우편번호" else (
            text(v) if out_name in TEXT_COLS else (F._s(v) or None))
    ph = phone(ws, r, h, cfg)
    row["전화번호"] = row["기타전화번호"] = ph
    row.update(cfg["fixed"])
    row["배송운임"] = F.shipping_fee(ws.cell(r, h["상품명"]).value, ws.cell(r, h["선택사항"]).value, factory_cfg())
    return row


def need_columns(cfg: dict) -> list[str]:
    return ["수령자", "수량", "상품명", "선택사항", *cfg["copy"].values(), *cfg["phone_sources"]]


def build(src: Path, dst: Path, cfg: dict) -> tuple[int, int, list[str]]:
    ws = load_workbook(src).active
    h, extra_col = F.locate(ws)
    miss = [n for n in need_columns(cfg) if n not in h]
    if miss:
        raise SystemExit(f"중간파일에 필수 컬럼 없음: {', '.join(miss)}")
    fcfg = factory_cfg()
    src_rows = data_rows(ws, h[KEY])
    rows = [build_row(ws, r, h, extra_col, cfg) for r in src_rows]
    matched = [F.shipping_fee_info(ws.cell(r, h["상품명"]).value, ws.cell(r, h["선택사항"]).value, fcfg)[1]
               for r in src_rows]
    unmatched = F.fee_warnings(ws, h, src_rows, fcfg)
    not_one = sum(1 for r in src_rows if F.qty(ws.cell(r, h["수량"]).value) != 1)

    heads = cfg["headers"]
    wb, o = xk.open_template(cfg["template"], heads)
    fee_col = heads.index("배송운임") + 1
    text_cols = {heads.index(n) + 1 for n in TEXT_COLS if n in heads}
    for i, (row, ok) in enumerate(zip(rows, matched), start=2):
        for c, name in enumerate(heads, start=1):
            o.cell(i, c).value = row[name]
        xk.style_data(o, i, len(heads), text_cols)
        if not ok:
            xk.mark_warning(o.cell(i, fee_col), fcfg["warning"])
    xk.normalize_cf(o)
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return len(rows), not_one, unmatched


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일(주문원본1 변환 결과)")
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CFG)
    a = p.parse_args()
    if not a.src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1
    dst = a.output or Path("output") / naming.courier_name()
    if dst.resolve() == a.src.resolve():
        print("출력 경로가 입력과 같습니다.", file=sys.stderr)
        return 1
    n, not_one, unmatched = build(a.src, dst, load_cfg(a.config))
    print(f"택배용 파일 생성: {dst} ({n}행)")
    if not_one:
        print(f"  경고: 수량이 1이 아닌 주문 {not_one}건 - 택배 수량은 1로 고정됩니다. 확인 필요")
    for name in unmatched:
        print(f"  경고: 운임표에 없는 상품 '{name}' - 기본운임 적용됨. config/factory.yaml shipping_rules 에 추가 필요")
    return 2 if (not_one or unmatched) else 0


if __name__ == "__main__":
    sys.exit(main())
