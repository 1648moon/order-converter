"""상품목록 엑셀의 상품명 -> 내부보관용 오른쪽 표(storage.yaml product_list)의 축약 자전거명 매칭 점검.

실행: .venv/bin/python -I tests/test_bike_match.py [상품목록.xlsx]
기본 입력: input/상품목록(20261110).xlsx (없으면 건너뜀). 규칙은 config/terms.yaml.
색상은 상품명에 없으므로 임의 선택사항("색상: 블랙")으로 채워 모델 부분(색상 앞/뒤 고정부)만 비교한다.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import openpyxl, rules  # noqa: E402

# 이미 축약형으로 적혀 있는 값 (변환 대상 아님)
ALREADY = re.compile(r"^(시애틀\S*|빅마운틴|엑스퍼트|부스터24)(/|$)")
NEW_MODELS = {"첼로부스터24"}   # 내부보관용 표에 아직 없지만 표기를 정해 둔 모델


def models(bikes):
    """축약명에서 모델 부분(첫 '/' 앞)과 {색상 앞 숫자(엑스퍼트 사이즈)} 제거한 형태."""
    return {b.split("/")[0] for b in bikes}


def main(path):
    terms = rules.load_terms(map_path=Path("/nonexistent.yaml"))
    bikes = terms["_bikes"]
    mset = models(bikes)

    names = [str(r[0]).strip() for r in openpyxl.load_workbook(path).active.iter_rows(min_row=2, values_only=True) if r[0]]
    ok, already, warn, nobike = [], [], [], []
    for n in names:
        if ALREADY.match(n):
            already.append(n); continue
        out, w = rules.convert_product(n, "색상: 블랙", terms)
        if w is None and out != n:
            if "삼천리SH700" in out or "삼천리SPS110" in out:   # 소품 규칙
                nobike.append((n, out)); continue
            model = out.split("/")[0]
            (ok if model in mset or model in NEW_MODELS or any(out.startswith(m) for m in mset) else warn).append((n, out, "모델이 product_list 에 없음"))
        elif w and w != "변환 표에 없는 상품":
            warn.append((n, out, w))
        else:
            nobike.append((n, "-"))
    # 자전거로 보이는데 규칙이 못 잡은 것 점검
    miss = [(n, o) for n, o in nobike if o == "-" and re.search(r"자전거|MTB", n) and not re.search(
        r"헬멧|안전모|보호대|라이트|전조등|후미등|자물쇠|번호키|락|미러|거울|펌프|오일|방청|물통|속도계|홀더|가방|테잎|테이프|스카프|패드|속바지|고글|보호장비", n)]

    print(f"전체 {len(names)}개 | 축약 변환 성공 {len(ok)} | 이미 축약형 {already.__len__()} | 경고 {len(warn)} | 용품/기타 {len(nobike) - len(miss)} | 자전거인데 미매칭 {len(miss)}")
    got = {}
    for n, o, _ in ok:
        got.setdefault(o, []).append(n)
    print("\n[변환 결과별 건수]")
    for o in sorted(got):
        print(f"  {o:28s} {len(got[o])}건")
    print("\n[product_list 에 있는데 상품목록에서 안 잡힌 모델]")
    seen = {o.split("/")[0] for o in got}
    for m in sorted(mset - seen):
        print("  ", m)
    print("\n[경고 - 사람이 확인 필요]")
    for n, o, w in warn:
        print(f"  {w}: {n}")
    print("\n[자전거로 보이는데 규칙 미매칭 - 신규 모델 후보]")
    for n, _ in miss:
        print("  ", n)
    return len(ok), warn, miss


if __name__ == "__main__":
    p = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/Users/moon/Documents/jimini/input/상품목록(20261110).xlsx")
    if not p.exists():
        print("상품목록 파일이 없어 건너뜀:", p)
    else:
        main(p)
