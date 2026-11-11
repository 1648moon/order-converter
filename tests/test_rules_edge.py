"""연식 없는 빅마운틴 / 엑스퍼트 사이즈+색상 / 추가상품 그대로 넘기기.
실행: .venv/bin/python -I tests/test_rules_edge.py
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import rules  # noqa: E402

t = rules.load_terms()

# 1) 추가상품: 상품명·선택사항 모두 원본 그대로, 경고 없음
assert rules.convert_product("추가상품", "┗삼천리흙받이", t) == ("추가상품", None)
assert rules.convert_option("┗삼천리흙받이", t, "추가상품") == ("┗삼천리흙받이", None)

# 2) 연식 없는 빅마운틴: 공란 + 괄호 생략 / 연식 있으면 기존대로
v, w = rules.convert_product("[삼천리자전거] 빅마운틴 26 생활형 MTB 21단", "블랙 1개 170cm 완전조립", t)
assert (v, w) == ("빅마운틴/블랙(2026)", None), (v, w)      # 연식 없으면 2026
v, w = rules.convert_product("2026년형 삼천리자전거 컴포트 MTB 빅마운틴 21단 26", "색상:다크실버", t)
assert (v, w) == ("빅마운틴/다크실버(2026)", None), (v, w)

v, w = rules.convert_product("2026년형 삼천리자전거 컴포트 MTB 빅마운틴 21단 26, 다크실버/미조립, 1개, 170cm, 26",
                             "다크실버/미조립 1개 170cm", t)
assert (v, w) == ("빅마운틴/다크실버(2026)", None), (v, w)       # '색상/미조립' 형식에서 색상 추출

# 3) 엑스퍼트: 주문의 '440화이트' -> 집계표 '엑스퍼트/440블랙화이트'
for name in ("[미조립/박스] 삼천리자전거 700C 엑스퍼트 알루미늄 프레임 학생 출퇴근 입문용 픽시, 1개, 164cm, 440화이트",
             "[프리기어/완전조립] 삼천리자전거 700C 엑스퍼트 알루미늄 프레임 학생 출퇴근 입문용 픽시, 164cm, 1개, 440화이트"):
    assert rules.convert_product(name, "440화이트 1개 164cm 700c", t) == ("엑스퍼트/440블랙화이트", None), name
assert rules.convert_product("엑스퍼트 픽시 510네온그린", "", t)[0] == "엑스퍼트/510블랙네온그린"
assert rules.convert_product("엑스퍼트 픽시 440블랙화이트", "", t)[0] == "엑스퍼트/440블랙화이트"   # 이미 블랙이 적혀 있어도 동일
assert rules.convert_product("엑스퍼트 픽시", "", t) == ("엑스퍼트", None)    # 사이즈·색상이 상품명에 없으면 기존 기본 규칙

# 4) 상품명에 '완전조립'이 있으면 선택사항에 조립 표기가 없어도 완전조립(100%조립요청)
fx = "[프리기어/완전조립] 삼천리자전거 700C 엑스퍼트 알루미늄 프레임 학생 출퇴근 입문용 픽시, 164cm, 1개, 440화이트"
assert rules.convert_option("440화이트 1개 164cm 700c", t, fx) == ("100%조립요청", None)
assert rules.convert_option("440화이트 1개 164cm 700c", t, "[미조립/박스] 엑스퍼트 440화이트") == (None, None)   # 상품명의 미조립도 인정(빈칸)
assert rules.convert_option("블랙 1개", t, "시애틀F 26")[1] is not None                                    # 조립 표기가 어디에도 없으면 경고
assert rules.convert_option("다크실버/미조립 1개", t, "빅마운틴 완전조립 어쩌고") == (None, None)       # 선택사항의 미조립이 우선

assert "엑스퍼트/440블랙화이트" in t["_bikes"]       # 집계표 목록과 이름이 실제로 일치

print("OK")
