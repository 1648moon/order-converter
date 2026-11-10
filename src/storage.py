"""중간파일(주문원본1 변환 결과) -> 내부보관용 엑셀 (왼쪽 주문표 + 오른쪽 상품별 집계표).

사용법:
    .venv/bin/python src/storage.py output/주문원본1_변환.xlsx
    .venv/bin/python src/storage.py output/주문원본1_변환.xlsx -o output/내부보관.xlsx

종료코드: 0 정상 / 2 경고(집계표 목록에 없는 상품 있음) / 1 오류
"""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date, datetime
from pathlib import Path

import yaml
from openpyxl import Workbook, load_workbook
from openpyxl.formatting.rule import CellIsRule, Rule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import naming  # noqa: E402
import factory as F  # noqa: E402
from convert import KEY, data_rows  # noqa: E402

DEFAULT_CFG = Path(__file__).resolve().parent.parent / "config" / "storage.yaml"
KNOWN = ["접수일자", "송장번호", "상품명", "수화주명", "주문량", "상품옵션",
         "우편번호", "수화주주소", "수화주전화", "수화주휴대폰"]
SIDE_GAP = 1   # 왼쪽 표와 집계표 사이 빈 열 수


def load_cfg(path: Path = DEFAULT_CFG) -> dict:
    cfg = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    bad = [h for h in cfg["headers"] if h not in KNOWN]
    if bad:
        raise SystemExit(f"storage.yaml headers에 지원하지 않는 항목: {bad}")
    return cfg


def parse_date(v) -> date | None:
    """yy.mm.dd / yyyymmdd / yyyy-mm-dd[ hh:mm:ss] / datetime -> date"""
    if v in (None, ""):
        return None
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if isinstance(v, float) and v.is_integer():
        v = int(v)
    s = str(v).strip()
    m = (re.fullmatch(r"(\d{2})\.(\d{1,2})\.(\d{1,2})", s)
         or re.fullmatch(r"(\d{4})[-./](\d{1,2})[-./](\d{1,2})(?:\s.*)?", s)
         or re.fullmatch(r"(\d{4})(\d{2})(\d{2})", s))
    if not m:
        return None
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    y += 2000 if y < 100 else 0
    try:
        return date(y, mo, d)
    except ValueError:
        return None


def order_date(ws, r: int, h: dict, sources: list[str]) -> date | None:
    for name in sources:
        if name in h:
            d = parse_date(ws.cell(r, h[name]).value)
            if d:
                return d
    return None


def build_row(ws, r: int, h: dict, extra_col: int, cfg: dict, fcfg: dict) -> dict:
    g = lambda name: ws.cell(r, h[name]).value  # noqa: E731
    opt = g("선택사항")
    all_vals = {
        "접수일자": order_date(ws, r, h, cfg["date_sources"]),
        "송장번호": None,
        "상품명": g("상품명"),
        "수화주명": ws.cell(r, extra_col).value,
        "주문량": F.qty(g("수량")),
        "상품옵션": fcfg["assembled_marker"] if F.is_assembled(opt, fcfg) else None,
        "우편번호": F.zip_text(g("우편번호")),
        "수화주주소": F._s(g("주소")) or None,
        "수화주전화": g("수령자전화번호"),
        "수화주휴대폰": g("수령자휴대전화"),
    }
    return {k: all_vals[k] for k in cfg["headers"]}


def side_layout(cfg: dict) -> dict:
    """집계표 위치/수식 (생성과 검증이 공유)."""
    heads = cfg["headers"]
    start = len(heads) + SIDE_GAP + 1
    name_col = get_column_letter(heads.index("상품명") + 1)
    opt_col = get_column_letter(heads.index("상품옵션") + 1)
    n = len(cfg["product_list"])
    lab, cnt = get_column_letter(start), get_column_letter(start + 1)
    return {
        "label_col": start, "count_col": start + 1, "marker_label_col": start + 2,
        "marker_count_col": start + 3, "last_row": n + 1,
        "sum": f"=SUM({cnt}2:{cnt}{n + 1})",
        "row": lambda i: f'=COUNTIF({name_col}:{name_col},{lab}{i}&"*")',
        "marker": f'=COUNTIF({opt_col}:{opt_col},"*"&{get_column_letter(start + 2)}1&"*")',
    }


def check_columns(ws) -> tuple[dict, int]:
    h, extra_col = F.locate(ws)
    return h, extra_col


def apply_style(o, cfg: dict, n_rows: int) -> None:
    """input/내부보관용.xlsx 예시 서식 적용 (설정은 config/storage.yaml style)."""
    st = cfg["style"]
    heads = cfg["headers"]
    s = side_layout(cfg)
    n_prod = len(cfg["product_list"])
    last = max(n_rows, n_prod) + 1

    def font(bold=False):
        return Font(name=st["font"], size=st["font_size"], bold=bold)

    thin = Side(style="thin")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    center = Alignment(vertical="center")

    # 행 높이
    o.row_dimensions[1].height = st["header_height"]
    for r in range(2, last + 1):
        o.row_dimensions[r].height = st["row_height"]

    # 왼쪽 표: 글꼴·세로 가운데·표시형식
    for c, name in enumerate(heads, start=1):
        o.column_dimensions[get_column_letter(c)].width = st["column_widths"][name]
        for r in range(1, n_rows + 2):
            cell = o.cell(r, c)
            cell.font = font()
            cell.alignment = center
            if r == 1:
                continue
            if name == "접수일자":
                cell.number_format = cfg["date_format"]
            elif name == "송장번호":
                cell.number_format = st["invoice_format"]
                cell.alignment = Alignment(horizontal="left", vertical="center")
            elif name in ("우편번호", "수화주전화", "수화주휴대폰"):
                cell.number_format = "@"
    for name in st.get("hidden_columns", []):
        if name in heads:
            o.column_dimensions[get_column_letter(heads.index(name) + 1)].hidden = True
    if st.get("autofilter"):
        o.auto_filter.ref = f"A1:{get_column_letter(len(heads))}1"

    # 오른쪽 집계표: 테두리, 굵은 글씨(총합 행), 그룹별 배경색
    gap = get_column_letter(len(heads) + SIDE_GAP)
    o.column_dimensions[gap].width = st["gap_width"]
    for col, w in zip(("label_col", "count_col", "marker_label_col", "marker_count_col"), st["side_widths"]):
        o.column_dimensions[get_column_letter(s[col])].width = w
    for r in range(1, n_prod + 2):
        for col in ("label_col", "count_col"):
            cell = o.cell(r, s[col])
            cell.font = font(bold=(r == 1))
            cell.border = box
            cell.alignment = center
            name = o.cell(r, s["label_col"]).value
            fill = st["side_fills"].get(name) if r > 1 else None
            if fill:
                cell.fill = PatternFill("solid", fgColor=fill)
    for col, bold in (("marker_label_col", False), ("marker_count_col", True)):
        cell = o.cell(1, s[col])
        cell.font = font(bold=bold)
        cell.border = box
        cell.alignment = center

    # 조건부 서식: 주문량 초과 / 조립 옵션 강조
    hl = st["highlight"]
    dxf = DifferentialStyle(font=Font(color=hl["font"]),
                            fill=PatternFill(bgColor=hl["fill"], fgColor=hl["fill"], fill_type="solid"))
    if "주문량" in heads:
        col = get_column_letter(heads.index("주문량") + 1)
        o.conditional_formatting.add(
            f"{col}2:{col}1000",
            CellIsRule(operator="greaterThan", formula=[str(st["highlight_qty_over"])],
                       font=Font(color=hl["font"]),
                       fill=PatternFill(bgColor=hl["fill"], fgColor=hl["fill"], fill_type="solid")))
    if "상품옵션" in heads:
        col = get_column_letter(heads.index("상품옵션") + 1)
        word = st["highlight_option_contains"]
        o.conditional_formatting.add(
            f"{col}2:{col}1000",
            Rule(type="containsText", operator="containsText", text=word, dxf=dxf,
                 formula=[f'NOT(ISERROR(SEARCH("{word}",{col}2)))']))
    o.freeze_panes = "A2"


def build(src: Path, dst: Path, cfg: dict) -> tuple[int, list[str]]:
    fcfg = F.load_cfg()
    ws = load_workbook(src).active
    h, extra_col = check_columns(ws)
    rows = []
    for r in data_rows(ws, h[KEY]):
        row = build_row(ws, r, h, extra_col, cfg, fcfg)
        if "접수일자" in row and row["접수일자"] is None:
            raise SystemExit(f"{r}행: 접수일자를 읽을 수 없습니다 ({', '.join(cfg['date_sources'])})")
        rows.append(row)

    out = Workbook()
    o = out.active
    o.title = "내부보관"
    o.append(cfg["headers"])
    for row in rows:
        o.append([row[k] for k in cfg["headers"]])
    s = side_layout(cfg)
    o.cell(1, s["label_col"]).value = "총합"
    o.cell(1, s["count_col"]).value = s["sum"]
    o.cell(1, s["marker_label_col"]).value = fcfg["assembled_marker"]
    o.cell(1, s["marker_count_col"]).value = s["marker"]
    for i, name in enumerate(cfg["product_list"], start=2):
        o.cell(i, s["label_col"]).value = name
        o.cell(i, s["count_col"]).value = s["row"](i)
    apply_style(o, cfg, len(rows))

    listed = cfg["product_list"]
    unlisted = sorted({str(r["상품명"]) for r in rows
                       if not any(str(r["상품명"]).startswith(p) for p in listed)}) if "상품명" in cfg["headers"] else []
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.save(dst)
    return len(rows), unlisted


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일(주문원본1 변환 결과)")
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--config", type=Path, default=DEFAULT_CFG)
    a = p.parse_args()
    if not a.src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1
    dst = a.output or Path("output") / naming.storage_name()
    if dst.resolve() == a.src.resolve():
        print("출력 경로가 입력과 같습니다.", file=sys.stderr)
        return 1
    n, unlisted = build(a.src, dst, load_cfg(a.config))
    print(f"내부보관용 파일 생성: {dst} ({n}행)")
    for name in unlisted:
        print(f"  경고: 집계표 목록에 없는 상품 '{name}' - config/storage.yaml product_list 에 추가 필요")
    return 2 if unlisted else 0


if __name__ == "__main__":
    sys.exit(main())
