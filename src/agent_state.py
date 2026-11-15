"""에이전트가 쓰는 작은 상태 저장소 (JSON 파일).

- 마지막 변환 결과 요약(run.json): 개인정보 없는 건수·단계·상품명만. 서버는 업로드 파일을 지우므로,
  디스코드 쪽 에이전트는 이 요약만 보고 대화한다.
- 변경 제안(proposals.json): 에이전트가 '제안'만 만들고, 사람이 승인해야 적용된다.

저장 위치: AGENT_STATE_DIR, 없으면 NAME_STATE_DIR/agent, 그것도 없으면 ./state/agent
"""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PROPOSAL_TTL = 24 * 3600          # 제안은 하루 뒤 만료 (오래된 제안을 실수로 승인하지 않도록)
STATUSES = ("pending", "applied", "rejected", "expired", "failed")


def default_dir() -> Path:
    env = os.environ.get("AGENT_STATE_DIR")
    if env:
        return Path(env)
    return Path(os.environ.get("NAME_STATE_DIR", ROOT / "state")) / "agent"


class Store:
    def __init__(self, directory: Path | None = None, clock=time.time):
        self.dir = Path(directory) if directory else default_dir()
        self._clock = clock
        self._lock = threading.RLock()

    # ---- 파일 입출력 (원자적 쓰기) ----
    def _read(self, name: str, default):
        p = self.dir / name
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return default

    def _write(self, name: str, data) -> None:
        self.dir.mkdir(parents=True, exist_ok=True)
        tmp = self.dir / f".{name}.tmp"
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.dir / name)

    # ---- 마지막 변환 결과 ----
    def save_run(self, record: dict) -> None:
        with self._lock:
            self._write("run.json", {**record, "saved_at": int(self._clock())})

    def latest_run(self) -> dict | None:
        with self._lock:
            return self._read("run.json", None)

    # ---- 변경 제안 ----
    def _load_proposals(self) -> dict:
        data = self._read("proposals.json", {"next": 1, "items": {}})
        now = self._clock()
        for p in data["items"].values():
            if p["status"] == "pending" and now - p["created"] > PROPOSAL_TTL:
                p["status"] = "expired"
        return data

    def add_proposal(self, kind: str, params: dict, summary: str) -> dict:
        with self._lock:
            data = self._load_proposals()
            # 같은 내용의 대기 중 제안이 이미 있으면 새로 만들지 않는다
            for p in data["items"].values():
                if p["status"] == "pending" and p["kind"] == kind and p["params"] == params:
                    return p
            pid = data["next"]
            data["next"] = pid + 1
            p = {"id": pid, "kind": kind, "params": params, "summary": summary,
                 "status": "pending", "created": int(self._clock()), "note": ""}
            data["items"][str(pid)] = p
            self._write("proposals.json", data)
            return p

    def get_proposal(self, pid: int) -> dict | None:
        with self._lock:
            return self._load_proposals()["items"].get(str(pid))

    def pending(self) -> list[dict]:
        with self._lock:
            return sorted((p for p in self._load_proposals()["items"].values() if p["status"] == "pending"),
                          key=lambda p: p["id"])

    def set_status(self, pid: int, status: str, note: str = "") -> None:
        assert status in STATUSES
        with self._lock:
            data = self._load_proposals()
            p = data["items"].get(str(pid))
            if p is not None:
                p["status"], p["note"] = status, note
                self._write("proposals.json", data)
