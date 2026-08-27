"""Confluence gold-label helper.

Label postings from a run into evals/gold/gold_labels.jsonl so
run_evals.py can score future pipeline changes.

Examples:
  # show 10 unlabeled viable postings (for you to read & decide)
  python label.py --run E:/confluence/runs/20260827 --sample 10

  # label one posting viable with lanes
  python label.py --id 022092512733564835172 --outcome viable --lanes python-automation --notes "real scraping gig"

  # label one posting rejected
  python label.py --id <id> --outcome rejected --reasons entry_level geo_locked
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

GOLD = Path(__file__).parent.parent / "evals" / "gold" / "gold_labels.jsonl"


def load_gold() -> list[dict]:
    if not GOLD.exists():
        return []
    return [json.loads(l) for l in open(GOLD, encoding="utf-8") if l.strip()]


def sample(run: Path, n: int) -> None:
    labeled = {g["id"] for g in load_gold()}
    viable = [json.loads(l) for l in open(run / "stage2_distill" / "viable.jsonl", encoding="utf-8")]
    rejected = [json.loads(l) for l in open(run / "stage2_distill" / "rejected.jsonl", encoding="utf-8")]
    shown = 0
    print("=== unlabeled VIABLE (decide lanes) ===")
    for r in viable:
        if r["id"] in labeled or shown >= n:
            continue
        shown += 1
        print(f"\n[{r['id']}] {r['title']}")
        print(f"  source={r['source']} predicted_lanes={r['lanes']} budget={r.get('budget_usd')}")
        print(f"  url={r.get('url')}")
        print(f"  excerpt: {r['text_excerpt'][:200]}")
    print("\n=== unlabeled REJECTED (decide if rejection is right) ===")
    shown = 0
    for r in rejected:
        if r["id"] in labeled or shown >= n:
            continue
        shown += 1
        print(f"\n[{r['id']}] {r['title']}")
        print(f"  reasons={r.get('rejection_reasons')} url={r.get('url')}")
        print(f"  excerpt: {r['text_excerpt'][:200]}")


def label(args) -> None:
    gold = load_gold()
    if any(g["id"] == args.id for g in gold):
        gold = [g for g in gold if g["id"] != args.id]  # re-label replaces
        print("(replaced existing label for this id)")
    rec = {
        "id": args.id,
        "lanes": args.lanes or [],
        "expected_outcome": args.outcome,
        "notes": args.notes or "",
    }
    if args.outcome == "rejected":
        rec["rejection_reasons"] = args.reasons or []
    gold.append(rec)
    GOLD.parent.mkdir(parents=True, exist_ok=True)
    with open(GOLD, "w", encoding="utf-8") as f:
        for g in gold:
            f.write(json.dumps(g, ensure_ascii=False) + "\n")
    print(f"labeled {args.id} -> {GOLD} ({len(gold)} total gold records)")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", help="run dir (for --sample)")
    ap.add_argument("--sample", type=int, help="show N unlabeled postings")
    ap.add_argument("--id", help="posting id to label")
    ap.add_argument("--outcome", choices=["viable", "rejected"])
    ap.add_argument("--lanes", nargs="*", default=[])
    ap.add_argument("--reasons", nargs="*", default=[])
    ap.add_argument("--notes", default="")
    args = ap.parse_args()

    if args.sample:
        if not args.run:
            sys.exit("--sample needs --run")
        sample(Path(args.run), args.sample)
    elif args.id:
        if not args.outcome:
            sys.exit("--id needs --outcome viable|rejected")
        label(args)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
