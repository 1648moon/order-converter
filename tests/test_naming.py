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
