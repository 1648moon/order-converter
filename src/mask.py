"""주문원본 엑셀의 개인정보 컬럼을 가명 처리한 샘플을 만든다. (로컬 실행 전용)

사용법:
    .venv/bin/python src/mask.py input/원본.xlsx
    .venv/bin/python src/mask.py input/원본.xlsx -o input/원본_masked.xlsx
    .venv/bin/python src/mask.py input/원본.xlsx --rows 20      # 데이터 20행만 남김
    .venv/bin/python src/mask.py input/원본.xlsx --columns 쇼핑몰ID 구매자 ...

특징:
- 같은 원본 값은 항상 같은 가명으로 바뀐다 (주문 간 동일인 관계 유지).
- 구매자/수령자는 이름 매핑을 공유한다 (구매자 == 수령자 관계 유지).
- 우편번호는 자릿수와 타입(문자/숫자)을 유지한다.
- 시트 구조, 서식, 병합셀은 openpyxl로 그대로 유지한다.
- 원본↔가명 매핑표는 저장하지 않는다 (매핑표 자체가 개인정보이므로).
- 화면에는 건수만 출력하고 실제 값은 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

DEFAULT_COLUMNS = ["쇼핑몰ID", "구매자", "수령자", "우편번호", "주소"]
HEADER_SCAN_ROWS = 30

# 컬럼별 가명 종류. 같은 kind는 매핑표를 공유한다.
KIND = {"쇼핑몰ID": "id", "구매자": "name", "수령자": "name",
        "우편번호": "zip", "주소": "addr"}

STREETS = ["테스트로", "샘플로", "예시길", "가상대로"]
DISTRICTS = ["가나구", "다라구", "마바구", "사아구"]


class Pseudonymizer:
    def __init__(self) -> None:
        self.maps: dict[str, dict[str, str]] = {}

    def _next(self, kind: str, key: str, make) -> str:
        m = self.maps.setdefault(kind, {})
        if key not in m:
            m[key] = make(len(m) + 1)
        return m[key]

    def apply(self, kind: str, value):
        if value is None or (isinstance(value, str) and not value.strip()):
            return value
        if isinstance(value, str) and value.startswith("="):
            return value  # 수식은 건드리지 않음
        key = str(value).strip()
        if kind == "id":
            return self._next("id", key, lambda n: f"user{n:04d}")
        if kind == "name":
            return self._next("name", key, lambda n: f"고객{n:04d}")
        if kind == "addr":
            return self._next(
                "addr", key,
                lambda n: f"가상시 {DISTRICTS[n % 4]} {STREETS[n % 4]} {n}길 {n % 90 + 1}",
            )
        if kind == "zip":
            numeric = isinstance(value, (int, float))
            if numeric:  # 엑셀이 앞자리 0을 지운 경우(6234 -> 06234)를 같은 값으로 취급
                key = str(int(value)).zfill(5)
            width = max(len(key), 5)
            fake = self._next("zip", key, lambda n: str(10000 + n).zfill(width))
            return int(fake) if numeric else fake
        raise ValueError(kind)


def find_header(ws, wanted: list[str]):
    """상단 N행에서 대상 컬럼명이 가장 많이 발견되는 행을 헤더로 본다."""
    best_row, best_hits, best_cols = None, 0, {}
    for r in range(1, min(ws.max_row, HEADER_SCAN_ROWS) + 1):
        cols = {}
        for c in range(1, ws.max_column + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip() in wanted:
                cols.setdefault(v.strip(), c)
        if len(cols) > best_hits:
            best_row, best_hits, best_cols = r, len(cols), cols
    return best_row, best_cols


def mask_workbook(src: Path, dst: Path, columns: list[str], rows: int | None) -> int:
    wb = load_workbook(src)
    ps = Pseudonymizer()
    total = 0
    for ws in wb.worksheets:
        header_row, cols = find_header(ws, columns)
        if not cols:
            print(f"[{ws.title}] 대상 컬럼 없음 - 건너뜀")
            continue
        missing = [c for c in columns if c not in cols]
        if missing:
            print(f"[{ws.title}] 찾지 못한 컬럼: {', '.join(missing)}")
        last = ws.max_row
        if rows is not None and header_row + rows < last:
            ws.delete_rows(header_row + rows + 1, last - (header_row + rows))
            last = header_row + rows
        count = 0
        for name, col in cols.items():
            kind = KIND.get(name, "name")
            for r in range(header_row + 1, last + 1):
                cell = ws.cell(r, col)
                new = ps.apply(kind, cell.value)
                if new is not cell.value:
                    cell.value = new
                    count += 1
        total += count
        print(f"[{ws.title}] 헤더 {header_row}행, 마스킹 컬럼 {len(cols)}개, 셀 {count}개, 데이터 {last - header_row}행")
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return total


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path)
    p.add_argument("-o", "--output", type=Path, help="기본값: <원본>_masked.xlsx")
    p.add_argument("--columns", nargs="+", default=DEFAULT_COLUMNS)
    p.add_argument("--rows", type=int, help="시트별 데이터 행 수 제한 (샘플 축소용)")
    a = p.parse_args()

    if not a.src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1
    dst = a.output or a.src.with_name(a.src.stem + "_masked.xlsx")
    if dst.resolve() == a.src.resolve():
        print("출력 경로가 원본과 같습니다.", file=sys.stderr)
        return 1
    n = mask_workbook(a.src, dst, a.columns, a.rows)
    print(f"완료: {dst} (총 {n}셀 마스킹)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
