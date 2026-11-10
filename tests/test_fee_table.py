"""config/factory.yaml 의 택배운임 규칙이 input/경동택배 운임표.xlsx 와 일치하는지 확인.
실행: .venv/bin/python -I tests/test_fee_table.py
"""
import sys
from pathlib import Path

from openpyxl import load_workbook

root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(root / "src"))
import factory as F  # noqa: E402

cfg = F.load_cfg()
A = cfg["assembled_marker"]
ws = load_workbook(root / "input" / "경동택배 운임표.xlsx").active

state, checked = None, 0
for r in range(2, ws.max_row + 1):
    a, model, fee = (ws.cell(r, c).value for c in (1, 2, 3))
    state = a or state
    if state == "완전조립":
        for name in ("빅마운틴/블랙(2026)", "시애틀F26/블랙", "엑스퍼트/380블랙화이트"):   # 모델 무관
            assert F.shipping_fee_info(name, A, cfg) == (fee, True), (name, fee)
        checked += 1
    else:
        product = f"{model}/테스트색"
        got = F.shipping_fee_info(product, None, cfg)
        assert got == (fee, True), (model, fee, got)
        got = F.shipping_fee_info(product, A, cfg)      # 같은 모델도 조립이면 25000
        assert got[0] == 25000, (model, got)
        checked += 1

# 표에 없는 미조립 모델은 기본운임 + 일치 안 함 표시
assert F.shipping_fee_info("신모델/레드", None, cfg) == (13000, False)
# 조립은 모델이 달라도 항상 25000
assert F.shipping_fee_info("신모델/레드", A, cfg) == (25000, True)
print(f"OK ({checked}개 행 확인)")
