"""산출물 파일명 규칙 (memory: excel-filename-rules).

    공장용(경동)  YY-MM-DD 브랜드주문({A})-{V}.xlsx     A: 오전 1 / 오후 2,  V: 같은 날·같은 A 재작업마다 +1 (1부터)
    공장용(CJ)    YY-MM-DD 브랜드주문({A})-CJ.xlsx
    택배용        YY-MM-DD 브랜드주문(합동)-신안-{오전|오후}.xlsx
    내부보관용    YY-MM-DD 발송내역.xlsx
    중간파일      {원본이름}_변환.xlsx   (내부용, 규칙 대상 아님)

오전/오후는 실행 시각 기준 (12시 이전 = 오전). V 는 output 아래(하위 폴더 포함)에 이미 있는 같은 날·같은 A 파일 중 최대값 + 1.
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

ENV_PATH = Path(__file__).resolve().parent.parent / ".env"


def brand() -> str:
    """파일명에 쓰는 브랜드명. 환경변수 BRAND_NAME → .env 의 BRAND_NAME → 기본값 '브랜드'.
    실제 이름은 소스에 두지 않고 .env(커밋 금지)에만 둔다."""
    if os.environ.get("BRAND_NAME"):
        return os.environ["BRAND_NAME"]
    try:
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            k, _, v = line.partition("=")
            if k.strip() == "BRAND_NAME" and v.strip():
                return v.split("#")[0].strip().strip('"').strip("'")
    except OSError:
        pass
    return "브랜드"


def ampm(now: datetime) -> tuple[int, str]:
    return (1, "오전") if now.hour < 12 else (2, "오후")


def _date(now: datetime) -> str:
    return now.strftime("%y-%m-%d")


def factory_name(output_root: Path, now: datetime | None = None) -> str:
    now = now or datetime.now()
    prefix = f"{_date(now)} {brand()}주문({ampm(now)[0]})-"
    pat = re.compile(rf"^{re.escape(prefix)}(\d+)\.xlsx$")
    found = [int(m.group(1)) for p in Path(output_root).rglob("*.xlsx") if (m := pat.match(p.name))]
    return f"{prefix}{max(found, default=0) + 1}.xlsx"


def courier_name(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{_date(now)} {brand()}주문(합동)-신안-{ampm(now)[1]}.xlsx"


def storage_name(now: datetime | None = None) -> str:
    now = now or datetime.now()
    return f"{_date(now)} 발송내역.xlsx"


def cj_stem(stem: str, suffix: str) -> str:
    """공장용 파일명(…({A})-{V})에서 CJ용 이름: …({A})-CJ. 규칙 형식이 아니면 stem + suffix."""
    m = re.match(rf"^(.*{re.escape(brand())}주문\(\d\))-\d+$", stem)
    return f"{m.group(1)}-CJ" if m else stem + suffix
