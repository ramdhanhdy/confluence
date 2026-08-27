"""Confluence stage 1 — SCOUT.

Extracts public job postings from Upwork + Freelancer.com via the
browser_exec harness (headless), writing one JSONL record per posting:

    {"id", "source", "category", "title", "url", "text", "scraped_at"}

Dedupe key: `id` (Upwork job id / Freelancer project slug).

NOTE: this module is designed to be invoked by the Hermes agent through
browser_exec — the browser helpers (new_tab/goto_url/js/wait_for_load)
only exist in that harness. When run via `python scout.py --run ...`
standalone it will fail fast with a clear message. The agent's cron job
calls browser_exec with the JS below and appends to stage1_raw.

Extraction JS (kept here as the validated recipe):

Upwork:
  Array.from(document.querySelectorAll('a[href*="/freelance-jobs/apply/"]'))
    .map(a => ({ url: a.href.split('?')[0],
                 title: (a.innerText || '').trim().split('\\n')[0],
                 text: ((a.closest('[class*="card"], article, section') || a.parentElement)
                        .innerText || '').trim().slice(0, 420) }))

Freelancer:
  Array.from(document.querySelectorAll('a[href*="/projects/"]'))
    .map(a => ({ url: a.href.split('?')[0],
                 title: (a.innerText || '').trim().split('\\n')[0],
                 text: ((a.closest('[class*="card"], article, section') || a.parentElement)
                        .innerText || '').trim().slice(0, 420) }))

Cloudflare clears in ~6-8s after goto_url (title stops being the
challenge page); wait, then extract.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from lib.io import StageTimer, manifest_update

UPWORK_CATS = [
    "artificial-intelligence", "machine-learning", "web-development",
    "data-science", "natural-language-processing",
]
FREELANCER_CATS = [
    "artificial-intelligence", "machine-learning", "data-science",
    "python", "javascript",
]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True)
    args = ap.parse_args()
    run = Path(args.run)
    timer = StageTimer()
    raw_path = run / "stage1_raw" / "raw_signals.jsonl"
    if not raw_path.exists():
        print("ERROR: stage1_raw/raw_signals.jsonl missing. Scout must be run "
              "through the Hermes browser_exec harness (see module docstring).",
              file=sys.stderr)
        sys.exit(2)
    from lib.io import read_jsonl
    raw = read_jsonl(raw_path)
    ids = {r["id"] for r in raw}
    manifest_update(run, "stage1_raw", {
        "outputs": {"raw_signals": len(raw), "unique_ids": len(ids),
                    "sources": sorted({r.get("source") for r in raw})},
        "seconds": timer.elapsed(),
    })
    print(f"scout: {len(raw)} raw signals, {len(ids)} unique")


if __name__ == "__main__":
    main()
