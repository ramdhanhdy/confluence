# Confluence

Demand↔inventory confluence for the freelance pipeline — built for
**evaluations-based development**: every stage writes inspectable,
line-oriented artifacts, every decision carries a reason, and a gold-set
eval loop scores each pipeline change.

## Layout

```
E:\confluence\
├── pipeline\               # stage code (pure, re-runnable)
│   ├── scout.py            # stage 1 — extract (runs via Hermes browser_exec)
│   ├── distill.py          # stage 2 — clean / filter / lane-tag / cluster
│   ├── match.py            # stage 3 — demand ↔ GitHub inventory
│   ├── run_evals.py        # score a run against gold labels
│   ├── label.py            # label postings into the gold set
│   └── lib\io.py           # JSONL IO + per-run manifest helpers
├── runs\<run_id>\          # one dir per scout run (run_id = YYYYMMDD)
│   ├── manifest.json       # stage funnel: inputs/outputs/seconds per stage
│   ├── stage1_raw\raw_signals.jsonl
│   ├── stage2_distill\clean.jsonl viable.jsonl rejected.jsonl signals.json summary.json
│   └── stage3_match\matches.jsonl
├── state\                  # persistent cross-run state
│   └── github_snapshot.jsonl
└── evals\
    ├── gold\gold_labels.jsonl      # hand-labeled postings (the ground truth)
    └── reports\eval_<run_id>.json  # lane P/R/F1 + rejection accuracy
```

Human-facing output goes to the Obsidian vault:
`E:\2026\vault\freelance\confluence\daily-brief-<date>.md`

## Data funnel (raw → processed)

```
raw_signals.jsonl          182   one JSON per line: id, source, category, title, url, text
  → clean.jsonl            171   junk titles dropped
  → viable.jsonl           171   + lanes[], lane_evidence{}, budget_usd
  → rejected.jsonl          11   + rejection_reasons[] (entry_level | geo_locked | micro_budget)
  → signals.json            10   demand clusters: lane:keyphrase, count, posting_ids[]
  → matches.jsonl           10   verdict match|partial|gap + candidate_repos + evidence_terms
```

Every record keeps its `id` end-to-end, so you can trace any posting from
raw scrape to final verdict:

```bash
grep '"022092512733564835172"' E:\confluence\runs\20260827\stage2_distill\rejected.jsonl
```

## Analyzing the datasets

All stage files are JSONL — one JSON object per line. Friendly to grep,
pandas, jq, or just opening in an editor:

```python
import pandas as pd
v = pd.read_json(r"E:\confluence\runs\20260827\stage2_distill\viable.jsonl", lines=True)
v["lanes"].explode().value_counts()          # lane demand
r = pd.read_json(r"...\rejected.jsonl", lines=True)
r["rejection_reasons"].explode().value_counts()  # why things get cut
```

`manifest.json` in each run records the funnel counts + timing per stage,
so week-over-week regressions (e.g. scout starts returning junk) show up
as count anomalies, not silent bad briefs.

## The eval loop

1. Read unlabeled postings: `python pipeline\label.py --run runs\<id> --sample 10`
2. Label them: `python pipeline\label.py --id <id> --outcome viable --lanes python-automation`
   (or `--outcome rejected --reasons entry_level`)
3. After any pipeline change: `python pipeline\run_evals.py --run runs\<id>`
4. Compare `evals\reports\eval_<id>.json` — lane precision/recall/F1 and
   rejection accuracy tell you whether the change helped.

Gold labels are append-only truth; never rewrite them to match the code.
If the eval disagrees with the label, re-check the posting first.

## Known eval finding (2026-08-27)

Upwork cards render experience as `Entry | Experience level` (not
"entry-level") — the first distill pass missed 4 of them. Fixed in
`LEVEL_RE`; gold set pins the 4 cases so a regression re-surfaces.

## Operations

- Daily cron `confluence-daily-scout` (07:00 WIB) runs stage 1 via
  browser_exec, then stages 2–3 + evals via terminal, writes the vault
  brief, and delivers a Telegram summary.
- Stage 1 is the only stage needing the browser harness; stages 2–3 and
  evals are pure local Python (fast, deterministic, re-runnable on any
  past run).
- `state/github_snapshot.jsonl` is refreshed when the inventory changes
  (new repos / descriptions).
