"""전체 다운로드(ZIP) 테스트. 실행: .venv/bin/python -I tests/test_web_zip.py"""
import io
import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
import webapp  # noqa: E402

with tempfile.TemporaryDirectory() as t:
    out = Path(t) / "output"
    d = out / "2026-11-10_v1"
    d.mkdir(parents=True)
    (d / "a.xlsx").write_bytes(b"A")
    (d / "b.xlsx").write_bytes(b"B")
    (d / "실행요약.txt").write_text("전체 결과: 정상", encoding="utf-8")
    (out / "2026-11-10_v2").mkdir()
    c = webapp.create_app(root=Path(t), output_root=out).test_client()
    r = c.get("/zip/2026-11-10_v1", base_url="http://127.0.0.1")
    assert r.status_code == 200 and r.mimetype == "application/zip"
    assert sorted(zipfile.ZipFile(io.BytesIO(r.data)).namelist()) == ["a.xlsx", "b.xlsx"]
    assert c.get("/zip/2026-11-10_v2", base_url="http://127.0.0.1").status_code == 404
    assert c.get("/zip/..", base_url="http://127.0.0.1").status_code == 404
    assert c.get("/zip/2026-11-10_v1", base_url="http://evil.com").status_code == 403
    page = c.get("/run/2026-11-10_v1", base_url="http://127.0.0.1").get_data(as_text=True)
    assert "/zip/2026-11-10_v1" in page
print("OK")
