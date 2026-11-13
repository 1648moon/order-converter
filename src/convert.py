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


CLAIM = "클레임사유"


def is_claim(ws, h: dict, r: int) -> bool:
    """클레임사유가 적힌 주문(취소·반품 등)이면 True."""
    c = h.get(CLAIM)
    return bool(c) and str(ws.cell(r, c).value or "").strip() != ""


def active_rows(ws, h: dict) -> list[int]:
    """산출물(공장/택배/내부보관)에 넣을 행: 주문번호가 있고 클레임이 없는 행. 중간파일에는 클레임 행도 그대로 남는다."""
    return [r for r in data_rows(ws, h[KEY]) if not is_claim(ws, h, r)]


def qty_of(ws, h: dict, r: int) -> int:
    """행의 수량(정수 2 이상이면 그 값, 아니면 1)."""
    c = h.get("수량")
    v = ws.cell(r, c).value if c else None
    return int(v) if isinstance(v, (int, float)) and float(v).is_integer() and v > 1 else 1


def expand_rows_by_qty(ws, h: dict) -> int:
    """수량이 1 초과인 주문(클레임 제외)은 같은 행을 수량만큼 복사해 아래에 붙이고, 각 행의 수량은 1로 한다.
    복사한 행 수를 돌려준다."""
    added = 0
    last = max(data_rows(ws, h[KEY]), default=1)
    for r in range(last, 1, -1):
        if ws.cell(r, h[KEY]).value in (None, "") or is_claim(ws, h, r):
            continue
        q = qty_of(ws, h, r)
        if q <= 1:
            continue
        ws.insert_rows(r + 1, q - 1)
        for k in range(1, q):
            for c in range(1, ws.max_column + 1):
                src, dst = ws.cell(r, c), ws.cell(r + k, c)
                dst.value, dst._style = src.value, copy.copy(src._style)
            if ws.row_dimensions[r].height:
                ws.row_dimensions[r + k].height = ws.row_dimensions[r].height
        for k in range(q):
            ws.cell(r + k, h["수량"]).value = 1
        added += q - 1
    return added


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

    n_added = expand_rows_by_qty(ws, h) if "수량" in h else 0
    if n_added:
        print(f"수량 2개 이상 주문을 수량만큼 행으로 복사했습니다 (추가 {n_added}행, 각 행 수량 1).")
    rows = data_rows(ws, h[KEY])
    warnings: list[tuple[int, str, str]] = []
    n_claim = sum(1 for r in rows if is_claim(ws, h, r))
    if n_claim:
        print(f"클레임 {n_claim}건은 중간파일에 남기고, 공장/택배/내부보관 파일에서는 제외됩니다.")
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
        new_opt, w = rules.convert_option(opt, terms, name)
        if w:
            warnings.append((r, "선택사항", w))
        ws.cell(r, h["상품명"]).value = new_name
        ws.cell(r, h["선택사항"]).value = new_opt

    # 1-1) 부품(단가 <= parts_rule.max_unit_price)은 택배사를 CJ 로
    if "단가" in h and "택배사" in h:
        n_part = 0
        for r in rows:
            cur = ws.cell(r, h["택배사"]).value
            new = rules.expected_carrier(cur, ws.cell(r, h["단가"]).value, terms)
            if new != cur:
                ws.cell(r, h["택배사"]).value = new
                n_part += 1
        if n_part:
            print(f"부품(단가 {terms['parts_rule']['max_unit_price']:,}원 이하) {n_part}건의 택배사를 {terms['parts_rule']['carrier']}로 변경했습니다.")

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
