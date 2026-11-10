"""상품목록 엑셀의 상품명 -> 내부보관용 오른쪽 표(storage.yaml product_list)의 축약 자전거명 매칭 점검.

실행: .venv/bin/python -I tests/test_bike_match.py [상품목록.xlsx] [--out 결과.xlsx]
- 상품명에는 색상이 없으므로 '모델 단위 축약형'(색상 자리 '/{color}' 제거)을 구한다. 예) 시애틀MT24, 빅마운틴(2026), 엑스퍼트
- 여러 상품명이 같은 축약형 하나에 매칭되는 다대일이 정상이다.
- 용품(헬멧·자물쇠 등)은 내부보관용 대상이 아니므로 빈칸.
- --out 을 주면 원본 엑셀 우측(B열 축약형, C열 비고)에 결과를 적어 새 파일로 저장한다. 원본은 건드리지 않는다.
규칙은 config/terms.yaml.
"""
import re, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
import openpyxl, rules  # noqa: E402

DEFAULT_IN = Path("/Users/moon/Documents/jimini/input/상품목록(20261110).xlsx")
SENT = "§"   # convert_product 에 넘기는 가짜 색상. 결과에서 '/§' 를 지우면 모델 단위 축약형
NEW_MODELS = {"첼로부스터24"}   # 내부보관용 표에 아직 없지만 표기를 정해 둔 모델
# 이미 축약형으로 적힌 값: '시애틀MT26/', '엑스퍼트/미조립박스', '빅마운틴/(2025)', '부스터24'
ALREADY = re.compile(r"^(?:시애틀\S*?|빅마운틴|엑스퍼트|부스터24)(?:/|$)")
SHORT = re.compile(r"^([^/]+)/.*?(\(\d{4}\))?$")


def model_key(name, terms):
    """(축약형 또는 '', 비고 또는 ''). 용품·미해당은 ('', '')."""
    n = name.strip()
    if ALREADY.match(n):
        if n == "부스터24":
            return "첼로부스터24", "이미 축약형"
        m = SHORT.match(n)
        key = m.group(1) if m else n
        if key == "빅마운틴" and m and m.group(2):   # 연식이 모델명의 일부인 건 빅마운틴뿐
            key += m.group(2)
        note = "이미 축약형"
        if key in ("시애틀라인", "시애틀MT", "시애틀키즈", "시애틀클래식"):
            note += " - 사이즈 없음, 확인 필요"
        elif key == "빅마운틴":
            note += " - 연식 없음, 확인 필요"
        return key, note
    rule = rules.find_rule(n, terms)
    if rule and rule.get("blank_option"):   # 용품(헬멧·자물쇠 등) 규칙은 내부보관용 대상이 아님
        return "", ""
    out, w = rules.convert_product(n, f"색상: {SENT}", terms)
    if w is None and out != n:
        return out.replace(f"/{SENT}", ""), ""
    if w and w != "변환 표에 없는 상품":
        return "", f"확인 필요: {w}"
    return "", ""


def main(path, out=None):
    terms = rules.load_terms(map_path=Path("/nonexistent.yaml"))
    # 표 쪽 모델 단위 키: '빅마운틴/블랙(2026)' -> '빅마운틴(2026)', '엑스퍼트/380블랙화이트' -> '엑스퍼트'
    table_keys = {re.sub(r"/[^()]*", "", b) for b in terms["_bikes"]}
    wb = openpyxl.load_workbook(path)
    ws = wb.active
    rows = []
    for r in range(2, ws.max_row + 1):
        v = ws.cell(r, 1).value
        if not v or not str(v).strip():
            continue
        key, note = model_key(str(v), terms)
        if key and key not in table_keys and key not in NEW_MODELS:
            note = (note + " " if note else "") + "우측 표에 없는 모델"
        rows.append((r, str(v).strip(), key, note))
    bikes = [x for x in rows if x[2]]
    groups = {}
    for _, n, k, _ in bikes:
        groups.setdefault(k, []).append(n)
    print(f"상품명 {len(rows)}개 | 자전거 축약 {len(bikes)}개 -> 축약형 {len(groups)}종 | 용품/기타(빈칸) {len(rows) - len(bikes)}개")
    print("\n[축약형별 상품명 수 (다대일)]")
    for k in sorted(groups):
        flag = "" if (k in table_keys or k in NEW_MODELS) else "   <- 우측 표에 없음"
        print(f"  {k:20s} {len(groups[k])}건{flag}")
    print("\n[우측 표에는 있는데 상품목록에 없는 모델]")
    print("  ", sorted(table_keys - set(groups)))
    print("\n[확인 필요]")
    for _, n, k, note in rows:
        if "확인 필요" in note or "표에 없는" in note:
            print(f"  {note}: {n} -> {k or '(빈칸)'}")
    if out:
        ws.cell(1, 2, "축약형"); ws.cell(1, 3, "비고")
        for r, _, k, note in rows:
            ws.cell(r, 2, k or None); ws.cell(r, 3, note or None)
        ws.column_dimensions["B"].width = 22; ws.column_dimensions["C"].width = 40
        wb.save(out)
        print("\n저장:", out)
    return rows


if __name__ == "__main__":
    args = list(sys.argv[1:])
    out = None
    if "--out" in args:
        i = args.index("--out"); out = Path(args[i + 1]); del args[i:i + 2]
    p = Path(args[0]) if args else DEFAULT_IN
    if not p.exists():
        print("상품목록 파일이 없어 건너뜀:", p)
    else:
        main(p, out)
