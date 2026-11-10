"""주문 엑셀 변환 웹앱 (Streamlit).

실행:
    streamlit run app.py

환경변수:
    APP_PASSWORD   설정하면 비밀번호를 입력해야 사용 가능 (서버 배포 시 반드시 설정)
    NAME_STATE_DIR 공장용 파일의 '재작업 버전' 번호를 이어가기 위해 파일명만 기록하는 폴더
                   (기본 ./state). 내용은 비어 있는 0바이트 파일이라 개인정보가 없다.

개인정보 처리: 업로드한 엑셀과 변환 결과는 임시 폴더에서만 처리하고, 화면에 결과를 만든 직후 모두 삭제한다.
(다운로드용 바이트만 세션 메모리에 남고, 브라우저를 닫거나 새로 변환하면 사라진다.)
"""
from __future__ import annotations

import hmac
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

ROOT = Path(__file__).resolve().parent
STATE_DIR = Path(os.environ.get("NAME_STATE_DIR", ROOT / "state"))
FACTORY_RE = re.compile(r"^\d{2}-\d{2}-\d{2} 문바이크주문\(\d\)-\d+\.xlsx$")

st.set_page_config(page_title="주문 엑셀 변환", page_icon="📦")


def check_password() -> bool:
    expected = os.environ.get("APP_PASSWORD", "")
    if not expected:
        st.warning("APP_PASSWORD 가 설정되지 않았습니다. 로컬 테스트에서만 이 상태로 쓰세요.")
        return True
    if st.session_state.get("authed"):
        return True
    pw = st.text_input("비밀번호", type="password")
    if pw:
        if hmac.compare_digest(pw.encode(), expected.encode()):
            st.session_state["authed"] = True
            st.rerun()
        else:
            st.error("비밀번호가 맞지 않습니다.")
    return False


def convert(data: bytes, filename: str) -> dict:
    """업로드 바이트를 변환해 {summary, ok, files} 로 돌려준다. 임시 폴더는 끝나면 삭제된다."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="order_") as tmp:
        tmp = Path(tmp)
        src = tmp / (Path(filename).stem + ".xlsx")   # 경로 조작 방지: 이름만 사용
        src.write_bytes(data)
        out_root = tmp / "output"
        out_root.mkdir()
        for p in STATE_DIR.glob("*.xlsx"):             # 오늘 이미 만든 공장용 번호 이어가기
            (out_root / p.name).touch()
        proc = subprocess.run(
            [sys.executable, "-I", str(ROOT / "src" / "run_all.py"), str(src),
             "--output-root", str(out_root)],
            cwd=ROOT, capture_output=True, text=True, timeout=300)
        runs = sorted(d for d in out_root.iterdir() if d.is_dir() and d.name != "latest"
                      and not d.is_symlink())
        files, summary = {}, ""
        if runs:
            run_dir = runs[-1]
            summary_file = run_dir / "실행요약.txt"
            if summary_file.exists():
                summary = summary_file.read_text(encoding="utf-8")
            if proc.returncode != 1:                   # 실패 실행의 파일은 내려주지 않음
                for p in sorted(run_dir.glob("*.xlsx")):
                    files[p.name] = p.read_bytes()
                    if FACTORY_RE.match(p.name):
                        (STATE_DIR / p.name).touch()
        return {"code": proc.returncode, "log": proc.stdout + proc.stderr,
                "summary": summary, "files": files}


def prune_state() -> None:
    """상태 폴더에서 오늘이 아닌 파일명 기록은 지운다 (버전 번호는 하루 단위)."""
    from datetime import datetime
    today = datetime.now().strftime("%y-%m-%d")
    if STATE_DIR.exists():
        for p in STATE_DIR.glob("*.xlsx"):
            if not p.name.startswith(today):
                p.unlink(missing_ok=True)


st.title("📦 주문 엑셀 변환")

if check_password():
    st.caption("주문원본1 엑셀을 올리면 공장용·택배용·내부보관용 파일을 만들고 검증합니다. "
               "서버에는 파일이 저장되지 않습니다.")
    up = st.file_uploader("주문원본 엑셀 (.xlsx)", type=["xlsx"])
    if up is not None and st.button("변환 시작", type="primary"):
        prune_state()
        st.session_state.pop("result", None)
        with st.spinner("변환·검증 중..."):
            try:
                st.session_state["result"] = convert(up.getvalue(), up.name)
            except subprocess.TimeoutExpired:
                st.error("시간이 너무 오래 걸려 중단했습니다.")

    res = st.session_state.get("result")
    if res:
        code = res["code"]
        if code == 0:
            st.success("모두 정상입니다.")
        elif code == 2:
            st.warning("파일은 만들었지만 경고가 있습니다. 아래 요약을 확인하세요.")
        else:
            st.error("실패했습니다. 파일은 제공하지 않습니다. 아래 요약을 확인하세요.")
        for name, blob in res["files"].items():
            st.download_button(f"⬇ {name}", blob, file_name=name,
                               mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                               key=name)
        with st.expander("실행 요약 (개인정보 없음)", expanded=code != 0):
            st.code(res["summary"] or res["log"])
