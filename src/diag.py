"""변환 진단 로그: 고객 정보는 빼고, 원인 파악에 필요한 상품·규칙 정보만 남긴다.

서버는 업로드 파일과 상세 리포트를 변환 직후 지운다. 그래서 실패 원인을 알 수 없었다.
변환마다 STATE/diag/<실행폴더>.json 한 개를 남기고(최근 KEEP개만 보관), 디스코드 '진단' 명령으로 요약을 본다.

남기는 것: 단계별 결과와 경고 문구, 검증 불일치(행 번호·항목 이름·기대값·결과값 — 허용된 상품·운임 항목만),
          변환된 상품명 목록과 건수, 오류 종류와 위치.
빼는 것:   수령자·구매자·주소·전화번호·우편번호·주문번호 등 고객 항목의 값. 허용 목록(VALUE_COLUMNS)에 없는 항목은 값을 가린다.
이중 안전장치: 원본 파일의 고객 항목 값과 전화번호 모양·긴 숫자열은 어느 문자열에서든 지운다.
"""
from __future__ import annotations

import csv
import json
import os
import re
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEEP = 30
MASK = "‹제외›"

# 값을 남겨도 되는 항목 (상품·운임·수량 등). 여기에 없는 항목은 값을 가린다.
VALUE_COLUMNS = {"상품명", "선택사항", "택배사", "수량", "주문량", "단가", "택배운임", "배송운임", "상품옵션",
                 "결제조건", "포장상태", "기타운임", "개별단가", "선불후불"}
# 원본에서 값을 지울 고객 항목 (머리글에 이 말이 들어 있으면 해당 열의 모든 값을 비밀로 본다)
SECRET_HEADERS = ("수령", "수취", "구매자", "주문자", "받는고객", "주소", "전화", "핸드폰", "휴대", "연락처",
                  "우편", "쇼핑몰ID", "주문번호", "송장", "이메일", "메모", "요청", "아이디", "ID")
_PHONE = re.compile(r"0\d{1,2}[-\s.]?\d{3,4}[-\s.]?\d{4}")
_LONG_DIGITS = re.compile(r"\d{8,}")


def diag_dir() -> Path:
    env = os.environ.get("DIAG_STATE_DIR")
    return Path(env) if env else Path(os.environ.get("NAME_STATE_DIR", ROOT / "state")) / "diag"


def secret_values(*workbooks: Path) -> set[str]:
    """원본·중간파일의 고객 항목 열 값 (2글자 이상). 값 자체는 파일에 저장하지 않고 지우는 데만 쓴다."""
    out: set[str] = set()
    for p in workbooks:
        try:
            from openpyxl import load_workbook
            ws = load_workbook(p, read_only=True, data_only=True).active
            rows = ws.iter_rows(values_only=True)
            head = [str(c or "").strip() for c in next(rows)]
            cols = [i for i, h in enumerate(head) if any(k in h for k in SECRET_HEADERS)]
            for r in rows:
                for i in cols:
                    v = r[i] if i < len(r) else None
                    t = str(v).strip() if v is not None else ""
                    if len(t) >= 2:
                        out.add(t)
        except Exception:
            continue
    return out


def scrub(text, secrets: set[str]) -> str:
    t = "" if text is None else str(text)
    for s in sorted(secrets, key=len, reverse=True):
        if s in t:
            t = t.replace(s, MASK)
    t = _PHONE.sub(MASK, t)
    return _LONG_DIGITS.sub(MASK, t)


def parse_stages(summary_text: str, secrets: set[str]) -> list[dict]:
    """실행요약.txt 의 '== 단계별 결과 ==' 를 [{name, status, lines}] 로."""
    stages, cur, on = [], None, False
    for line in summary_text.splitlines():
        if line.startswith("== 단계별 결과"):
            on = True
            continue
        if not on:
            continue
        m = re.match(r"^\[(정상|경고|실패)\] (.+)$", line)
        if m:
            cur = {"name": m.group(2), "status": m.group(1), "lines": []}
            stages.append(cur)
        elif cur is not None and line.strip():
            cur["lines"].append(scrub(line.strip(), secrets)[:300])
    for s in stages:
        s["lines"] = s["lines"][:25]
    return stages


def read_mismatches(report_dir: Path, secrets: set[str], limit: int = 40) -> list[dict]:
    out = []
    for p in sorted(report_dir.glob("*.csv")):
        try:
            with p.open(encoding="utf-8-sig", newline="") as f:
                for row in csv.DictReader(f):
                    cat, col = row.get("분류", ""), row.get("컬럼", "")
                    show = col in VALUE_COLUMNS or "합계" in col or "집계" in cat
                    out.append({
                        "file": p.name[:40], "category": scrub(cat, secrets), "row": row.get("행", ""),
                        "column": scrub(col, secrets),
                        "expected": scrub(row.get("원본(기대)값", ""), secrets)[:200] if show else MASK,
                        "actual": scrub(row.get("결과값", ""), secrets)[:200] if show else MASK,
                    })
                    if len(out) >= limit:
                        return out
        except (OSError, csv.Error):
            continue
    return out


def product_counts(intermediate: Path | None, secrets: set[str], limit: int = 60) -> list[list]:
    """변환된 상품명과 건수 (상품명은 고객 정보가 아니다)."""
    if not intermediate or not Path(intermediate).exists():
        return []
    try:
        from openpyxl import load_workbook
        ws = load_workbook(intermediate, read_only=True, data_only=True).active
        rows = ws.iter_rows(values_only=True)
        head = [str(c or "").strip() for c in next(rows)]
        if "상품명" not in head:
            return []
        i = head.index("상품명")
        cnt = Counter(scrub(r[i], secrets) for r in rows if i < len(r) and r[i] not in (None, ""))
        return [[n, c] for n, c in cnt.most_common(limit)]
    except Exception:
        return []


def error_tail(stderr: str, secrets: set[str], limit: int = 1500) -> str:
    """스택 트레이스에서 오류 종류와 위치만: 예외 줄(값이 섞일 수 있어 지움)과 'File …, line N' 줄."""
    keep = []
    for ln in (stderr or "").splitlines():
        s = ln.strip()
        if s.startswith("File ") or s.startswith("Traceback"):
            keep.append(scrub(re.sub(r"^File \"[^\"]*[/\\]", 'File "', s), secrets))
        elif re.match(r"^[A-Za-z_.]+(Error|Exception)\b", s):
            keep.append(s.split(":", 1)[0] + (": " + MASK if ":" in s else ""))
    return "\n".join(keep)[-limit:]


def build(src: Path, run_dir: Path | None, code: int, stderr: str = "") -> dict:
    intermediate = None
    if run_dir:
        found = sorted(Path(run_dir).glob("*_변환.xlsx"))
        intermediate = found[0] if found else None
    secrets = secret_values(src, *( [intermediate] if intermediate else [] ))
    rec = {"saved_at": int(time.time()), "code": code,
           "run": Path(run_dir).name if run_dir else None, "stages": [], "mismatches": [],
           "products": [], "error": ""}
    if run_dir:
        summary = Path(run_dir) / "실행요약.txt"
        if summary.exists():
            rec["stages"] = parse_stages(summary.read_text(encoding="utf-8"), secrets)
        rec["mismatches"] = read_mismatches(Path(run_dir) / "검증리포트", secrets)
        rec["products"] = product_counts(intermediate, secrets)
    if not run_dir or code == 1 and not rec["stages"]:
        rec["error"] = error_tail(stderr, secrets)
    return rec


def save(rec: dict, directory: Path | None = None) -> Path:
    d = Path(directory) if directory else diag_dir()
    d.mkdir(parents=True, exist_ok=True)
    name = rec.get("run") or f"error_{time.strftime('%Y%m%d_%H%M%S')}"
    p = d / f"{name}.json"
    p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    old = sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[KEEP:]
    for o in old:
        try:
            o.unlink()
        except OSError:
            pass
    return p


def save_run(src: Path, run_dir: Path | None, code: int, stderr: str = "") -> None:
    """변환 직후 호출. 진단 기록이 실패해도 변환 결과에는 영향을 주지 않는다."""
    try:
        save(build(src, run_dir, code, stderr))
    except Exception:
        pass


def load(name: str | None = None, directory: Path | None = None) -> dict | None:
    d = Path(directory) if directory else diag_dir()
    if name:
        safe = re.sub(r"[^0-9A-Za-z_\-]", "", name)
        p = d / f"{safe}.json"
        files = [p] if safe and p.exists() else []
    else:
        files = sorted(d.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True)[:1] if d.exists() else []
    if not files:
        return None
    try:
        rec = json.loads(files[0].read_text(encoding="utf-8"))
        rec.setdefault("run", files[0].stem)
        return rec
    except (OSError, ValueError):
        return None


def format_record(rec: dict) -> str:
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(rec.get("saved_at", 0)))
    out = [f"진단 · {rec.get('run') or '(실행 폴더 없음)'} · {when} · 종료코드 {rec.get('code')}"]
    for s in rec.get("stages", []):
        icon = {"정상": "✅", "경고": "⚠️", "실패": "❌"}.get(s["status"], "•")
        out.append(f"{icon} {s['name']}")
        if s["status"] != "정상":
            out += [f"    {ln}" for ln in s["lines"][:8]]
    if rec.get("mismatches"):
        out.append(f"검증 불일치 {len(rec['mismatches'])}건:")
        for m in rec["mismatches"][:15]:
            out.append(f"  - [{m['category']}] 행 {m['row']} · {m['column']}: 기대 {m['expected']} / 결과 {m['actual']}")
    if rec.get("products"):
        out.append("상품 " + ", ".join(f"{n} ×{c}" for n, c in rec["products"][:15]))
    if rec.get("error"):
        out.append("오류:\n" + rec["error"])
    return "\n".join(out)


def reply(arg: str = "", directory: Path | None = None) -> str:
    rec = load(arg.strip() or None, directory)
    if rec is None:
        return "진단 기록이 없어요." if not arg.strip() else f"'{arg.strip()}' 진단 기록을 찾지 못했어요."
    return format_record(rec)
