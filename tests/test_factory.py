"""공장파일 규칙 단위 테스트 (기대값은 사용자가 정한 규칙을 직접 적은 것).
실행: .venv/bin/python -I tests/test_factory.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import factory as F  # noqa: E402

cfg = F.load_cfg()
A = "100%조립요청"

# 택배운임: 조립 20000 / 미조립 기본 10000 / 미조립+시애틀F26 12000
assert F.shipping_fee("빅마운틴/블랙(2026)", A, cfg) == 20000
assert F.shipping_fee("시애틀F26/블랙", A, cfg) == 20000      # 조립이면 시애틀F26도 20000
assert F.shipping_fee("시애틀F26/블랙", None, cfg) == 12000
assert F.shipping_fee("빅마운틴/블랙(2026)", None, cfg) == 10000
assert F.shipping_fee("시애틀GS20/라이트바이올렛", "", cfg) == 10000

# 상품옵션: 선택사항 + ", " + 추가구성
assert F.product_option(A, None, cfg) == A
assert F.product_option(A, "헬멧", cfg) == "100%조립요청, 헬멧"
assert F.product_option(A, "헬멧 라이트", cfg) == "100%조립요청, 헬멧 라이트"
assert F.product_option(A, "헬멧,라이트", cfg) == "100%조립요청, 헬멧, 라이트"   # 쉼표 구분 -> 각각 ', '
assert F.product_option(A, "헬멧 ,  라이트 ,", cfg) == "100%조립요청, 헬멧, 라이트"  # 공백/빈 항목 정리
assert F.product_option(None, "헬멧", cfg) == "헬멧"            # 미조립 + 추가구성
assert F.product_option(None, None, cfg) is None

# 우편번호: 숫자로 저장돼 앞자리 0이 빠진 경우 복원
assert F.zip_text(6234) == "06234" and F.zip_text(6234.0) == "06234" and F.zip_text("06234") == "06234"
assert cfg["payment_term"] == "선불"
print("OK")

# ---- 택배사 구분 (CJ / 경동) ----
assert F.carrier_kind("CJ택배", cfg) == "cj"
assert F.carrier_kind(" cj택배 ", cfg) == "cj"          # 대소문자·공백 무시
assert F.carrier_kind("경동택배", cfg) == "kd"
assert F.carrier_kind("로젠택배", cfg) is None and F.carrier_kind(None, cfg) is None
assert cfg["carriers"]["cj_fee"] == 2000
print("OK (carrier)")
