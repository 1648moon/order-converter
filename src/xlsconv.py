"""구형 엑셀(.xls, OLE2) 원본을 .xlsx 로 바꾼다. 확장자가 아니라 파일 내용으로 판단한다."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

OLE2_MAGIC = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"


def is_xls(path: Path) -> bool:
    try:
        with open(path, "rb") as f:
            return f.read(8) == OLE2_MAGIC
    except OSError:
        return False


def xls_to_xlsx(src: Path, dst: Path) -> Path:
    """첫 시트의 값을 그대로 옮겨 dst(.xlsx)로 저장한다 (서식은 옮기지 않음)."""
    import xlrd
    from openpyxl import Workbook

    book = xlrd.open_workbook(src, formatting_info=False)
    sh = book.sheet_by_index(0)
    wb = Workbook()
    ws = wb.active
    ws.title = sh.name[:31] or "Sheet1"
    for r in range(sh.nrows):
        for c in range(sh.ncols):
            cell = sh.cell(r, c)
            t, v = cell.ctype, cell.value
            if t in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                continue
            if t == xlrd.XL_CELL_DATE:
                try:
                    v = xlrd.xldate.xldate_as_datetime(v, book.datemode)
                except Exception:
                    pass
            elif t == xlrd.XL_CELL_BOOLEAN:
                v = bool(v)
            elif t == xlrd.XL_CELL_NUMBER and float(v).is_integer():
                v = int(v)
            elif t == xlrd.XL_CELL_ERROR:
                continue
            ws.cell(r + 1, c + 1, v)
    dst.parent.mkdir(parents=True, exist_ok=True)
    wb.save(dst)
    return dst


def ensure_xlsx(src: Path, work_dir: Path) -> Path:
    """src 가 .xls 면 work_dir 에 .xlsx 로 변환해 그 경로를, 아니면 src 를 그대로 돌려준다."""
    if not is_xls(src):
        return src
    return xls_to_xlsx(src, work_dir / (src.stem + ".xlsx"))
