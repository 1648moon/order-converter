"""웹 업로드 + 알림 테스트. 실행: .venv/bin/python -I tests/test_web_notify.py
실제 변환은 가짜 runner 로 대체(개인정보 파일 불필요)."""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import discord_notify  # noqa: E402
import runinfo  # noqa: E402
import webapp  # noqa: E402


def make_run(out: Path, name: str, overall: str, stages, files=()):
    d = out / name
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_bytes(b"x")
    lines = [f"전체 결과: {overall}", "", "== 단계별 결과 =="]
    for status, st in stages:
        lines += [f"[{status}] {st}", "    경고: 홍길동 010-1234-5678 행 3"]     # 원문(개인정보 가정)은 알림에 새면 안 됨
    (d / "실행요약.txt").write_text("\n".join(lines), encoding="utf-8")


with tempfile.TemporaryDirectory() as t:
    root = Path(t)
    out = root / "output"
    make_run(out, "2026-11-10_v1", "정상", [("정상", "변환")], ["a.xlsx", "b.xlsx"])
    make_run(out, "2026-11-10_v2", "경고", [("정상", "변환"), ("경고", "공장용")], ["a.xlsx"])
    make_run(out, "2026-11-10_v3", "실패", [("실패", "변환 검증")], [])

    s = {r.name: r for r in runinfo.recent_runs(out)}
    assert runinfo.notify_text(s["2026-11-10_v1"]) == "✅ 변환 완료 · 2026-11-10_v1 · 파일 2개"
    assert "경고 단계 1개" in runinfo.notify_text(s["2026-11-10_v2"])
    assert runinfo.notify_text(s["2026-11-10_v3"]) == "❌ 변환 실패 · 2026-11-10_v3 · 실패 단계: 변환 검증"
    for r in s.values():                                   # 개인정보가 알림에 섞이지 않는다
        assert "홍길동" not in runinfo.notify_text(r) and "010" not in runinfo.notify_text(r)
    assert runinfo.recent_runs(out)[0].name == "2026-11-10_v3"      # 최신순

    bot = discord_notify.Notifier(out, None, None, None)
    assert bot.reply_for("상태").startswith("2026-11-10_v3")
    assert len(bot.reply_for("목록").splitlines()) == 3
    assert bot.reply_for("아무말") is None
    assert "지원하지 않는" in bot.reply_for("웹")                      # 열기 동작이 없으면 안내만

    import os, serve                                                     # .env 의 같은 줄 주석이 값으로 들어가지 않는다
    envf = root / "t.env"
    envf.write_text("TENV_A=123   # 설명\nTENV_B=\"x # 유지\"\nTENV_C=   # 비어있음\nTENV_D=abc\n", encoding="utf-8")
    serve.load_env(envf)
    assert (os.environ["TENV_A"], os.environ["TENV_B"], os.environ["TENV_C"], os.environ["TENV_D"]) == ("123", "x # 유지", "", "abc")

    opened = []
    web_bot = discord_notify.Notifier(out, None, None, None, open_web=lambda: opened.append(1) or "열었습니다")
    assert [web_bot.reply_for(w) for w in ("웹", " web ", "업로드")] == ["열었습니다"] * 3 and len(opened) == 3
    assert web_bot.reply_for("웹 열어줘") is None                      # 정확히 일치할 때만 (일반 대화에 오작동 방지)

    def boom():
        raise RuntimeError("no browser")
    assert "열지 못했습니다" in discord_notify.Notifier(out, None, None, None, open_web=boom).reply_for("웹")
    assert not bot.enabled

    sent = []

    def fake_runner(src, out_root):
        assert src.name.startswith("주문원본_") and src.exists()      # 원본 이름이 아닌 일반 이름으로 저장
        make_run(out_root, "2026-11-10_v4", "정상", [("정상", "변환")], ["26-11-10 발송내역.xlsx"])

    app = webapp.create_app(root, notify=sent.append, runner=fake_runner).test_client()
    assert app.get("/").status_code == 200
    r = app.post("/upload", data={"file": (io.BytesIO(b"x"), "홍길동_주문.xlsx")}, content_type="multipart/form-data")
    assert r.status_code == 200 and "2026-11-10_v4" in r.get_data(as_text=True)
    assert sent == ["✅ 변환 완료 · 2026-11-10_v4 · 파일 1개"], sent
    assert "홍길동" not in r.get_data(as_text=True)
    assert list((root / "input").glob("*홍길동*")) == []
    assert app.post("/upload", data={"file": (io.BytesIO(b"x"), "a.txt")}, content_type="multipart/form-data").status_code == 400
    assert app.get("/files/2026-11-10_v4/26-11-10 발송내역.xlsx").status_code == 200
    assert app.get("/files/2026-11-10_v4/..%2Fx.xlsx").status_code == 404        # 경로 조작 차단
    assert app.get("/files/..%2F/x.xlsx", follow_redirects=True).status_code == 404
    assert app.get("/files/2026-11-10_v4/실행요약.txt").status_code == 404
    assert app.get("/", headers={"Host": "evil.example.com"}).status_code == 403
print("OK")
