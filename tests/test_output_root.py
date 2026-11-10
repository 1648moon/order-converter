"""input_dir/output_root 지정 시 업로드·결과가 그 경로에 쌓이는지 테스트.
실행: .venv/bin/python -I tests/test_output_root.py (가짜 runner 사용, 개인정보 파일 불필요)"""
import io
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import webapp  # noqa: E402


def upload(app):
    return app.test_client().post("/upload", data={"file": (io.BytesIO(b"xlsx"), "a.xlsx")},
                                  content_type="multipart/form-data", base_url="http://127.0.0.1")


with tempfile.TemporaryDirectory() as t:
    base = Path(t)
    root, fixed_in, fixed_out = base / "worktree", base / "main" / "input", base / "main" / "output"
    root.mkdir()

    def runner(src: Path, out: Path):
        d = out / "2026-11-10_v1"
        d.mkdir(parents=True)
        (d / "a.xlsx").write_bytes(b"x")
        (d / "실행요약.txt").write_text("전체 결과: 정상\n\n== 단계별 결과 ==\n[정상] 변환\n", encoding="utf-8")

    r = upload(webapp.create_app(root, runner=runner, input_dir=fixed_in, output_root=fixed_out))
    assert r.status_code == 200, r.status_code
    assert (fixed_out / "2026-11-10_v1" / "a.xlsx").exists()                  # 고정 경로에 결과
    assert len(list(fixed_in.glob("주문원본_*.xlsx"))) == 1                    # 고정 경로에 업로드
    assert not (root / "output").exists() and not (root / "input").exists()   # 워크트리에는 안 생김

    upload(webapp.create_app(root, runner=runner))                            # 기본값은 기존과 동일
    assert (root / "output" / "2026-11-10_v1" / "a.xlsx").exists()
print("OK")
