"""중간파일과 택배 접수용 파일의 공통 정보 동일성 검증.

사용법:
    .venv/bin/python src/validate_courier.py output/주문원본1_변환.xlsx output/주문원본1_택배.xlsx

검증 항목
  1. 헤더가 설정(config/courier.yaml)과 정확히 같은지
  2. 행 수
  3. 공통 정보: 받는분/주소/우편번호/품목명/메모/전화번호(기타전화번호 포함)가 중간파일과 동일
  4. 고정값(선불후불/수량/포장상태/기타운임/개별단가), 배송운임(=공장파일 택배운임 규칙)과, 값을 넣지 않기로 한 컬럼이 비어 있는지
상세(값 포함)는 reports/ CSV에만 기록하고 화면에는 건수·위치만 출력한다.
종료코드: 0 통과 / 1 불일치
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import courier as C  # noqa: E402
import factory as F  # noqa: E402
import xlsxkit as xk  # noqa: E402
from convert import KEY, data_rows  # noqa: E402
from validate import norm, write_report  # noqa: E402


def validate(src: Path, out: Path, cfg: dict) -> tuple[list[tuple], int]:
    a = load_workbook(src).active
    b = load_workbook(out).active
    h, extra_col = F.locate(a)
    diffs: list[tuple] = []

    n = len(cfg["headers"])
    heads = [b.cell(1, c).value for c in range(1, n + 1)]
    extra_heads = [b.cell(1, c).value for c in range(n + 1, b.max_column + 1) if b.cell(1, c).value not in (None, "")]
    if heads != cfg["headers"] or extra_heads:
        diffs.append(("헤더", 1, "", cfg["headers"], heads))
        return diffs, 0
    hb = {name: i + 1 for i, name in enumerate(heads)}

    ra = data_rows(a, h[KEY])
    rb = [r for r in range(2, b.max_row + 1)
          if any(b.cell(r, c).value not in (None, "") for c in range(1, b.max_column + 1))]
    if len(ra) != len(rb):
        diffs.append(("행수", "", "", len(ra), len(rb)))
        return diffs, len(ra)

    filled = {"받는분", "전화번호", "기타전화번호", "배송운임", *cfg["copy"], *cfg["fixed"]}
    for r1, r2 in zip(ra, rb):
        exp = C.build_row(a, r1, h, extra_col, cfg)
        for name in cfg["headers"]:
            got = b.cell(r2, hb[name]).value
            if name in ("우편번호", "전화번호", "기타전화번호"):
                got = C.text(got)
            if name in filled:
                e = exp[name]
            else:
                e = None   # 값을 넣지 않기로 한 컬럼은 비어 있어야 함
            if norm(e) != norm(got):
                diffs.append(("불일치", r2, name, e, got))
        if b.cell(r2, hb["전화번호"]).value != b.cell(r2, hb["기타전화번호"]).value:
            diffs.append(("불일치", r2, "전화번호≠기타전화번호", "", ""))
    # 운임표에 없는 상품은 배송운임 셀에 경고색, 그 외에는 경고색이 없어야 함
    fcfg = C.factory_cfg()
    for r1, r2 in zip(ra, rb):
        ok = F.shipping_fee_info(a.cell(r1, h["상품명"]).value, a.cell(r1, h["선택사항"]).value, fcfg)[1]
        if xk.is_warning(b.cell(r2, hb["배송운임"]), fcfg["warning"]) == ok:
            diffs.append(("경고표시", r2, "배송운임", "경고색 없음" if ok else "경고색", "경고색" if ok else "경고색 없음"))
    tws = load_workbook(xk.ROOT / cfg["template"]).active
    diffs += xk.template_diffs(b, tws, n)
    return diffs, len(ra)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일")
    p.add_argument("out", type=Path, help="택배 접수용 파일")
    p.add_argument("--config", type=Path, default=C.DEFAULT_CFG)
    a = p.parse_args()
    for f in (a.src, a.out):
        if not f.exists():
            print(f"파일 없음: {f}", file=sys.stderr)
            return 1
    diffs, n = validate(a.src, a.out, C.load_cfg(a.config))
    print(f"검증 대상 {n}행 | 불일치 {len(diffs)}건")
    for cat, r, col, *_ in diffs:
        print(f"  - [{cat}] {r}행 {col}")
    if diffs:
        print(f"상세(값 포함): {write_report(diffs)}")
    print("결과:", "통과" if not diffs else "실패")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
