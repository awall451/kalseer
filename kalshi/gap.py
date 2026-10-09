"""Pipeline-gap notice for the judgment step's prompt. No net.

The judgment session starts every run cold. When runs died in between
(2026-10-02..10-08: seven briefs lost to an outdated host CLI), the first
recovered run reads "today's" candidates and never learns that a week of
frozen pre-registrations scored without it. bin/daily.sh prepends this
notice to the prompt; on a normal day it prints nothing.

  python3 kalshi/gap.py [DATA_DIR] [--today YYYY-MM-DD]
"""

import datetime
import os
import pathlib
import re
import sys

BRIEF = re.compile(r"^brief-(\d{4}-\d{2}-\d{2})\.json$")


def last_brief_before(data: pathlib.Path, today: datetime.date):
    if not data.is_dir():
        return None
    days = [datetime.date.fromisoformat(m.group(1))
            for p in data.iterdir() if (m := BRIEF.match(p.name))]
    days = [d for d in days if d < today]
    return max(days, default=None)


def notice(data, today: str) -> str:
    """The gap notice, or "" when yesterday has a brief (or none ever did)."""
    today = datetime.date.fromisoformat(today)
    last = last_brief_before(pathlib.Path(data), today)
    if last is None or (today - last).days <= 1:
        return ""
    first, end = last + datetime.timedelta(days=1), today - datetime.timedelta(days=1)
    n = (end - first).days + 1
    span = first.isoformat() if n == 1 else f"{first}..{end}"
    runs = "1 daily run" if n == 1 else f"{n} daily runs"
    return (
        f"PIPELINE GAP: the newest brief before today is brief-{last}.json — "
        f"{runs} ({span}) produced no brief (settle, scan, and the AAA "
        "capture still ran). Before today's research, catch up: score every "
        "pre-registration and watchlist prediction that came due in the gap. "
        "Pull time-limited sources first — NWS CLI archives age out "
        "(`python3 kalshi/wx.py cli LOC --list`); market finals stay readable "
        "(`python3 kalshi/kalshi.py market TICKER`, `series SERIES settled`); "
        "gap-day AAA prints are in aaa/prints.jsonl. Predictions that were "
        "never frozen because their run died are unscorable — say so, never "
        "reconstruct them. Name the gap and the catch-up in the brief "
        "narrative.")


def main(argv: list[str]) -> int:
    today = datetime.date.today().isoformat()
    if "--today" in argv:
        i = argv.index("--today")
        today = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    data = argv[0] if argv else os.environ.get(
        "KALSEER_DATA_DIR", pathlib.Path(__file__).parents[1] / "data")
    note = notice(data, today)
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
