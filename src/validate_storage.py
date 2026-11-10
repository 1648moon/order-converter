"""중간파일과 내부보관용 파일의 공통 정보 동일성 검증.

사용법:
    .venv/bin/python src/validate_storage.py output/주문원본1_변환.xlsx output/주문원본1_내부보관.xlsx

검증 항목
  1. 헤더가 설정(config/storage.yaml)과 같은지, 행 수
  2. 접수일자: 실제 날짜 값 + 표시형식 YYYY-MM-DD, 그리고 중간파일의 '다른' 날짜 컬럼(주문일자 yyyyMMdd)과 같은 날짜
  3. 송장번호는 공란, 상품명/수화주명/주문량은 중간파일과 동일, 상품옵션은 조립 여부와 일치
  4. 오른쪽 집계표: 상품 목록·수식(COUNTIF/SUM) 일치, 그리고 파이썬으로 센 상품별 수량 합계 == 주문 행 수
     (엑셀 수식은 파일을 열어야 계산되므로, 합계가 맞는지는 파이썬 집계로 확인한다)
  5. 서식: 열 너비·행 높이·필터·집계표 테두리/배경색·조건부 서식이 예시 문서 서식대로 적용됐는지
상세(값 포함)는 reports/ CSV에만 기록하고 화면에는 건수·위치만 출력한다.
종료코드: 0 통과 / 1 불일치
"""
from __future__ import annotations

import argparse
import sys
from datetime import date, datetime
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory as F  # noqa: E402
import storage as S  # noqa: E402
from convert import KEY, data_rows  # noqa: E402
from validate import norm, write_report  # noqa: E402


def validate(src: Path, out: Path, cfg: dict) -> tuple[list[tuple], int]:
    fcfg = F.load_cfg()
    a = load_workbook(src).active
    b = load_workbook(out).active
    h, extra_col = S.check_columns(a)
    diffs: list[tuple] = []

    heads = [b.cell(1, c).value for c in range(1, len(cfg["headers"]) + 1)]
    if heads != cfg["headers"]:
        diffs.append(("헤더", 1, "", cfg["headers"], heads))
        return diffs, 0
    hb = {name: i + 1 for i, name in enumerate(heads)}

    ra = data_rows(a, h[KEY])
    rb = [r for r in range(2, b.max_row + 1)
          if any(b.cell(r, c).value not in (None, "") for c in range(1, len(heads) + 1))]
    if len(ra) != len(rb):
        diffs.append(("행수", "", "", len(ra), len(rb)))
        return diffs, len(ra)

    check_src = cfg.get("date_check_source")
    for r1, r2 in zip(ra, rb):
        exp = S.build_row(a, r1, h, extra_col, cfg, fcfg)
        for name in cfg["headers"]:
            got = b.cell(r2, hb[name]).value
            e = exp[name]
            if name == "접수일자":
                cell = b.cell(r2, hb[name])
                if isinstance(got, datetime):
                    got = got.date()
                if not isinstance(got, date):
                    diffs.append(("접수일자 형식", r2, name, "날짜 값", type(got).__name__))
                    continue
                if "yyyy-mm-dd" not in cell.number_format.lower():
                    diffs.append(("접수일자 형식", r2, name, cfg["date_format"], cell.number_format))
                if check_src in h:   # 다른 컬럼 날짜와 교차 확인
                    e = S.parse_date(a.cell(r1, h[check_src]).value)
            elif name in ("우편번호", "수화주전화", "수화주휴대폰"):
                got = F.zip_text(got) if name == "우편번호" else got
            if norm(e) != norm(got):
                diffs.append(("불일치", r2, name, e, got))

    # 오른쪽 집계표
    s = S.side_layout(cfg)
    n = len(cfg["product_list"])
    if b.cell(1, s["label_col"]).value != "총합":
        diffs.append(("집계표", 1, "총합", "총합", b.cell(1, s["label_col"]).value))
    if b.cell(1, s["count_col"]).value != s["sum"]:
        diffs.append(("집계표", 1, "합계 수식", s["sum"], b.cell(1, s["count_col"]).value))
    if b.cell(1, s["marker_label_col"]).value != fcfg["assembled_marker"]:
        diffs.append(("집계표", 1, "조립 라벨", fcfg["assembled_marker"], b.cell(1, s["marker_label_col"]).value))
    if b.cell(1, s["marker_count_col"]).value != s["marker"]:
        diffs.append(("집계표", 1, "조립 수식", s["marker"], b.cell(1, s["marker_count_col"]).value))
    for i, name in enumerate(cfg["product_list"], start=2):
        if b.cell(i, s["label_col"]).value != name:
            diffs.append(("집계표", i, "상품명", name, b.cell(i, s["label_col"]).value))
        if b.cell(i, s["count_col"]).value != s["row"](i):
            diffs.append(("집계표", i, "수식", s["row"](i), b.cell(i, s["count_col"]).value))
    if b.max_row > max(n + 1, len(rb) + 1) and any(
            b.cell(r, s["label_col"]).value for r in range(n + 2, b.max_row + 1)):
        diffs.append(("집계표", "", "목록 길이", n, "목록 밖에 값 있음"))

    # 엑셀 수식과 같은 방식(앞부분 일치)으로 파이썬이 세어 본 합계 == 주문 행 수
    if "상품명" in hb:
        names = [str(b.cell(r, hb["상품명"]).value) for r in rb]
        counted = sum(sum(1 for nm in names if nm.startswith(p)) for p in cfg["product_list"])
        if counted != len(names):
            diffs.append(("집계 합계", "", "상품별 합계", len(names), counted))
    if "상품옵션" in hb:
        marker = fcfg["assembled_marker"]
        n_opt = sum(1 for r in rb if marker in str(b.cell(r, hb["상품옵션"]).value or ""))
        n_src = sum(1 for r in ra if F.is_assembled(a.cell(r, h["선택사항"]).value, fcfg))
        if n_opt != n_src:
            diffs.append(("집계 합계", "", marker, n_src, n_opt))
    diffs += check_format(b, cfg)
    return diffs, len(ra)


def check_format(b, cfg: dict) -> list[tuple]:
    """예시 문서 서식(config/storage.yaml style)이 적용됐는지 확인."""
    st = cfg["style"]
    heads = cfg["headers"]
    s = S.side_layout(cfg)
    d: list[tuple] = []

    def widths():
        out = {}
        for v in b.column_dimensions.values():
            for c in range(v.min or 1, (v.max or v.min or 1) + 1):
                out[c] = round(v.width or 0, 2)
        return out

    w = widths()
    for c, name in enumerate(heads, start=1):
        if abs(w.get(c, 0) - st["column_widths"][name]) > 0.01:
            d.append(("서식", 1, f"열너비:{name}", st["column_widths"][name], w.get(c)))
    for col, exp in zip(("label_col", "count_col", "marker_label_col", "marker_count_col"), st["side_widths"]):
        if abs(w.get(s[col], 0) - exp) > 0.01:
            d.append(("서식", 1, f"집계표 열너비 {s[col]}", exp, w.get(s[col])))
    hidden = set(st.get("hidden_columns", []))
    for c, name in enumerate(heads, start=1):
        dim = b.column_dimensions.get(get_column_letter(c))
        is_hidden = bool(dim and dim.hidden)
        if is_hidden != (name in hidden):
            d.append(("서식", 1, f"숨김:{name}", name in hidden, is_hidden))
    if b.row_dimensions[1].height != st["header_height"]:
        d.append(("서식", 1, "헤더 행높이", st["header_height"], b.row_dimensions[1].height))
    if b.row_dimensions[2].height != st["row_height"]:
        d.append(("서식", 2, "데이터 행높이", st["row_height"], b.row_dimensions[2].height))
    if st.get("autofilter") and b.auto_filter.ref != f"A1:{get_column_letter(len(heads))}1":
        d.append(("서식", 1, "필터", "헤더 필터", b.auto_filter.ref))
    for r in (1, 2, len(cfg["product_list"]) + 1):
        for col in ("label_col", "count_col"):
            cell = b.cell(r, s[col])
            if cell.border.left.style != "thin" or cell.font.name != st["font"]:
                d.append(("서식", r, f"집계표 테두리/글꼴 {cell.coordinate}", "thin/" + st["font"], cell.border.left.style))
    for name, fill in st["side_fills"].items():
        for i, p in enumerate(cfg["product_list"], start=2):
            if p == name and b.cell(i, s["label_col"]).fill.fgColor.rgb != fill:
                d.append(("서식", i, "집계표 배경색", fill, b.cell(i, s["label_col"]).fill.fgColor.rgb))
    cf = {str(k.sqref): [r.type for r in v] for k, v in b.conditional_formatting._cf_rules.items()}
    for head, typ in (("주문량", "cellIs"), ("상품옵션", "containsText")):
        if head in heads:
            col = get_column_letter(heads.index(head) + 1)
            if typ not in cf.get(f"{col}2:{col}1000", []):
                d.append(("서식", "", f"조건부서식:{head}", typ, cf.get(f"{col}2:{col}1000")))
    return d


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일")
    p.add_argument("out", type=Path, help="내부보관용 파일")
    p.add_argument("--config", type=Path, default=S.DEFAULT_CFG)
    a = p.parse_args()
    for f in (a.src, a.out):
        if not f.exists():
            print(f"파일 없음: {f}", file=sys.stderr)
            return 1
    diffs, n = validate(a.src, a.out, S.load_cfg(a.config))
    print(f"검증 대상 {n}행 | 불일치 {len(diffs)}건")
    for cat, r, col, *_ in diffs:
        print(f"  - [{cat}] {r}행 {col}")
    if diffs:
        print(f"상세(값 포함): {write_report(diffs)}")
    print("결과:", "통과" if not diffs else "실패")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
