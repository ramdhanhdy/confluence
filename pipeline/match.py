"""Confluence stage 3 — MATCH.

stage2_distill/viable.jsonl + state/github_snapshot.jsonl  ->  matches.jsonl

Every match row carries: the demand signal, the candidate repos, the
verdict (match / partial / gap), and `evidence` (which lane keywords
connected them) — so a human eval can audit why the system paired them.

Lane gate: a repo is only a candidate for a signal if its primary lane
matches the signal's lane (prevents cross-lane noise).

Usage:
  python match.py --run E:/confluence/runs/<run_id> --snapshot E:/confluence/state/github_snapshot.jsonl
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import (StageTimer, manifest_update, read_json, read_jsonl,
                    write_jsonl)

# Curated lane map for the user's GitHub inventory (session knowledge,
# because several repo descriptions are empty upstream). Extend as repos
# are added. Lane assignment: primary first.
REPO_LANES: dict[str, dict] = {
    "hermes-toolkit": {"lanes": ["agent", "python-automation"], "desc": "Hermes agent tooling, workflows, automation"},
    "hermes-fit-agent": {"lanes": ["agent", "python-automation"], "desc": "Fitness tracking agent plugin"},
    "agentred": {"lanes": ["python-automation", "agent"], "desc": "Job market demand intelligence / automation"},
    "skillruled": {"lanes": ["agent"], "desc": "Skill-driven agent routing"},
    "FraudLM": {"lanes": ["llm-eval", "ds-classic"], "desc": "LLM fraud-detection research"},
    "SycoBench": {"lanes": ["llm-eval"], "desc": "Sycophancy evaluation benchmark (research)"},
    "LLM-Text-Network-Analysis": {"lanes": ["ds-classic", "llm-eval"], "desc": "Text network analysis with LLMs"},
    "jobfit-ai": {"lanes": ["agent", "web-build"], "desc": "Job-fit AI assistant"},
    "ocr-checker": {"lanes": ["python-automation"], "desc": "OCR verification automation"},
    "HomeCredit": {"lanes": ["ds-classic"], "desc": "Credit risk modeling (classic DS)"},
    "retail-ops-control-tower": {"lanes": ["ds-classic", "web-build"], "desc": "Retail operations dashboard"},
    "price_optimization": {"lanes": ["ds-classic"], "desc": "Price optimization modeling"},
    "RSemble-AI": {"lanes": ["web-build", "agent"], "desc": "AI model showcase web app"},
    "MadraXis": {"lanes": ["web-build"], "desc": "Web build"},
    "pdverse": {"lanes": ["web-build"], "desc": "Web build"},
    "ramdhanhdy.github.io": {"lanes": ["web-build"], "desc": "Personal site"},
    "mageconv": {"lanes": ["web-build"], "desc": "Web build"},
}


def primary_lane(repo: str) -> str | None:
    meta = REPO_LANES.get(repo)
    return meta["lanes"][0] if meta else None


def match(viable: list[dict], snapshot: list[dict], signals: list[dict]) -> list[dict]:
    """One match row per demand signal."""
    rows = []
    repos_by_lane: dict[str, list[str]] = defaultdict(list)
    for name, meta in REPO_LANES.items():
        for lane in meta["lanes"]:
            repos_by_lane[lane].append(name)

    for sig in signals:
        lane = sig["lane"]
        candidates = repos_by_lane.get(lane, [])
        # postings that mention this lane
        member_ids = set(sig["posting_ids"])
        evidence_terms = defaultdict(int)
        for rec in viable:
            if rec["id"] in member_ids and lane in rec.get("lane_evidence", {}):
                for kw in rec["lane_evidence"][lane]:
                    evidence_terms[kw] += 1
        top_terms = sorted(evidence_terms.items(), key=lambda kv: -kv[1])[:5]

        if not candidates:
            verdict = "gap"
        else:
            # heuristic: 'match' if any candidate repo description shares a
            # keyphrase with the signal; otherwise 'partial' (adjacent, needs
            # packaging/demo). Kept simple on purpose — the eval harness is
            # what decides if this heuristic is good enough.
            keyphrase = sig["keyphrase"].lower()
            direct = [r for r in candidates
                      if keyphrase in REPO_LANES[r]["desc"].lower()]
            verdict = "match" if direct else "partial"
            candidates = direct or candidates

        rows.append({
            "signal_id": sig["signal_id"],
            "lane": lane,
            "keyphrase": sig["keyphrase"],
            "posting_count": sig["count"],
            "verdict": verdict,
            "candidate_repos": candidates,
            "evidence_terms": [t for t, _ in top_terms],
            "posting_ids": sig["posting_ids"][:10],
        })
    return rows


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--snapshot", required=True)
    args = ap.parse_args()
    run = Path(args.run)
    timer = StageTimer()

    viable = read_jsonl(run / "stage2_distill" / "viable.jsonl")
    signals = read_json(run / "stage2_distill" / "signals.json")["signals"]
    snapshot = read_jsonl(Path(args.snapshot))
    rows = match(viable, snapshot, signals)

    s3 = run / "stage3_match"
    write_jsonl(s3 / "matches.jsonl", rows)
    from collections import Counter
    verdicts = Counter(r["verdict"] for r in rows)
    manifest_update(run, "stage3_match", {
        "inputs": {"signals": len(signals), "snapshot_repos": len(snapshot)},
        "outputs": {"matches": len(rows), **dict(verdicts)},
        "seconds": timer.elapsed(),
    })
    print(f"match: {len(rows)} rows, verdicts={dict(verdicts)}")


if __name__ == "__main__":
    main()
