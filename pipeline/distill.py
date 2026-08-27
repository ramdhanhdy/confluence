"""Confluence stage 2 — DISTILL.

raw_signals.jsonl  ->  clean / viable / rejected (with reasons) + demand signals.

Design for evals-based development:
- every rejected record carries `rejection_reasons` (list of stable codes)
- every viable record carries `lanes` + `lane_evidence` (which keywords fired)
- signals.json records member posting ids, so clustering is inspectable
- summary.json records the funnel counts for the manifest

Usage:
  python distill.py --run E:/confluence/runs/<run_id>
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import (StageTimer, manifest_update, read_jsonl, write_json,
                    write_jsonl)

# ---------------------------------------------------------------- rules ----

MIN_TITLE_LEN = 12  # shorter = nav junk, not a real posting title

LEVEL_RE = re.compile(
    r"\b(entry[- ]level|beginner|no experience|junior only)\b"
    r"|\bentry\s*\|\s*experience level\b",  # Upwork card format: "Entry | Experience level"
    re.I,
)
GEO_RE = re.compile(
    r"\b(must be (?:located|based) in|only (?:us|usa|u\.s\.|canada|australia|uk|europe)|"
    r"us[- ]only|usa[- ]only|based in (?:the )?(?:us|usa|u\.s\.|canada|australia|uk|united states)|"
    r"residents? of|citizens? of|located in (?:the )?(?:us|usa|u\.s\.|canada|australia|uk))\b",
    re.I,
)
MICRO_BUDGET_MAX_USD = 100

# lane keyword rules: lane -> keywords (matched case-insensitively on
# title + text excerpt). Evidence records which keywords fired.
LANE_RULES: dict[str, list[str]] = {
    "llm-eval": [
        "annotation", "labeling", "labelling", "data labeling", "rlhf",
        "evaluation", "evals", "benchmark", "llm evaluation", "model evaluation",
        "prompt evaluation", "red team", "ai training data", "rating",
    ],
    "agent": [
        "agent", "agents", "agentic", "multi-agent", "multiagent",
        "agent workflow", "autonomous", "orchestration", "tool calling",
        "langchain", "langgraph", "crewai", "autogen",
    ],
    "python-automation": [
        "automation", "automate", "scraping", "scraper", "crawl", "crawler",
        "web scraping", "script", "scripts", "bot", "pipeline", "etl",
        "api integration", "python script", "selenium", "playwright", "beautifulsoup",
    ],
    "web-build": [
        "website", "web app", "webapp", "landing page", "frontend", "front-end",
        "react", "next.js", "nextjs", "vue", "astro", "wordpress", "shopify",
        "web development", "ui", "dashboard", "saas",
    ],
    "ds-classic": [
        "data analysis", "data analyst", "sql", "power bi", "tableau",
        "excel", "visualization", "statistics", "forecasting", "regression",
        "machine learning model", "predictive model",
    ],
}

# demand-signal keyphrases per lane: first matching phrase (by priority)
# names the cluster within the lane.
SIGNAL_PHRASES: dict[str, list[str]] = {
    "python-automation": ["scraping", "automation", "scripting", "pipeline"],
    "llm-eval": ["annotation", "evaluation", "labeling", "benchmark"],
    "agent": ["agent", "workflow", "orchestration"],
    "web-build": ["website", "video-collab", "dashboard", "ecommerce"],
    "ds-classic": ["analysis", "forecasting", "visualization", "sql"],
}


def extract_budget(text: str) -> dict | None:
    """Best-effort budget extraction -> {'min': x, 'max': y} USD or None."""
    nums = [int(m.replace(",", "")) for m in re.findall(r"\$\s?([\d,]{2,9})", text)]
    nums = [n for n in nums if 10 <= n <= 1_000_000]
    if not nums:
        m = re.search(r"(\d{2,6})\s*[-–]\s*(\d{2,6})\s*USD", text, re.I)
        if m:
            return {"min": int(m.group(1)), "max": int(m.group(2))}
        return None
    return {"min": min(nums), "max": max(nums)}


def tag_lanes(title: str, text: str) -> tuple[list[str], dict[str, list[str]]]:
    blob = (title + " \n " + text).lower()
    lanes, evidence = [], {}
    for lane, kws in LANE_RULES.items():
        hits = [k for k in kws if k in blob]
        if hits:
            lanes.append(lane)
            evidence[lane] = hits[:6]
    return lanes, evidence


def signal_keyphrase(lane: str, title: str, text: str) -> str:
    blob = (title + " \n " + text).lower()
    for ph in SIGNAL_PHRASES.get(lane, []):
        if ph.replace("-", " ") in blob or ph in blob:
            return ph
    return "general"


def distill(raw: list[dict]) -> dict:
    clean, viable, rejected = [], [], []
    for rec in raw:
        title = (rec.get("title") or "").strip()
        text = rec.get("text") or ""
        if len(title) < MIN_TITLE_LEN:
            rejected.append({**rec, "rejection_reasons": ["title_junk"]})
            continue
        blob = (title + " \n " + text)
        reasons = []
        if LEVEL_RE.search(blob):
            reasons.append("entry_level")
        if GEO_RE.search(blob):
            reasons.append("geo_locked")
        budget = extract_budget(blob)
        if budget and budget["max"] < MICRO_BUDGET_MAX_USD:
            reasons.append("micro_budget")
        rec_out = {
            "id": rec["id"],
            "source": rec.get("source"),
            "category": rec.get("category"),
            "title": title,
            "url": rec.get("url"),
            "text_excerpt": text[:420],
            "budget_usd": budget,
        }
        if reasons:
            rejected.append({**rec_out, "rejection_reasons": reasons})
        else:
            lanes, ev = tag_lanes(title, text)
            viable.append({**rec_out, "lanes": lanes, "lane_evidence": ev})
            clean.append(rec_out)
    return {"clean": clean, "viable": viable, "rejected": rejected}


def cluster(viable: list[dict]) -> list[dict]:
    groups: dict[str, list[str]] = defaultdict(list)
    for rec in viable:
        if not rec["lanes"]:
            continue
        lane = rec["lanes"][0]  # primary lane = first matched rule
        ph = signal_keyphrase(lane, rec["title"], rec["text_excerpt"])
        groups[f"{lane}:{ph}"].append(rec["id"])
    signals = []
    for key, ids in sorted(groups.items(), key=lambda kv: -len(kv[1])):
        if len(ids) >= 2:
            lane, ph = key.split(":", 1)
            signals.append({
                "signal_id": key, "lane": lane, "keyphrase": ph,
                "count": len(ids), "posting_ids": ids,
            })
    return signals


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, help="run directory")
    args = ap.parse_args()
    run = Path(args.run)
    timer = StageTimer()

    raw = read_jsonl(run / "stage1_raw" / "raw_signals.jsonl")
    out = distill(raw)
    signals = cluster(out["viable"])

    s2 = run / "stage2_distill"
    write_jsonl(s2 / "clean.jsonl", out["clean"])
    write_jsonl(s2 / "viable.jsonl", out["viable"])
    write_jsonl(s2 / "rejected.jsonl", out["rejected"])
    write_json(s2 / "signals.json", {"signals": signals,
                                     "singletons": sum(1 for v in out["viable"] if v["lanes"]) - sum(s["count"] for s in signals)})

    reason_counts = Counter(r for rec in out["rejected"] for r in rec["rejection_reasons"])
    lane_counts = Counter(l for rec in out["viable"] for l in rec["lanes"])
    summary = {
        "raw": len(raw), "clean": len(out["clean"]),
        "viable": len(out["viable"]), "rejected": len(out["rejected"]),
        "rejection_reasons": dict(reason_counts),
        "lane_counts": dict(lane_counts),
        "signals": len(signals),
    }
    write_json(s2 / "summary.json", summary)
    manifest_update(run, "stage2_distill", {
        "inputs": {"raw_signals": len(raw)},
        "outputs": {k: len(v) for k, v in out.items()} | {"signals": len(signals)},
        "summary": summary, "seconds": timer.elapsed(),
    })
    print(f"distill: {summary}")


if __name__ == "__main__":
    main()
