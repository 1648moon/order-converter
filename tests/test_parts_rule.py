"""부품(단가 <= 100,000) 자동 CJ 처리 테스트. 실행: python -I tests/test_parts_rule.py"""
import os
import sys
import tempfile
from pathlib import Path

os.environ["FACTORY_IGNORE_LOCAL"] = "1"
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import rules, convert, factory as F  # noqa: E402
from openpyxl import Workbook, load_workbook  # noqa: E402

terms = rules.load_terms()
assert rules.is_part(100000, terms) and rules.is_part(0, terms) and rules.is_part("12,000원", terms)
assert not rules.is_part(100001, terms) and not rules.is_part(None, terms) and not rules.is_part("", terms)
assert rules.expected_carrier("경동택배", 59000, terms) == "CJ택배"
assert rules.expected_carrier("경동택배", 206000, terms) == "경동택배"
assert F.carrier_kind(terms["parts_rule"]["carrier"], F.load_cfg()) == "cj"

# 변환: 단가 낮은 행만 CJ 로
wb = Workbook(); ws = wb.active
ws.append(["주문번호", "상품명", "선택사항", "수령자", "주소", "단가", "택배사"])
ws.append(["1", "빅마운틴 2026년형", "색상:블랙", "가", "서울시 강남구", 206000, "경동택배"])
ws.append(["2", "삼천리 헬멧", "색상:블루", "나", "서울시 강남구", 100000, "경동택배"])
ws.append(["3", "삼천리 헬멧", "색상:블루", "다", "서울시 강남구", 35000, ""])
d = Path(tempfile.mkdtemp())
wb.save(d / "src.xlsx")
convert.convert(d / "src.xlsx", d / "out.xlsx", terms)
o = load_workbook(d / "out.xlsx").active
h = convert.header_map(o)
assert [o.cell(r, h["택배사"]).value for r in (2, 3, 4)] == ["경동택배", "CJ택배", "CJ택배"]
print("OK")

# 색상: 조립여부 뒤에 사이즈(24인치)가 와도 색상으로 잡지 않는다
assert rules.extract_color("레드 1개 160cm 미조립박스 24인치", terms) == "레드"
assert rules.convert_product("[삼천리자전거/하운드] 2026 시애틀MT 24 기어 21단 주니어, 레드, 1개, 160cm, 24인치",
                             "레드 1개 160cm 미조립박스 24인치", terms)[0] == "시애틀MT24/레드"
assert rules.extract_color("완전조립 블랙", terms) == "블랙"
print("OK color")
