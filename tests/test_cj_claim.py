"""CJ대한통운 표기 / 클레임 제외 / 소품 상품명 변환 테스트. 실행: python -I tests/test_cj_claim.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import rules, convert, factory as F, llm_fallback as L  # noqa: E402
from openpyxl import Workbook  # noqa: E402

terms = rules.load_terms()
cfg = F.load_cfg()

# 사용자가 정한 변환 예시 (소품)
helmet = "삼천리자전거 어반 어린이용 헬멧 SH700 유행을 타지 않는 클래식한 어반 스타일의 어린이 헬멧"
pads = "삼천리자전거 어린이 아동 보호대 무릎 팔꿈치 세트 SPS110"
assert rules.convert_product(helmet, "색상:라이트핑크(무광)/2개", terms) == ("삼천리SH700어린이어반헬멧/라이트핑크/2개", None)
assert rules.convert_product(pads, "색상:블루-1개", terms) == ("삼천리SPS110어린이보호대/블루", None)
# 쿠팡식 상품명/선택사항
assert rules.convert_product(pads + ", 블루, one size, 1개", "블루 1개 one size", terms)[0] == "삼천리SPS110어린이보호대/블루"
# 소품은 선택사항 빈칸 (경고 없음), 자전거는 기존 규칙 그대로
assert rules.convert_option("색상:블루-1개", terms, pads) == (None, None)
assert rules.convert_option("색상:블랙, 완전조립", terms, "빅마운틴 2026년형") == ("100%조립요청", None)
assert rules.convert_product("빅마운틴 2026년형", "색상:블랙", terms)[0] == "빅마운틴/블랙(2026)"
assert rules.convert_product("2026 삼천리자전거 시애틀F 26 접이식", "블랙 1개 170cm 완전조립", terms)[0] == "시애틀F26/블랙"

# LLM 템플릿: {color}, {count} 만 허용
assert L.valid_template("삼천리X/{color}{count}") and not L.valid_template("{x}")

# CJ 표기
for v in ("CJ택배", "CJ대한통운", " cj대한통운 "):
    assert F.carrier_kind(v, cfg) == "cj", v
assert F.carrier_kind("경동택배", cfg) == "kd"

# 클레임 행 제외 (중간파일 헤더 구조와 같은 이름만 사용)
wb = Workbook(); ws = wb.active
ws.append(["주문번호", "클레임사유"])
ws.append(["A1", None]); ws.append(["A2", "구매의사 없어짐"]); ws.append(["A3", "  "]); ws.append([None, "x"]); ws.append(["A5", ""])
h = convert.header_map(ws)
assert convert.active_rows(ws, h) == [2, 4, 6]
assert convert.data_rows(ws, h["주문번호"]) == [2, 3, 4, 6]
print("OK")
