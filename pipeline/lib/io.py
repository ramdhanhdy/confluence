"""Shared IO + manifest helpers for the Confluence pipeline.

Every run directory gets a manifest.json that stages append to, so the
raw -> processed funnel (counts, durations, hashes) is auditable per run.
"""
from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path


def read_jsonl(path: Path) -> list[dict]:
    out = []
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def write_jsonl(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def read_json(path: Path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        json.dump(obj, f, ensure_ascii=False, indent=1)


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def manifest_path(run_dir: Path) -> Path:
    return run_dir / "manifest.json"


def manifest_update(run_dir: Path, stage: str, stats: dict) -> None:
    """Append/replace a stage entry in the run manifest."""
    mp = manifest_path(run_dir)
    m = read_json(mp) if mp.exists() else {"run_id": run_dir.name, "stages": {}}
    m["stages"][stage] = {**stats, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    write_json(mp, m)


class StageTimer:
    def __init__(self):
        self.t0 = time.time()

    def elapsed(self) -> float:
        return round(time.time() - self.t0, 2)
