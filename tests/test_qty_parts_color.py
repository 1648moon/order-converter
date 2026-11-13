"""수량 행 복사(변환 단계) / 택배용 부품 제외 / 색상 '블랙/레드' -> '블랙레드' 테스트."""
import sys, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
from openpyxl import Workbook, load_workbook
import rules, convert, courier, validate

terms = rules.load_terms()
# 3) 색상
assert rules.extract_color("색상:블랙/레드", terms) == "블랙레드"
assert rules.extract_color("색상:블랙/레드, 완전조립", terms) == "블랙레드"
assert rules.extract_color("색상:블랙", terms) == "블랙"
assert rules.extract_color("색상:라이트핑크(무광)/2개", terms) == "라이트핑크"
assert rules.convert_product("2026 삼천리자전거 시애틀 MT 24 21단", "색상:블랙/레드", terms)[0] == "시애틀MT24/블랙레드"

# 1)+2) 변환/택배
d = Path(tempfile.mkdtemp())
wb = Workbook(); ws = wb.active
heads = ["주문번호", "상품명", "선택사항", "수량", "수령자", "주소", "택배사", "단가", "추가구성", "우편번호",
         "수령자전화번호", "수령자휴대전화", "배송메모", "클레임사유"]
ws.append(heads)
bike = "2026 삼천리자전거 시애틀 MT 24 21단"
helmet = "삼천리자전거 어반 어린이용 헬멧 SH700"
ws.append(["A1", bike, "색상:블랙/레드", 3, "홍길동", "서울시 강남구", "경동", 200000, None, 12345, "010", "010", None, None])
ws.append(["A2", helmet, "색상:라이트핑크(무광)/2개", 2, "김철수", "부산시 중구", "CJ", 20000, None, 12345, "010", "010", None, None])
ws.append(["A3", bike, "색상:블랙", 1, "이영희", "대구시 동구", "경동", 200000, None, 12345, "010", "010", None, None])
src = d / "src.xlsx"; wb.save(src)
mid = d / "mid.xlsx"
convert.convert(src, mid, terms)
m = load_workbook(mid).active
assert [m.cell(r, 1).value for r in range(2, m.max_row + 1)] == ["A1"] * 3 + ["A2"] * 2 + ["A3"]
assert all(m.cell(r, 4).value == 1 for r in range(2, m.max_row + 1))   # 수량 열(수령자 앞 삽입 전: 4번째)
assert validate.validate(src, mid, terms) == [], validate.validate(src, mid, terms)
out = d / "courier.xlsx"
n, _, _ = courier.build(mid, out, courier.load_cfg())
assert n == 4, n   # 자전거 3 + 1, 부품 제외
print("ok")
