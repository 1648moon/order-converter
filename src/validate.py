"""원본(주문원본1)과 변환 결과의 공통 정보 동일성 검증.

사용법:
    .venv/bin/python src/validate.py input/주문원본1.xlsx output/주문원본1_변환.xlsx
    .venv/bin/python src/validate.py 원본 결과 --golden input/주문원본2.xlsx   # 정답 파일과도 비교

검증 항목
  1. 헤더: 원본 헤더 순서 + 신규(빈 헤더) 컬럼 1개 외에 차이 없음
  2. 행: 행 수, 주문번호 목록과 순서 동일
  3. 공통 컬럼: 변환 대상(상품명/선택사항/신규컬럼) 외 모든 컬럼의 셀 값 동일
  4. 변환 컬럼: 원본에 규칙을 다시 적용한 기대값과 일치
상세 불일치(실제 값 포함)는 reports/ 의 CSV에만 기록하고, 화면에는 건수·위치만 출력한다.
종료코드: 0 통과 / 1 불일치 있음
"""
from __future__ import annotations

import argparse
import csv
import os
import sys
from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules  # noqa: E402
from convert import KEY, data_rows, header_map  # noqa: E402


def norm(v):
    return "" if v is None else v


def load(path: Path):
    ws = load_workbook(path, data_only=False).active
    return ws, header_map(ws)


def validate(src: Path, out: Path, terms: dict) -> list[tuple]:
    """불일치 목록: (분류, 행, 컬럼, 원본값, 결과값)"""
    a, ha = load(src)
    b, hb = load(out)
    diffs: list[tuple] = []
    transformed = {"상품명", "선택사항"}

    # 1) 헤더
    only_a = [k for k in ha if k not in hb]
    only_b = [k for k in hb if k not in ha]
    if only_a or only_b:
        diffs.append(("헤더", 1, "", f"결과에 없음:{only_a}", f"원본에 없음:{only_b}"))
    if b.max_column != a.max_column + 1:
        diffs.append(("헤더", 1, "", f"컬럼수 {a.max_column}", f"컬럼수 {b.max_column} (기대 {a.max_column + 1})"))
    pos = ha[terms["insert_column"]["after"]] + 1
    if norm(b.cell(1, pos).value) != norm(terms["insert_column"]["header"] or None):
        diffs.append(("헤더", 1, "신규컬럼", "", b.cell(1, pos).value))
    order_a = [k for k, _ in sorted(ha.items(), key=lambda x: x[1])]
    order_b = [k for k, _ in sorted(hb.items(), key=lambda x: x[1]) if k in ha]
    if order_a != order_b:
        diffs.append(("헤더", 1, "", "컬럼 순서", "컬럼 순서가 다름"))

    # 2) 행
    ra, rb = data_rows(a, ha[KEY]), data_rows(b, hb[KEY])
    if len(ra) != len(rb):
        diffs.append(("행수", "", KEY, len(ra), len(rb)))
    ka = [a.cell(r, ha[KEY]).value for r in ra]
    kb = [b.cell(r, hb[KEY]).value for r in rb]
    if ka != kb:
        diffs.append(("행", "", KEY, "주문번호 목록/순서", "원본과 다름"))

    # 3) 공통 컬럼 + 4) 변환 컬럼
    for i, (r1, r2) in enumerate(zip(ra, rb)):
        for name, c1 in ha.items():
            if name not in hb:
                continue
            v1, v2 = a.cell(r1, c1).value, b.cell(r2, hb[name]).value
            if name in transformed:
                continue
            if norm(v1) != norm(v2):
                diffs.append(("공통값", r2, name, v1, v2))
        opt = a.cell(r1, ha["선택사항"]).value
        exp_name, _ = rules.convert_product(a.cell(r1, ha["상품명"]).value, opt, terms)
        exp_opt, _ = rules.convert_option(opt, terms, a.cell(r1, ha["상품명"]).value)
        exp_extra = rules.make_extra(a.cell(r1, ha["수령자"]).value, a.cell(r1, ha["주소"]).value, terms)
        for label, exp, got in (
            ("상품명", exp_name, b.cell(r2, hb["상품명"]).value),
            ("선택사항", exp_opt, b.cell(r2, hb["선택사항"]).value),
            ("신규컬럼", exp_extra, b.cell(r2, pos).value),
        ):
            if norm(exp) != norm(got):
                diffs.append(("변환값", r2, label, exp, got))
    return diffs


def compare_golden(out: Path, golden: Path) -> list[tuple]:
    """결과와 정답 파일을 셀 단위로 비교 (컬럼 위치 기준)."""
    b, _ = load(out)
    g, _ = load(golden)
    diffs = []
    rows = max(len(data_rows(b, header_map(b)[KEY])), len(data_rows(g, header_map(g)[KEY]))) + 1
    for r in range(1, rows + 1):
        for c in range(1, max(b.max_column, g.max_column) + 1):
            v1, v2 = b.cell(r, c).value, g.cell(r, c).value
            if norm(v1) != norm(v2):
                diffs.append(("정답과 다름", r, b.cell(1, c).value or f"열{c}", v1, v2))
    return diffs


def write_report(diffs: list[tuple]) -> Path:
    d = Path(os.environ.get("ORDER_REPORT_DIR", "reports"))   # run_all.py 는 실행 폴더 안으로 지정
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"validation_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with p.open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["분류", "행", "컬럼", "원본(기대)값", "결과값"])
        w.writerows(diffs)
    return p


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path)
    p.add_argument("out", type=Path)
    p.add_argument("--golden", type=Path)
    p.add_argument("--terms", type=Path, default=rules.DEFAULT_TERMS)
    a = p.parse_args()
    for f in (a.src, a.out, *( [a.golden] if a.golden else [])):
        if not f.exists():
            print(f"파일 없음: {f}", file=sys.stderr)
            return 1

    diffs = validate(a.src, a.out, rules.load_terms(a.terms))
    n_rows = len(data_rows(*[x for x in (load(a.src)[0],)], header_map(load(a.src)[0])[KEY]))
    print(f"검증 대상 {n_rows}행 | 원본↔결과 불일치 {len(diffs)}건")
    golden = compare_golden(a.out, a.golden) if a.golden else []
    if a.golden:
        print(f"정답 파일({a.golden.name})과 셀 차이 {len(golden)}건")
    allc = diffs + golden
    for cat, r, col, *_ in allc:
        print(f"  - [{cat}] {r}행 {col}")
    if allc:
        print(f"상세(값 포함): {write_report(allc)}")
    print("결과:", "통과" if not diffs else "실패")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main())
