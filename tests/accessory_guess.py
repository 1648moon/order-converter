"""상품목록 용품(헬멧·보호대·라이트·자물쇠 등) 상품명 -> 축약형 '추측'을 엑셀 우측에 기입.

예시 패턴(상품목록_부품축약예시): 삼천리 + 모델코드 + 대상(어린이/성인) + 품목 + '/'  (뒤의 '/' 는 색상 자리)
  - 캐릭터명(캐치티니핑·겨울왕국 등)과 코드 끝의 'L'(캐릭터판)은 뺀다: SH700L -> SH700, SPS150L -> SPS150
  - 브랜드는 상품명 그대로(삼천리 / 디스트로 / TONYON)
추측이므로 B열 값은 사람이 확인해야 한다. C열 비고에 근거와 확신도(코드 없음 등)를 적는다.

실행: .venv/bin/python -I tests/accessory_guess.py <입력.xlsx> --out <결과.xlsx>
입력: 이미 자전거 축약형이 B열에 적힌 파일(tests/test_bike_match.py --out 결과). B열이 비어 있는 행만 채운다.
"""
import re, sys
from pathlib import Path

import openpyxl

SIZE = re.compile(r"번호키(?:\s*자물쇠)?\s*(소|중|대)(?=\s|$)")


def guess(name):
    """(축약형, 비고). 못 맞추면 ('', '미분류')."""
    n = name.upper()
    p = re.sub(r"\s+", "", n)
    has = lambda *ks: any(k.upper().replace(" ", "") in p for k in ks)

    # 헬멧
    if has("SH700"): return "삼천리SH700어린이어반헬멧/", "예시 패턴"
    if has("SH310"): return "삼천리SH310어린이헬멧/", ""
    if has("SH110"): return "삼천리SH110아동어반헬멧/", ""
    if has("AH910SR"): return "삼천리AH910SR성인어반후미등헬멧/", ""
    if has("AH710SR"): return "삼천리AH710SR성인인몰드어반후미등헬멧/", ""
    if has("AH340"):
        return ("삼천리AH340주니어헬멧/", "") if has("주니어") else ("삼천리AH340성인헬멧/", "L사이즈 등은 색상/옵션 쪽일 것으로 추정")
    if re.search(r"DH-?470", p): return "디스트로DH470성인헬멧/", "브랜드 디스트로"
    if re.search(r"DH-?468", p): return "디스트로DH468미러고글헬멧/", "브랜드 디스트로"
    if has("아이시스"): return "아이시스K5에일린2주니어헬멧/", "확신 낮음(코드 없는 타사 제품)"
    # 보호대
    if has("SPS110"): return "삼천리SPS110어린이보호대/", "예시 패턴"
    if has("SPS150"): return "삼천리SPS150어린이보호대/", "L 제외(예시 SH700L 규칙 준용)"
    if has("보호대", "보호장비") and has("티니핑", "겨울왕국", "프린세스"):
        return "삼천리SPS150어린이보호대/", "코드 없음 - 같은 캐릭터 보호대(SPS150L)로 추측"
    # 라이트
    if has("AF015"): return "삼천리AF015올러스전조등/", ""
    if has("AF500"): return "삼천리AF500충전식전조등/", ""
    if has("AF450"): return "삼천리AF450충전식전조등/", ""
    if has("AT500"): return "삼천리AT500충전식후미등/", ""
    if has("후미등") and has("디스트로"): return "디스트로USB충전후미등/", "코드 없음 - 확신 낮음"
    # 자물쇠
    if has("SL360"): return "삼천리SL360사슬형번호키자물쇠/", ""
    if has("SL110C"): return "삼천리SL110C와이어컬러자물쇠중/", ""
    if has("7관절"): return "7관절락자물쇠/", "브랜드·코드 없음 - 확신 낮음"
    if has("TONYON"): return "TONYONTY217마디커버자물쇠/", "확신 낮음"
    if has("SL160C"):
        m = SIZE.search(name)
        return (f"삼천리SL160C컬러번호키{m.group(1)}/", "") if m else ("삼천리SL160C컬러번호키/", "크기(소/중) 못 찾음 - 확인 필요")
    if has("SL160") or (has("번호키") and has("자물쇠")):
        m = SIZE.search(name)
        note = "" if has("SL160") else "코드 없음 - SL160으로 추측"
        return (f"삼천리SL160번호키자물쇠{m.group(1)}/", note) if m else ("삼천리SL160번호키자물쇠/", "크기(중/대) 못 찾음 - 확인 필요")
    # 기타 용품
    if has("SMR150"): return "삼천리SMR150핸들바엔드미러/", ""
    if has("AC300W"): return "삼천리AC300W무선속도계/", ""
    if has("AB570S"): return "삼천리AB570S탑튜브스마트폰홀더/", ""
    if has("AB550S"): return "삼천리AB550S프레임스마트폰홀더/", ""
    if has("SP110"): return "삼천리SP110알로이펌프소/", ""
    if has("SRI110"): return "삼천리SRI110윤활방청제/", ""
    if has("AO150"): return "삼천리AO150자전거오일/", "'2개 한세트'는 수량으로 처리될 것으로 추정"
    if has("ABC360"): return "삼천리ABC360물통걸이/", ""
    if has("ABT220"): return "삼천리ABT220바테이프/", ""
    if has("ABT110"): return "삼천리ABT110픽시바테이프/", ""
    if has("바테이프", "바테잎"): return "삼천리바테이프/", "코드 없음 - 확신 낮음"
    if has("AM310E"): return "삼천리AM310E멀티프/", ""
    if has("이너패드", "속바지"): return "이너패드팬츠/", "브랜드·코드 없음 - 확신 낮음"
    return "", "미분류"


def main(src, out):
    wb = openpyxl.load_workbook(src)
    ws = wb.active
    stats = {}
    unknown = []
    for r in range(2, ws.max_row + 1):
        name = ws.cell(r, 1).value
        if not name or ws.cell(r, 2).value:
            continue
        if "확인 필요" in str(ws.cell(r, 3).value or ""):   # 자전거 확인 대기 행은 건드리지 않음
            continue
        abbr, note = guess(str(name))
        ws.cell(r, 2, abbr or None)
        ws.cell(r, 3, ("추측: " + note if note else "추측") if abbr else note)
        if abbr:
            stats.setdefault(abbr, []).append(str(name))
        else:
            unknown.append(str(name))
    wb.save(out)
    print(f"축약형 {len(stats)}종 / 상품명 {sum(map(len, stats.values()))}개 기입, 미분류 {len(unknown)}개")
    for k in sorted(stats):
        print(f"  {k:36s} {len(stats[k])}건")
    for n in unknown:
        print("  미분류:", n)
    print("저장:", out)


if __name__ == "__main__":
    a = list(sys.argv[1:])
    i = a.index("--out")
    main(Path(a[0]), Path(a[i + 1]))
