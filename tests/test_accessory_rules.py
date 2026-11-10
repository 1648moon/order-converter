"""자전거·용품 축약 규칙(terms.yaml)과 '색상 없으면 /색상 생략' 동작 테스트.
실행: .venv/bin/python -I tests/test_accessory_rules.py
input/상품목록(20261110)_전체축약.xlsx 가 있으면 B열(추측값)과 규칙 결과가 같은지도 확인한다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import rules  # noqa: E402

T = rules.load_terms(map_path=Path("/nonexistent.yaml"))
conv = lambda n, o="": rules.convert_product(n, o, T)

# 색상이 있으면 '/색상', 없으면 생략
assert conv("삼천리자전거 번호키 사슬형 자물쇠 SL360 쇠사슬", "") == ("삼천리SL360사슬형번호키자물쇠", None)
assert conv("2026 삼천리자전거 시애틀 MT 24 21단", "색상:블랙") == ("시애틀MT24/블랙", None)
assert conv("2026 삼천리자전거 빅마운틴 21단 26", "") == ("빅마운틴(2026)", None)           # 빅마운틴/(2026) 이 아님
assert conv("2026 삼천리자전거 빅마운틴 21단 26", "색상:블랙") == ("빅마운틴/블랙(2026)", None)
# 소품: 색상/수량. 색상 없이 수량만 있으면 '/2개'
assert conv("삼천리자전거 어반 어린이용 헬멧 SH700", "색상:라이트핑크(무광)/2개") == ("삼천리SH700어린이어반헬멧/라이트핑크/2개", None)
assert conv("삼천리자전거 어린이 아동 보호대 무릎 팔꿈치 세트 SPS110", "블루 1개") == ("삼천리SPS110어린이보호대/블루", None)
assert conv("삼천리자전거 오일 AO150 40ml", "2개")[0] == "삼천리AO150자전거오일/2개"
# 번호키: SL160C 가 SL160 보다 먼저, 소/중/대는 상품명에서
assert conv("삼천리자전거 SL160C 삼천리 컬러 번호키 소 사이즈")[0] == "삼천리SL160C컬러번호키소"
assert conv("삼천리자전거 번호키 자물쇠 중 M 사이즈 SL160")[0] == "삼천리SL160번호키자물쇠중"
assert conv("번호키 대 자물쇠 자전거 삼천리자전거")[0] == "삼천리SL160번호키자물쇠대"
assert conv("삼천리자전거 번호키 SL160")[1] is not None          # 크기를 못 읽으면 경고
# 시애틀라인 은 '클래식' 이 같이 있어도 라인으로
assert conv("삼천리자전거 하운드 클래식 자전거 시애틀 라인 24 150cm", "색상:민트")[0] == "시애틀라인24/민트"
# 캐릭터 보호대(SPS150L), 코드 없는 캐릭터 보호대
assert conv("삼천리자전거 SPS150L 겨울왕국 보호대 아동용")[0] == "삼천리SPS150어린이보호대"
assert conv("삼천리자전거 캐치티니핑 하츄핑 어린이 보호장비 무릎 팔꿈치 보호대 세트")[0] == "삼천리SPS150어린이보호대"

xlsx = Path("/Users/moon/Documents/jimini/input/상품목록(20261110)_전체축약.xlsx")
if xlsx.exists():
    import openpyxl
    ws = openpyxl.load_workbook(xlsx).active
    bad = []
    for r in range(2, ws.max_row + 1):
        name, want = ws.cell(r, 1).value, ws.cell(r, 2).value
        if not name or not want or "이미 축약형" in str(ws.cell(r, 3).value or ""):
            continue
        got, w = conv(str(name), f"색상: §")
        got = got.replace("/§", "")
        if w or got != want.rstrip("/"):
            bad.append((name, want, got, w))
    for b in bad[:10]:
        print("불일치:", b)
    assert not bad, f"엑셀 추측값과 규칙 결과가 다른 행 {len(bad)}개"
print("OK")
