"""텔레그램 봇의 접속과 무관한 부분 테스트.
실행: <venv>/bin/python -I tests/test_telegram_bot.py [샘플.xlsx]   (샘플을 주면 변환 파이프라인까지 확인)
"""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import telegram_bot as T  # noqa: E402

assert T.parse_ids("111, -222\n333,abc") == {111, -222, 333}
assert T.parse_ids("") == set()
assert T.safe_name("주문 원본(1).xlsx") == "주문_원본_1_.xlsx"
with tempfile.TemporaryDirectory() as d:
    env = Path(d) / ".env"
    env.write_text("# c\nTELEGRAM_BOT_TOKEN='abc:def'\nTELEGRAM_ALLOWED_CHAT_IDS=1,2\n", encoding="utf-8")
    e = T.load_env(env)
    assert e["TELEGRAM_BOT_TOKEN"] == "abc:def" and T.parse_ids(e["TELEGRAM_ALLOWED_CHAT_IDS"]) == {1, 2}
    assert T.load_env(Path(d) / "none") == {}
    out = Path(d) / "o"
    out.mkdir()
    before = T.snapshot_xlsx(out)
    (out / "a.xlsx").touch()
    (out / "x_변환.xlsx").touch()
    assert [p.name for p in T.new_xlsx(before, out)] == ["a.xlsx"]
if len(sys.argv) > 1:
    with tempfile.TemporaryDirectory() as d:
        code, summary, files = T.run_pipeline(Path(sys.argv[1]).resolve(), Path(d))
        print(summary)
        print([f.name for f in files])
        assert code in (0, 2) and len(files) == 3, (code, files)
        code, _, files = T.run_pipeline(Path(d) / "없음.xlsx", Path(d))
        assert code == 1 and files == []
print("OK")
