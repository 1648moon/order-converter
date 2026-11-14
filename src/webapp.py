"""로컬 업로드 웹페이지. 내 맥(127.0.0.1)에서만 열리고, 파일은 이 컴퓨터 밖으로 나가지 않는다.

업로드 -> input/ 저장 -> run_all.py 실행 -> 결과는 output/YYYY-MM-DD_vN/ -> 이 페이지에서 내려받기.
디스코드에는 runinfo.notify_text() 의 개인정보 없는 한 줄 알림만 보낸다.
"""
from __future__ import annotations

import io
import re
import subprocess
import sys
import threading
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Callable

from flask import Flask, abort, render_template_string, request, send_file, send_from_directory

import runinfo

ROOT = Path(__file__).resolve().parent.parent
MAX_UPLOAD_MB = 20
_RUN_LOCK = threading.Lock()                        # 버전 번호 충돌 방지: 변환은 한 번에 하나씩

PAGE = """<!doctype html><html lang="ko"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>주문 엑셀 변환</title>
<style>
 body{font-family:-apple-system,system-ui,sans-serif;max-width:720px;margin:2rem auto;padding:0 1rem;color:#222}
 h1{font-size:1.3rem} .box{border:2px dashed #999;border-radius:8px;padding:1.5rem;text-align:center}
 button{padding:.6rem 1.2rem;font-size:1rem;margin-top:.8rem;cursor:pointer}
 .ok{color:#0a7d2c}.warn{color:#b26a00}.bad{color:#c0392b}
 li{margin:.3rem 0} small{color:#666}
</style>
<h1>주문 엑셀 변환</h1>
<form class="box" method="post" action="/upload" enctype="multipart/form-data"
      onsubmit="this.querySelector('button').disabled=true;this.querySelector('button').textContent='변환 중… (잠시만 기다려주세요)'">
 <input type="file" name="file" accept=".xlsx" required><br>
 <button type="submit">변환하기</button>
 <p><small>파일은 이 컴퓨터에서만 처리되며 디스코드로 올라가지 않습니다.</small></p>
</form>
{% if result %}
 <h2 class="{{ cls }}">{{ result.overall }} · {{ result.name }}</h2>
 {% if result.fail_stages %}<p class="bad">실패 단계: {{ result.fail_stages|join(', ') }}<br>
  <small>자세한 내용은 폴더의 실행요약.txt 를 확인하세요: output/{{ result.name }}/</small></p>{% endif %}
 {% if result.warn_stages %}<p class="warn">경고 단계: {{ result.warn_stages|join(', ') }}<br>
  <small>파일은 생성됐지만 확인이 필요합니다. output/{{ result.name }}/실행요약.txt</small></p>{% endif %}
 {% if result.files|length > 1 %}<p><a href="/zip/{{ result.name }}"><button type="button">⬇ 전체 한 번에 받기 (ZIP, {{ result.files|length }}개)</button></a></p>{% endif %}
 <ul>{% for f in result.files %}
  <li><a href="/files/{{ result.name }}/{{ f }}">{{ f }}</a></li>{% endfor %}</ul>
{% endif %}
{% if recent %}<h3>최근 실행</h3><ul>
 {% for r in recent %}<li>{{ r.name }} · {{ r.overall }} · 파일 {{ r.files|length }}개
  {% if r.files %}(<a href="/run/{{ r.name }}">보기</a>){% endif %}</li>{% endfor %}</ul>{% endif %}
</html>"""


def create_app(root: Path = ROOT, notify: Callable[[str], None] | None = None,
               runner: Callable[[Path, Path], None] | None = None,
               input_dir: Path | None = None, output_root: Path | None = None) -> Flask:
    """runner(src_xlsx, output_root): 변환 실행. 기본값은 run_all.py 호출 (테스트에서 교체 가능).

    input_dir / output_root 를 주면 root 아래 input/·output/ 대신 그 경로를 쓴다."""
    app = Flask(__name__)
    app.config["MAX_CONTENT_LENGTH"] = MAX_UPLOAD_MB * 1024 * 1024
    input_dir = Path(input_dir) if input_dir else root / "input"
    output_root = Path(output_root) if output_root else root / "output"
    notify = notify or (lambda text: None)

    def default_runner(src: Path, out: Path) -> None:
        subprocess.run([sys.executable, "-I", "src/run_all.py", str(src), "--output-root", str(out)],
                       cwd=root, capture_output=True, text=True, timeout=600)   # 화면 출력은 버림(개인정보 방지)

    run_conversion = runner or default_runner

    @app.before_request
    def only_localhost():                           # 다른 웹사이트가 이 주소로 업로드를 쏘는 것 방지
        host = request.host.split(":")[0]
        if host not in ("127.0.0.1", "localhost"):
            abort(403)

    def render(result=None):
        cls = {"정상": "ok", "경고": "warn", "실패": "bad"}.get(result.overall, "") if result else ""
        return render_template_string(PAGE, result=result, cls=cls,
                                      recent=runinfo.recent_runs(output_root))

    @app.get("/")
    def index():
        return render()

    @app.post("/upload")
    def upload():
        f = request.files.get("file")
        if not f or not f.filename.lower().endswith(".xlsx"):
            abort(400, "xlsx 파일만 올릴 수 있습니다.")
        input_dir.mkdir(parents=True, exist_ok=True)
        # 원본 파일명은 쓰지 않는다(이름에 개인정보가 있을 수 있음, 경로 조작 방지)
        src = input_dir / f"주문원본_{datetime.now():%Y%m%d_%H%M%S}.xlsx"
        f.save(src)
        with _RUN_LOCK:
            before = {r.name for r in runinfo.recent_runs(output_root, limit=1000)}
            run_conversion(src, output_root)
            after = runinfo.recent_runs(output_root, limit=1000)
        new = [r for r in after if r.name not in before]
        if not new:
            summary = runinfo.RunSummary("(결과 없음)", "실패", fail_stages=["실행"])
        else:
            summary = new[0]
        notify(runinfo.notify_text(summary))
        return render(summary)

    @app.get("/run/<run>")
    def view_run(run):
        if not runinfo.RUN_DIR_RE.match(run) or not (output_root / run).is_dir():
            abort(404)
        return render(runinfo.summarize_run(output_root / run))

    @app.get("/files/<run>/<name>")
    def download(run, name):
        if not runinfo.RUN_DIR_RE.match(run) or not name.endswith(".xlsx"):
            abort(404)
        return send_from_directory(output_root / run, name, as_attachment=True)

    @app.get("/zip/<run>")
    def download_zip(run):
        run_dir = output_root / run
        if not runinfo.RUN_DIR_RE.match(run) or not run_dir.is_dir():
            abort(404)
        files = sorted(run_dir.glob("*.xlsx"))
        if not files:
            abort(404)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_STORED) as z:
            for p in files:
                z.write(p, p.name)
        buf.seek(0)
        return send_file(buf, mimetype="application/zip", as_attachment=True,
                         download_name=f"{run}.zip")

    return app
