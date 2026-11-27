"""파일명 규칙 테스트. 실행: .venv/bin/python -I tests/test_naming.py"""
import os, sys, tempfile
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
os.environ["BRAND_NAME"] = "브랜드"  # 실제 .env 값과 무관하게 테스트
import naming as N  # noqa: E402

am, pm = datetime(2026, 11, 10, 9, 0), datetime(2026, 11, 10, 14, 0)
assert N.courier_name(am) == "26-11-10 브랜드주문(합동)-신안-오전.xlsx"
assert N.courier_name(pm) == "26-11-10 브랜드주문(합동)-신안-오후.xlsx"
assert N.storage_name(am) == "26-11-10 발송내역.xlsx"
assert N.ampm(datetime(2026, 11, 10, 11, 59))[0] == 1 and N.ampm(datetime(2026, 11, 10, 12, 0))[0] == 2
with tempfile.TemporaryDirectory() as d:
    d = Path(d); (d / "run1").mkdir()
    assert N.factory_name(d, am) == "26-11-10 브랜드주문(1)-1.xlsx"
    (d / "run1" / "26-11-10 브랜드주문(1)-1.xlsx").touch()
    assert N.factory_name(d, am) == "26-11-10 브랜드주문(1)-2.xlsx"      # 재작업 -> 버전업
    assert N.factory_name(d, pm) == "26-11-10 브랜드주문(2)-1.xlsx"      # 오후는 별도 A, V 1부터
    (d / "26-11-10 브랜드주문(1)-CJ.xlsx").touch()                        # CJ 는 버전 계산에서 제외
    assert N.factory_name(d, am) == "26-11-10 브랜드주문(1)-2.xlsx"
assert N.cj_stem("26-11-10 브랜드주문(1)-2", "-CJ") == "26-11-10 브랜드주문(1)-CJ"
assert N.cj_stem("주문원본1_공장", "-CJ") == "주문원본1_공장-CJ"
print("OK")

# 전체 다운로드 ZIP 이름: 산출물 파일명 앞 날짜(YYMMDD), 없으면 오늘
assert N.zip_name(["26-11-10 브랜드주문(1)-1.xlsx", "26-11-10 발송내역.xlsx"]) == "261110.zip"
assert N.zip_name(["26-11-09 발송내역.xlsx", "26-11-10 발송내역.xlsx"]) == "261110.zip"
assert N.zip_name(["a.xlsx", "b.xlsx"], datetime(2026, 11, 16)) == "261116.zip"

# 날짜는 원본 파일명에 적힌 날짜를 따른다 (주문일자 열과 무관)
assert N.filename_date("발송대기_(기본)-선택주문(2026-11-20 08;54;26) 원본.xlsx") == datetime(2026, 11, 20)
assert N.filename_date("주문_20261127.xlsx") == datetime(2026, 11, 27)
assert N.filename_date("주문원본.xlsx") is None
assert N.filename_date("주문_2026-13-45.xlsx") is None                     # 말이 안 되는 날짜는 무시
assert N.source_date(Path("/nonexistent/발송대기-선택주문(2026-11-27 08;00;00) 원본.xlsx")) == datetime(2026, 11, 27)
assert N.with_source_date(datetime(2026, 11, 28, 14, 5), Path("선택주문(2026-11-27 08;00;00).xlsx")) == datetime(2026, 11, 27, 14, 5)
