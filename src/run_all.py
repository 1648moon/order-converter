"""주문원본 하나로 전체 산출물을 만들고 검증한 뒤, 날짜+버전 폴더에 모아 둔다.

사용법:
    .venv/bin/python src/run_all.py input/주문원본1.xlsx

실행할 때마다 새 폴더가 생긴다 (이전 폴더는 그대로 남음):
    output/2026-11-10_v1/
    output/2026-11-10_v2/      <- 같은 날 다시 실행하면 버전만 올라감
    output/2026-11-11_v1/      <- 날짜가 바뀌면 v1부터
    output/latest              <- 가장 최근 '성공' 폴더를 가리키는 바로가기 (실패한 실행은 제외)

폴더 안 내용 (파일명 규칙은 src/naming.py, 예: 26-11-10 오전 실행):
    주문원본1_변환.xlsx                          중간파일
    26-11-10 브랜드주문(1)-1.xlsx              공장용 (경동)  끝 숫자 = 같은 날 재작업 버전
    26-11-10 브랜드주문(1)-CJ.xlsx             CJ 주문이 있을 때만
    26-11-10 브랜드주문(합동)-신안-오전.xlsx   택배 접수용
    26-11-10 발송내역.xlsx                       내부보관용
    실행요약.txt             단계별 결과, 경고, 검증 결과 (개인정보 없음)
    검증리포트/              검증 불일치가 있을 때만 (값 포함)

종료코드: 0 모두 정상 / 2 경고 있음(파일은 생성됨) / 1 오류 또는 검증 실패
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
import naming  # noqa: E402


def next_run_dir(output_root: Path, today: str | None = None) -> Path:
    """output_root/YYYY-MM-DD_vN : 같은 날짜의 가장 큰 N + 1."""
    today = today or datetime.now().strftime("%Y-%m-%d")
    pat = re.compile(rf"^{re.escape(today)}_v(\d+)$")
    versions = [int(m.group(1)) for d in output_root.glob(f"{today}_v*")
                if d.is_dir() and (m := pat.match(d.name))]
    return output_root / f"{today}_v{max(versions, default=0) + 1}"


def previous_run_dir(output_root: Path, current: Path) -> Path | None:
    runs = sorted((d for d in output_root.iterdir()
                   if d.is_dir() and re.match(r"^\d{4}-\d{2}-\d{2}_v\d+$", d.name) and d != current),
                  key=lambda d: (d.name[:10], int(d.name.rsplit("_v", 1)[1])))
    return runs[-1] if runs else None


def point_latest(output_root: Path, run: Path) -> None:
    link = output_root / "latest"
    try:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(run.name)
    except OSError:
        pass   # 바로가기를 못 만드는 환경이면 건너뜀 (폴더 자체에는 영향 없음)


def run(cmd: list[str], env: dict) -> tuple[int, str]:
    p = subprocess.run([sys.executable, "-I", *cmd], cwd=ROOT, env=env,
                       capture_output=True, text=True)
    return p.returncode, (p.stdout + p.stderr).strip()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path, help="주문원본 엑셀 (예: input/주문원본1.xlsx)")
    ap.add_argument("--output-root", type=Path, default=ROOT / "output")
    ap.add_argument("--llm", action="store_true", help="규칙에 없는 상품명을 LLM 으로 제안받아 적용 (ANTHROPIC_API_KEY 필요)")
    ap.add_argument("--ampm", choices=["오전", "오후"], help="파일명의 오전/오후를 현재 시각 대신 지정")
    a = ap.parse_args()
    src = a.src if a.src.is_absolute() else Path.cwd() / a.src
    if not src.exists():
        print(f"파일 없음: {a.src}", file=sys.stderr)
        return 1

    root = a.output_root
    root.mkdir(parents=True, exist_ok=True)
    run_dir = next_run_dir(root)
    prev = previous_run_dir(root, run_dir)
    run_dir.mkdir()
    stem = src.stem
    now = datetime.now()
    if a.ampm:
        now = now.replace(hour=9 if a.ampm == "오전" else 14)
    now = naming.with_source_date(now, src)   # 파일명의 날짜는 실행일이 아니라 원본 파일의 날짜
    f = {"변환": run_dir / f"{stem}_변환.xlsx",
         "공장": run_dir / naming.factory_name(root, now),
         "택배": run_dir / naming.courier_name(now),
         "내부보관": run_dir / naming.storage_name(now)}
    env = {**os.environ, "ORDER_REPORT_DIR": str(run_dir / "검증리포트")}

    stages = [
        ("변환",           ["src/convert.py", str(src), "-o", str(f["변환"]), *(["--llm"] if a.llm else [])], False),
        ("변환 검증",       ["src/validate.py", str(src), str(f["변환"])], True),
        ("공장용",          ["src/factory.py", str(f["변환"]), "-o", str(f["공장"])], False),
        ("공장용 검증",     ["src/validate_factory.py", str(f["변환"]), str(f["공장"])], True),
        ("택배용",          ["src/courier.py", str(f["변환"]), "-o", str(f["택배"])], False),
        ("택배용 검증",     ["src/validate_courier.py", str(f["변환"]), str(f["택배"])], True),
        ("내부보관용",      ["src/storage.py", str(f["변환"]), "-o", str(f["내부보관"])], False),
        ("내부보관용 검증",  ["src/validate_storage.py", str(f["변환"]), str(f["내부보관"])], True),
    ]
    log, failed, warned = [], False, False
    for name, cmd, is_validation in stages:
        code, out = run(cmd, env)
        status = {0: "정상", 2: "경고"}.get(code, "실패")
        if status == "실패":
            failed = True
        elif status == "경고":
            warned = True
        log.append((name, status, out))
        print(f"[{status}] {name}")
        for line in out.splitlines():
            if line.strip().startswith("경고") or status == "실패":
                print("   ", line.strip())
        if name == "변환" and status == "실패":
            break   # 중간파일이 없으면 이후 단계 불가

    overall = "실패" if failed else ("경고" if warned else "정상")
    lines = [f"실행 시각: {datetime.now():%Y-%m-%d %H:%M:%S}",
             f"입력 파일: {src.name}",
             f"이번 폴더: {run_dir.name}",
             f"이전 폴더: {prev.name if prev else '(없음)'}",
             f"전체 결과: {overall}", "", "== 생성된 파일 =="]
    lines += [f"  {p.name}" for p in sorted(run_dir.glob("*.xlsx"))]
    lines += ["", "== 단계별 결과 =="]
    for name, status, out in log:
        lines.append(f"[{status}] {name}")
        lines += [f"    {ln}" for ln in out.splitlines()]
    (run_dir / "실행요약.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")

    if not failed:   # 실패한 실행은 latest 로 가리키지 않음 (폴더와 실행요약은 기록으로 남음)
        point_latest(root, run_dir)
    print(f"\n결과: {overall}  ->  {run_dir}")
    if prev:
        print(f"이전 폴더: {prev}")
    for p in sorted(run_dir.glob("*.xlsx")):
        print(f"  {p.name}")
    return 1 if failed else (2 if warned else 0)


if __name__ == "__main__":
    sys.exit(main())
