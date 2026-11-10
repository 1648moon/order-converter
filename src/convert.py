"""주문원본1 -> 주문원본2 형태 변환.

사용법:
    .venv/bin/python src/convert.py input/주문원본1.xlsx
    .venv/bin/python src/convert.py input/주문원본1.xlsx -o output/결과.xlsx

종료코드: 0 정상 / 2 변환 표에 없는 값이 있어 일부를 원본 그대로 둠(경고) / 1 오류
"""
from __future__ import annotations

import argparse
import copy
import sys
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.utils import get_column_letter

sys.path.insert(0, str(Path(__file__).resolve().parent))
import rules  # noqa: E402

KEY = "주문번호"


def header_map(ws) -> dict[str, int]:
    return {ws.cell(1, c).value: c for c in range(1, ws.max_column + 1)
            if ws.cell(1, c).value not in (None, "")}


def data_rows(ws, key_col: int) -> list[int]:
    return [r for r in range(2, ws.max_row + 1) if ws.cell(r, key_col).value not in (None, "")]


def apply_llm_fallback(ws, h, rows, terms: dict, map_path: Path) -> int:
    """규칙·매핑표에 없는 상품명을 LLM 에 제안받아 매핑표에 status: llm 으로 저장. 새로 저장한 건수 반환."""
    import llm_fallback  # 지연 import: --llm 을 쓸 때만 anthropic 필요
    missing = sorted({str(ws.cell(r, h["상품명"]).value).strip() for r in rows
                      if rules.convert_product(ws.cell(r, h["상품명"]).value,
                                               ws.cell(r, h["선택사항"]).value,
                                               terms)[1] == "변환 표에 없는 상품"})
    if not missing:
        return 0
    got = llm_fallback.suggest(missing, terms)
    for name, tpl in got.items():
        terms["_map"][name.replace(" ", "")] = {"name": name, "template": tpl, "status": "llm"}
    if got:
        rules.save_product_map(terms["_map"], map_path)
    return len(got)


def convert(src: Path, dst: Path, terms: dict, use_llm: bool = False,
            map_path: Path = rules.DEFAULT_MAP) -> list[tuple[int, str, str]]:
    wb = load_workbook(src)
    ws = wb.active
    h = header_map(ws)
    for need in (KEY, "상품명", "선택사항", "수령자", "주소", terms["insert_column"]["after"]):
        if need not in h:
            raise SystemExit(f"필수 컬럼 없음: {need}")

    rows = data_rows(ws, h[KEY])
    warnings: list[tuple[int, str, str]] = []
    if use_llm:
        n = apply_llm_fallback(ws, h, rows, terms, map_path)
        print(f"LLM 상품명 제안 {n}건 -> {map_path} (status: llm, 확인 필요)")

    # 1) 값 변환 (컬럼 삽입 전, 원래 위치 기준)
    for r in rows:
        opt = ws.cell(r, h["선택사항"]).value
        name = ws.cell(r, h["상품명"]).value
        new_name, w = rules.convert_product(name, opt, terms)
        if w:
            warnings.append((r, "상품명", w))
        new_opt, w = rules.convert_option(opt, terms)
        if w:
            warnings.append((r, "선택사항", w))
        ws.cell(r, h["상품명"]).value = new_name
        ws.cell(r, h["선택사항"]).value = new_opt

    # 2) 신규 컬럼 삽입 (서식·열너비 이동 포함)
    pos = h[terms["insert_column"]["after"]] + 1
    widths = {}
    for d in ws.column_dimensions.values():
        if d.width:
            for c in range(d.min or 1, (d.max or d.min or 1) + 1):
                widths[c] = d.width
    ws.insert_cols(pos)
    ws.column_dimensions.clear()
    for c, w in widths.items():
        ws.column_dimensions[get_column_letter(c + 1 if c >= pos else c)].width = w
    if pos - 1 in widths:
        ws.column_dimensions[get_column_letter(pos)].width = widths[pos - 1]
    for r in range(1, ws.max_row + 1):
        ws.cell(r, pos)._style = copy.copy(ws.cell(r, pos - 1)._style)
    ws.cell(1, pos).value = terms["insert_column"]["header"] or None
    h2 = header_map(ws)
    for r in rows:
        ws.cell(r, pos).value = rules.make_extra(
            ws.cell(r, h2["수령자"]).value, ws.cell(r, h2["주소"]).value, terms)

    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return warnings


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path)
    p.add_argument("-o", "--output", type=Path)
    p.add_argument("--terms", type=Path, default=rules.DEFAULT_TERMS)
    p.add_argument("--map", type=Path, default=rules.DEFAULT_MAP, help="상품명 매핑표(LLM 제안 저장 위치)")
    p.add_argument("--llm", action="store_true", help="규칙에 없는 상품명을 LLM 으로 제안받아 적용 (ANTHROPIC_API_KEY 필요)")
    a = p.parse_args()
    if not a.src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1
    dst = a.output or Path("output") / f"{a.src.stem}_변환.xlsx"
    if dst.resolve() == a.src.resolve():
        print("출력 경로가 원본과 같습니다.", file=sys.stderr)
        return 1
    warnings = convert(a.src, dst, rules.load_terms(a.terms, a.map), a.llm, a.map)
    print(f"변환 완료: {dst}")
    for r, col, msg in warnings:
        tail = "확인 후 product_map.yaml 에서 status 를 ok 로" if msg == rules.LLM_WARN else "원본 값 유지"
        print(f"  경고: {r}행 [{col}] {msg} - {tail}")
    return 2 if warnings else 0


if __name__ == "__main__":
    sys.exit(main())
