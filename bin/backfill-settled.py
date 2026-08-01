#!/usr/bin/env python3
"""One-shot: re-stamp `settled` in closed.jsonl with the real market close time.

Before the settle poller learned about Kalshi's "finalized" status (fix
762116e) it sat dead from 2026-07-13 to 07-20, then closed eight days of
expired positions in a single catch-up run. Every one of those rows carries
the catch-up timestamp, which stacks them into one vertical cliff on the
equity curve.

This rewrites `settled` from the market's close_time and preserves the
poller's own clock as `recorded`. Idempotent — safe to re-run.

    KALSEER_DATA_DIR=... python3 bin/backfill-settled.py [--dry-run]
"""

import json
import shutil
import sys

sys.path.insert(0, str(__import__("pathlib").Path(__file__).parents[1] / "kalshi"))

import kalshi  # noqa: E402
import paper  # noqa: E402


def main(dry_run: bool) -> int:
    if not paper.CLOSED.exists():
        print(f"no closed trades at {paper.CLOSED}")
        return 0

    rows = [json.loads(l) for l in paper.CLOSED.read_text().splitlines() if l.strip()]
    changed = 0
    for r in rows:
        try:
            close = paper.market_close_time(kalshi.get_market(r["ticker"]))
        except Exception as e:
            print(f"! {r['ticker']}: {e} — left alone")
            continue
        if not close or close == r.get("settled"):
            continue
        r.setdefault("recorded", r["settled"])
        print(f"  {r['ticker']:<32} {r['settled']} -> {close}")
        r["settled"] = close
        changed += 1

    if not changed:
        print("nothing to backfill")
        return 0
    if dry_run:
        print(f"{changed} row(s) would change (dry run)")
        return 0

    shutil.copy2(paper.CLOSED, paper.CLOSED.with_suffix(".jsonl.bak"))
    rows.sort(key=lambda r: r.get("settled", ""))
    paper.CLOSED.write_text("".join(json.dumps(r) + "\n" for r in rows))
    print(f"{changed} row(s) re-stamped; backup at {paper.CLOSED}.bak")
    return 0


if __name__ == "__main__":
    sys.exit(main("--dry-run" in sys.argv))
