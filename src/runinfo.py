"""실행 결과 폴더(output/YYYY-MM-DD_vN)를 요약한다. 디스코드 알림·웹 화면 공통 사용.

개인정보 방침: 여기서 만드는 문자열에는 폴더명, 단계 이름, 건수만 넣는다.
스크립트가 출력한 경고/오류 원문(행·셀 값이 섞일 수 있음)은 절대 포함하지 않는다.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

RUN_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}_v\d+$")
_STAGE_RE = re.compile(r"^\[(정상|경고|실패)\] (.+)$")        # 실행요약.txt 의 단계 줄 (들여쓰기 없음)
_OVERALL_RE = re.compile(r"^전체 결과: (정상|경고|실패)$", re.M)


@dataclass
class RunSummary:
    name: str
    overall: str                                   # 정상 / 경고 / 실패 / 알 수 없음
    files: list[str] = field(default_factory=list)
    warn_stages: list[str] = field(default_factory=list)
    fail_stages: list[str] = field(default_factory=list)


def summarize_run(run_dir: Path) -> RunSummary:
    files = sorted(p.name for p in run_dir.glob("*.xlsx"))
    summary_txt = run_dir / "실행요약.txt"
    if not summary_txt.exists():
        return RunSummary(run_dir.name, "알 수 없음", files)
    text = summary_txt.read_text(encoding="utf-8")
    m = _OVERALL_RE.search(text)
    warn, fail = [], []
    for line in text.splitlines():
        sm = _STAGE_RE.match(line)
        if sm and sm.group(1) == "경고":
            warn.append(sm.group(2))
        elif sm and sm.group(1) == "실패":
            fail.append(sm.group(2))
    return RunSummary(run_dir.name, m.group(1) if m else "알 수 없음", files, warn, fail)


def recent_runs(output_root: Path, limit: int = 5) -> list[RunSummary]:
    if not output_root.exists():
        return []
    dirs = sorted((d for d in output_root.iterdir() if d.is_dir() and RUN_DIR_RE.match(d.name)),
                  key=lambda d: (d.name[:10], int(d.name.rsplit("_v", 1)[1])), reverse=True)
    return [summarize_run(d) for d in dirs[:limit]]


def notify_text(s: RunSummary) -> str:
    """디스코드로 보낼 한 줄 알림. 개인정보 없음."""
    if s.overall == "실패":
        stages = ", ".join(s.fail_stages) or "알 수 없음"
        return f"❌ 변환 실패 · {s.name} · 실패 단계: {stages}"
    icon = "✅" if s.overall == "정상" else "⚠️"
    tail = f" · 경고 단계 {len(s.warn_stages)}개 (웹 화면에서 확인)" if s.warn_stages else ""
    return f"{icon} 변환 완료 · {s.name} · 파일 {len(s.files)}개{tail}"


def status_text(runs: list[RunSummary]) -> str:
    if not runs:
        return "아직 변환 기록이 없습니다."
    return "\n".join(f"{r.name} · {r.overall} · 파일 {len(r.files)}개" for r in runs)
