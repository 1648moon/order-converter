"""진단 로그: 고객 정보가 남지 않는지, 상품 정보는 남는지 확인. 실행: .venv/bin/python -I tests/test_diag.py"""
import csv
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import diag  # noqa: E402
import discord_notify  # noqa: E402
from openpyxl import Workbook  # noqa: E402

NAME, ADDR, PHONE, ORDER = "홍길동테스트", "서울시 가상구 테스트로 12길 5", "010-1234-5678", "2026111900123456"

d = Path(tempfile.mkdtemp())
# 원본·중간파일: 고객 정보 열 + 상품 열
wb = Workbook(); ws = wb.active
ws.append(["주문번호", "상품명", "선택사항", "수령자", "주소", "전화번호", "단가", "택배사"])
ws.append([ORDER, "시애틀F26", "블랙", NAME, ADDR, PHONE, 250000, "경동택배"])
ws.append([ORDER + "9", "시애틀F26", "블랙", NAME, ADDR, PHONE, 250000, "경동택배"])
src = d / "src.xlsx"; wb.save(src)
run = d / "output" / "2026-11-19_v1"
(run / "검증리포트").mkdir(parents=True)
wb.save(run / "src_변환.xlsx")
(run / "실행요약.txt").write_text(
    "실행 시각: x\n\n== 단계별 결과 ==\n[정상] 변환\n    변환 완료\n"
    f"[경고] 내부보관용\n    경고: 집계표 목록에 없는 상품 '시애틀F26' (받는분 {NAME} {PHONE})\n"
    "[실패] 내부보관용 검증\n    검증 대상 2행 | 불일치 3건\n", encoding="utf-8")
with (run / "검증리포트" / "validation_1.csv").open("w", newline="", encoding="utf-8-sig") as f:
    w = csv.writer(f)
    w.writerow(["분류", "행", "컬럼", "원본(기대)값", "결과값"])
    w.writerow(["집계 합계", "2", "행 상품별 합계", "2", "1"])
    w.writerow(["공통값", "3", "상품명", "시애틀F26/블랙", "시애틀F26"])
    w.writerow(["공통값", "3", "수령자", NAME, "다른이름"])
    w.writerow(["공통값", "3", "주소", ADDR, ADDR + "x"])

rec = diag.build(src, run, 1)
text = json.dumps(rec, ensure_ascii=False)
for secret in (NAME, ADDR, PHONE, ORDER, "다른이름"):
    assert secret not in text, secret                      # 고객 정보는 어디에도 없다
assert "시애틀F26/블랙" in text and "행 상품별 합계" in text  # 상품·집계 정보는 남는다
assert rec["products"] == [["시애틀F26", 2]]
assert [s["status"] for s in rec["stages"]] == ["정상", "경고", "실패"]
vals = {m["column"]: (m["expected"], m["actual"]) for m in rec["mismatches"]}
assert vals["수령자"] == (diag.MASK, diag.MASK) and vals["상품명"] == ("시애틀F26/블랙", "시애틀F26")

# 저장·조회·보관 개수
store = d / "diag"
diag.save(rec, store)
assert diag.reply("", store).startswith("진단 · 2026-11-19_v1")
assert "시애틀F26" in diag.reply("2026-11-19_v1", store)
assert "찾지 못했어요" in diag.reply("nope", store)
assert diag.reply("../../etc", store).endswith("찾지 못했어요.")        # 경로 조작 불가
for i in range(diag.KEEP + 5):
    diag.save({**rec, "run": f"2026-11-{i:02d}_v1"}, store)
assert len(list(store.glob("*.json"))) == diag.KEEP

# 실행 폴더가 없는 크래시: 오류 종류와 위치만 (예외 메시지의 값은 지움)
err = 'Traceback (most recent call last):\n  File "/app/src/convert.py", line 10, in f\nValueError: bad value 홍길동\n'
crash = diag.build(src, None, 1, err)
assert "ValueError" in crash["error"] and "홍길동" not in crash["error"] and "convert.py" in crash["error"]

# 디스코드 명령: '진단' 만 (일반 문장은 에이전트로 넘어간다)
n = discord_notify.Notifier(None, None, None, None)
assert n.reply_for("진단해줘 오늘 뭐가 문제야") is None
print("OK")
