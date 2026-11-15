"""변환 한 번의 '개인정보 없는' 요약 기록을 만든다 (에이전트가 대화에 쓰는 유일한 데이터).

들어가는 것: 실행 이름, 전체 결과, 파일 수, 경고·실패 단계 이름, 주문 건수, 상품명 목록.
들어가지 않는 것: 수령자·전화번호·주소, 스크립트가 출력한 경고·오류 원문(셀 값이 섞일 수 있음).
상품명도 전화번호처럼 보이는 숫자열이 있으면 버린다.
"""
from __future__ import annotations

import re
from pathlib import Path

PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}(?!\d)")
MAX_NAMES = 30
MAX_LEN = 60


def safe_name(value) -> str | None:
    """상품명으로 써도 되는 짧은 문자열이면 정리해서 돌려주고, 아니면 None."""
    s = re.sub(r"\s+", " ", str(value or "")).strip()
    if not s or len(s) > MAX_LEN or PHONE_RE.search(s):
        return None
    return s


def _names(values) -> list[str]:
    seen: dict[str, None] = {}
    for v in values:
        n = safe_name(v)
        if n:
            seen[n] = None
    return list(seen)[:MAX_NAMES]


def unmatched_products(src: Path) -> tuple[int, list[str]]:
    """(주문 건수, 변환 표(규칙·매핑)에 없는 상품명 목록) - 원본 파일의 상품명·선택사항 열만 읽는다."""
    from openpyxl import load_workbook

    import rules
    from convert import KEY, active_rows, header_map

    ws = load_workbook(src, read_only=False).active
    h = header_map(ws)
    if KEY not in h or "상품명" not in h:
        return 0, []
    terms = rules.load_terms()
    rows = active_rows(ws, h)
    opt_col = h.get("선택사항")
    bad = []
    for r in rows:
        name = ws.cell(r, h["상품명"]).value
        option = ws.cell(r, opt_col).value if opt_col else None
        _, warn = rules.convert_product(name, option, terms)
        if warn == "변환 표에 없는 상품":
            bad.append(name)
    return len(rows), _names(bad)


def fee_missing_products(intermediate: Path) -> list[str]:
    """운임표에 규칙이 없어 기본운임이 적용된 상품(변환된 이름) - 중간파일에서 상품명·선택사항만 읽는다."""
    from openpyxl import load_workbook

    import factory as F
    from convert import active_rows

    ws = load_workbook(intermediate).active
    h, _ = F.locate(ws)
    cfg = F.load_cfg()
    kd, _cj, _unknown = F.split_rows(ws, h, active_rows(ws, h), cfg)
    return _names(F.fee_warnings(ws, h, kd, cfg))


def converted_source(run_dir: Path | None) -> Path | None:
    """.xls 원본은 run_all 이 run_dir/원본변환/ 에 .xlsx 로 바꿔 쓴다. 그 파일이 있으면 원본 대신 그것을 읽는다."""
    if not run_dir:
        return None
    return next(iter(sorted((Path(run_dir) / "원본변환").glob("*.xlsx"))), None)


def build_record(src: Path, run_dir: Path | None, summary) -> dict:
    """summary: runinfo.RunSummary. 일부를 읽지 못해도 가능한 만큼만 채워 돌려준다(변환 결과에는 영향 없음)."""
    rec = {"run": summary.name, "overall": summary.overall, "files": len(summary.files),
           "warn_stages": list(summary.warn_stages), "fail_stages": list(summary.fail_stages),
           "orders": None, "unmatched_products": [], "fee_missing_products": [], "partial": False}
    try:
        rec["orders"], rec["unmatched_products"] = unmatched_products(converted_source(run_dir) or src)
    except Exception:
        rec["partial"] = True
    try:
        inter = next(iter(sorted(run_dir.glob("*_변환.xlsx"))), None) if run_dir else None
        if inter:
            rec["fee_missing_products"] = fee_missing_products(inter)
    except Exception:
        rec["partial"] = True
    return rec
