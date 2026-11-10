"""템플릿 기반 엑셀 작성 공통 도구 (공장용/택배용)."""
from __future__ import annotations

import copy
import re
from pathlib import Path

from openpyxl import load_workbook
from openpyxl.comments import Comment
from openpyxl.formatting.formatting import ConditionalFormattingList
from openpyxl.styles import Alignment, Font, PatternFill

ROOT = Path(__file__).resolve().parent.parent
DATA_FONT = "Malgun Gothic"
LAST_ROW = 1000   # 템플릿이 서식을 깔아 둔 마지막 행


def open_template(path: str | Path, headers: list[str]):
    """템플릿을 열고 헤더가 설정과 같은지, 데이터 영역이 비어 있는지 확인."""
    p = Path(path)
    p = p if p.is_absolute() else ROOT / p
    if not p.exists():
        raise SystemExit(f"템플릿 파일 없음: {p}")
    wb = load_workbook(p)
    ws = wb.active
    got = [ws.cell(1, c).value for c in range(1, len(headers) + 1)]
    if got != headers:
        raise SystemExit(f"템플릿 헤더가 설정과 다릅니다.\n  템플릿: {got}\n  설정:   {headers}")
    extra = [ws.cell(1, c).value for c in range(len(headers) + 1, ws.max_column + 1)
             if ws.cell(1, c).value not in (None, "")]
    if extra:
        raise SystemExit(f"템플릿에 설정에 없는 헤더가 더 있습니다: {extra}")
    for r in range(2, ws.max_row + 1):
        if any(ws.cell(r, c).value not in (None, "") for c in range(1, ws.max_column + 1)):
            raise SystemExit(f"템플릿 {r}행에 데이터가 있습니다. 빈 템플릿이어야 합니다.")
    return wb, ws


def style_data(ws, r: int, ncols: int, text_cols: set[int]) -> None:
    """데이터 셀: 템플릿 헤더와 같은 글꼴, 세로 가운데. 우편번호/전화번호 등은 문자열 서식."""
    for c in range(1, ncols + 1):
        cell = ws.cell(r, c)
        cell.font = Font(name=DATA_FONT, size=11)
        cell.alignment = Alignment(vertical="center")
        if c in text_cols:
            cell.number_format = "@"


def mark_warning(cell, warning: dict) -> None:
    cell.fill = PatternFill("solid", fgColor=warning["fill"], bgColor=warning["fill"])
    cell.font = Font(name=DATA_FONT, size=11, bold=True)
    cell.comment = Comment(warning["note"], "order-converter", width=260, height=60)


def is_warning(cell, warning: dict) -> bool:
    return bool(cell.fill and cell.fill.fill_type == "solid" and cell.fill.fgColor.rgb == warning["fill"])


def _sig(rule) -> tuple:
    d = rule.dxf
    return (rule.type, rule.operator, rule.text, tuple(rule.formula or []),
            d.fill.bgColor.rgb if d and d.fill and d.fill.bgColor else None,
            d.font.color.rgb if d and d.font and d.font.color else None,
            bool(d and d.font and d.font.b))


def normalize_cf(ws, last_row: int = LAST_ROW) -> None:
    """템플릿 조건부 서식이 일부 행(예: 2~4행)에만 걸려 있으면 2~last_row 전체로 넓힌다.
    같은 열의 같은 규칙은 하나로 합친다."""
    seen: dict[tuple, tuple] = {}
    for cf, rules in ws.conditional_formatting._cf_rules.items():
        for rng in cf.sqref.ranges:
            for col in range(rng.min_col, rng.max_col + 1):
                letter = ws.cell(1, col).column_letter
                for rule in rules:
                    rule = copy.copy(rule)
                    rule.formula = [re.sub(r",\(([A-Z]{1,3})\d+\)\)", r",(\g<1>2))", f)
                                    for f in (rule.formula or [])]
                    key = (letter, _sig(rule))
                    seen.setdefault(key, (letter, rule))
    new = ConditionalFormattingList()
    for prio, (letter, rule) in enumerate(seen.values(), start=1):
        rule.priority = prio
        new.add(f"{letter}2:{letter}{last_row}", rule)
    ws.conditional_formatting = new


def template_diffs(ws, tws, ncols: int) -> list[tuple]:
    """결과 파일이 템플릿의 열 너비·행 높이·헤더 서식을 유지했는지."""
    d: list[tuple] = []

    def widths(w):
        out = {}
        for v in w.column_dimensions.values():
            for c in range((v.min or 1), (v.max or v.min or 1) + 1):
                out[c] = round(v.width or 0, 2)
        return out

    wa, wt = widths(ws), widths(tws)
    for c in range(1, ncols + 1):
        if wa.get(c) != wt.get(c):
            d.append(("서식", 1, f"열너비:{ws.cell(1, c).value}", wt.get(c), wa.get(c)))
    for r in (1, 2):
        if ws.row_dimensions[r].height != tws.row_dimensions[r].height:
            d.append(("서식", r, "행높이", tws.row_dimensions[r].height, ws.row_dimensions[r].height))
    for c in range(1, ncols + 1):
        a, t = ws.cell(1, c), tws.cell(1, c)
        if (a.font.name, a.font.sz, a.fill.fill_type, a.number_format) != (t.font.name, t.font.sz, t.fill.fill_type, t.number_format):
            d.append(("서식", 1, f"헤더서식:{a.value}", "템플릿과 동일", "다름"))
    return d
