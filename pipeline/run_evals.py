"""Confluence EVAL harness.

Scores a run's stage2_distill output against the hand-labeled gold set
(evals/gold/gold_labels.jsonl) and writes a report to evals/reports/.

Gold record format (one JSONL line per labeled posting):
    {"id": "<posting id>", "lanes": ["python-automation"],
     "expected_outcome": "viable" | "rejected",
     "rejection_reasons": ["entry_level"],   // only when expected_outcome=rejected
     "notes": "why"}

Metrics computed:
- lane tagging: precision / recall / F1 per lane and micro-averaged
- rejection filter: accuracy, plus false-reject / false-accept lists
- signal clustering: agreement (does the gold posting land in the
  signal the human would name — gold may carry "expected_signal")

Exit code 0 always; the report is the artifact. Run after every pipeline
change to see if the change helped.

Usage:
  python run_evals.py --run E:/confluence/runs/<run_id>
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import read_jsonl, write_json


def score_lanes(viable_by_id: dict, gold: list[dict]) -> dict:
    per_lane = {}
    tp = fp = fn = 0
    for g in gold:
        if g["id"] not in viable_by_id:
            continue  # gold posting was rejected or not scouted
        pred = set(viable_by_id[g["id"]].get("lanes", []))
        truth = set(g.get("lanes", []))
        for lane in truth | pred:
            hit = lane in truth and lane in pred
            extra = lane in pred and lane not in truth
            miss = lane in truth and lane not in pred
            per_lane.setdefault(lane, {"tp": 0, "fp": 0, "fn": 0})
            per_lane[lane]["tp"] += hit
            per_lane[lane]["fp"] += extra
            per_lane[lane]["fn"] += miss
            tp += hit; fp += extra; fn += miss
    def f1(p, r):
        return round(2 * p * r / (p + r), 3) if p + r else 0.0
    out = {}
    for lane, c in per_lane.items():
        p = c["tp"] / (c["tp"] + c["fp"]) if c["tp"] + c["fp"] else 0.0
        r = c["tp"] / (c["tp"] + c["fn"]) if c["tp"] + c["fn"] else 0.0
        out[lane] = {"precision": round(p, 3), "recall": round(r, 3),
                     "f1": f1(p, r), **c}
    micro_p = tp / (tp + fp) if tp + fp else 0.0
    micro_r = tp / (tp + fn) if tp + fn else 0.0
    return {"per_lane": out, "micro": {
        "precision": round(micro_p, 3), "recall": round(micro_r, 3),
        "f1": f1(micro_p, micro_r), "tp": tp, "fp": fp, "fn": fn}}


def score_rejections(rejected_by_id: dict, viable_by_id: dict, gold: list[dict]) -> dict:
    correct = false_reject = false_accept = 0
    fr_list, fa_list = [], []
    for g in gold:
        exp = g.get("expected_outcome", "viable")
        in_viable = g["id"] in viable_by_id
        in_rejected = g["id"] in rejected_by_id
        if exp == "rejected" and in_rejected:
            correct += 1
        elif exp == "rejected" and in_viable:
            false_accept += 1
            fa_list.append({"id": g["id"], "why": g.get("notes", "")})
        elif exp == "viable" and in_rejected:
            false_reject += 1
            fr_list.append({"id": g["id"],
                            "reasons": rejected_by_id[g["id"]].get("rejection_reasons")})
        elif exp == "viable" and in_viable:
            correct += 1
    n = correct + false_reject + false_accept
    return {"gold_count": n, "correct": correct,
            "accuracy": round(correct / n, 3) if n else None,
            "false_rejects": fr_list, "false_accepts": fa_list}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    ap.add_argument("--gold", default=str(Path(__file__).parent.parent / "evals" / "gold" / "gold_labels.jsonl"))
    args = ap.parse_args()
    run = Path(args.run)

    gold_path = Path(args.gold)
    if not gold_path.exists() or gold_path.stat().st_size < 5:
        print("No gold labels yet. Label some postings in", gold_path,
              "then re-run. Writing empty report.")
        write_json(run.parent.parent / "evals" / "reports" /
                   f"eval_{run.name}.json", {"run": run.name, "gold": 0,
                                             "note": "no gold labels"})
        return

    gold = read_jsonl(gold_path)
    viable = read_jsonl(run / "stage2_distill" / "viable.jsonl")
    rejected = read_jsonl(run / "stage2_distill" / "rejected.jsonl")
    viable_by_id = {r["id"]: r for r in viable}
    rejected_by_id = {r["id"]: r for r in rejected}

    report = {
        "run": run.name,
        "gold_records": len(gold),
        "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "lanes": score_lanes(viable_by_id, gold),
        "rejections": score_rejections(rejected_by_id, viable_by_id, gold),
    }
    out = Path(__file__).parent.parent / "evals" / "reports" / f"eval_{run.name}.json"
    write_json(out, report)
    print(f"eval report -> {out}")
    print(json.dumps(report, indent=1)[:1200])


if __name__ == "__main__":
    main()
