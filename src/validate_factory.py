"""중간파일과 공장 전달용 파일의 공통 정보 동일성 검증.

사용법:
    .venv/bin/python src/validate_factory.py output/주문원본1_변환.xlsx output/주문원본1_공장.xlsx

검증 항목
  1. 헤더가 설정(config/factory.yaml)과 정확히 같은지
  2. 행 수, 수량 합계
  3. 행별 공통 정보: 받는고객/우편번호/주소/전화번호/핸드폰번호/수량/상품명/비고가 중간파일과 동일
  4. 규칙 값: 택배운임, 결제조건, 상품옵션이 규칙 재적용 결과와 일치
  5. CJ 주문(택배사 CJ택배)은 경동 공장용에서 빠지고 CJ 공장 파일에 들어갔는지, CJ 택배운임은 고정값인지
  6. 서식/경고: 템플릿의 열 너비·행 높이·헤더 서식 유지, 운임표에 없는 상품의 택배운임 셀에만 경고색
상세(값 포함)는 reports/ CSV에만 기록하고 화면에는 건수·위치만 출력한다.
종료코드: 0 통과 / 1 불일치
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from openpyxl import load_workbook

sys.path.insert(0, str(Path(__file__).resolve().parent))
import factory as F  # noqa: E402
import xlsxkit as xk  # noqa: E402
from convert import KEY, data_rows  # noqa: E402
from validate import norm, write_report  # noqa: E402


def check_file(a, h: dict, extra_col: int, ra: list[int], out: Path, cfg: dict, cj: bool = False) -> list[tuple]:
    """공장용 파일 1개를 검증. ra = 이 파일에 들어가야 하는 중간파일 행들."""
    tag = " (CJ)" if cj else ""
    b = load_workbook(out).active
    diffs: list[tuple] = []

    n = len(cfg["headers"])
    heads = [b.cell(1, c).value for c in range(1, n + 1)]
    extra_heads = [b.cell(1, c).value for c in range(n + 1, b.max_column + 1) if b.cell(1, c).value not in (None, "")]
    if heads != cfg["headers"] or extra_heads:
        return [("헤더" + tag, 1, "", cfg["headers"], heads)]
    hb = {name: i + 1 for i, name in enumerate(heads)}

    rb = [r for r in range(2, b.max_row + 1)
          if any(b.cell(r, c).value not in (None, "") for c in range(1, b.max_column + 1))]
    if len(ra) != len(rb):
        return [("행수" + tag, "", "", len(ra), len(rb))]

    fixed_fee = cfg["carriers"]["cj_fee"] if cj else None
    for r1, r2 in zip(ra, rb):
        g = lambda name: a.cell(r1, h[name]).value  # noqa: E731
        got = lambda name: b.cell(r2, hb[name]).value  # noqa: E731
        expected = {
            "받는고객": a.cell(r1, extra_col).value,
            "우편번호": F.zip_text(g("우편번호")),
            "받는고객주소": F._s(g("주소")) or None,
            "전화번호": g("수령자전화번호"),
            "핸드폰번호": g("수령자휴대전화"),
            "수량": F.qty(g("수량")),
            "상품명": g("상품명"),
            "비고": g("배송메모"),
            "택배운임": fixed_fee if cj else F.shipping_fee(g("상품명"), g("선택사항"), cfg),
            "결제조건": cfg["payment_term"],
            "상품옵션": F.product_option(g("선택사항"), g("추가구성"), cfg),
        }
        for name, exp in expected.items():
            v = got(name)
            if name == "우편번호":          # 숫자/문자 표기 차이는 같은 값으로 취급
                v = F.zip_text(v)
            if norm(exp) != norm(v):
                diffs.append(("불일치" + tag, r2, name, exp, v))

    # 경동: 운임표에 없는 상품은 택배운임 셀에 경고색, 그 외에는 없어야 함 / CJ: 고정운임이라 경고색 없음
    fee_col = hb["택배운임"]
    for r1, r2 in zip(ra, rb):
        ok = True if cj else F.shipping_fee_info(a.cell(r1, h["상품명"]).value, a.cell(r1, h["선택사항"]).value, cfg)[1]
        if xk.is_warning(b.cell(r2, fee_col), cfg["warning"]) == ok:
            diffs.append(("경고표시" + tag, r2, "택배운임", "경고색 없음" if ok else "경고색", "경고색" if ok else "경고색 없음"))
    tws = load_workbook(xk.ROOT / cfg["template"]).active
    diffs += [(c + tag, *rest) for c, *rest in xk.template_diffs(b, tws, n)]

    qa = sum(F.qty(a.cell(r, h["수량"]).value) or 0 for r in ra)
    qb = sum(b.cell(r, hb["수량"]).value or 0 for r in rb)
    if qa != qb:
        diffs.append(("수량합계" + tag, "", "수량", qa, qb))
    return diffs


def validate(src: Path, out: Path, cfg: dict) -> tuple[list[tuple], int, dict]:
    a = load_workbook(src).active
    h, extra_col = F.locate(a)
    all_rows = data_rows(a, h[KEY])
    kd, cj, _unknown = F.split_rows(a, h, all_rows, cfg)

    diffs = check_file(a, h, extra_col, kd, out, cfg)
    cjp = F.cj_path(out, cfg)
    if cj:
        if cjp.exists():
            diffs += check_file(a, h, extra_col, cj, cjp, cfg, cj=True)
        else:
            diffs.append(("CJ파일", "", cjp.name, f"CJ 주문 {len(cj)}건 -> CJ 파일 필요", "파일 없음"))
    elif cjp.exists():
        diffs.append(("CJ파일", "", cjp.name, "CJ 주문 없음", "이전 CJ 파일이 남아 있음"))
    return diffs, len(all_rows), {"kd": len(kd), "cj": len(cj)}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("src", type=Path, help="중간파일")
    p.add_argument("out", type=Path, help="공장 전달용 파일")
    p.add_argument("--config", type=Path, default=F.DEFAULT_CFG)
    a = p.parse_args()
    for f in (a.src, a.out):
        if not f.exists():
            print(f"파일 없음: {f}", file=sys.stderr)
            return 1
    diffs, n, split = validate(a.src, a.out, F.load_cfg(a.config))
    print(f"검증 대상 {n}행 (경동 {split['kd']} / CJ {split['cj']}) | 불일치 {len(diffs)}건")
    for cat, r, col, *_ in diffs:
        print(f"  - [{cat}] {r}행 {col}")
    if diffs:
        print(f"상세(값 포함): {write_report(diffs)}")
    print("결과:", "통과" if not diffs else "실패")
    return 1 if diffs else 0


if __name__ == "__main__":
    sys.exit(main())
