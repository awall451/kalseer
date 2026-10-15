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


def no_run_days(data: pathlib.Path, first: datetime.date, end: datetime.date):
    """Gap days with no daily log: the pipeline never started (host down).

    Gap #4 (2026-10-11..10-12) was one. [] when there's no logs dir, since an
    install without one can't tell a dead host from a dead judgment step."""
    logs = data / "logs"
    if not logs.is_dir():
        return []
    days = [first + datetime.timedelta(days=i) for i in range((end - first).days + 1)]
    return [d.isoformat() for d in days
            if not (logs / f"daily-{d.isoformat()}.log").exists()]


def alerting_configured(env=os.environ) -> bool:
    # Same test as daily.sh's alert(): an empty value counts as unset.
    return bool(env.get("KALSEER_ALERT_URL") or env.get("KALSEER_ALERT_CMD"))


def heartbeat_configured(env=os.environ) -> bool:
    # Same test as daily.sh's heartbeat(): an empty value counts as unset.
    return bool(env.get("KALSEER_HEARTBEAT_URL"))


def notice(data, today: str, alerting: bool = True, heartbeat: bool = True) -> str:
    """The gap notice, or "" when yesterday has a brief (or none ever did).

    alerting=False adds that this host pages nobody on a failed run, so the
    brief tells the human why the gap went unnoticed. heartbeat=False does the
    same for no-run days, which only an external dead-man's switch can see."""
    today = datetime.date.fromisoformat(today)
    last = last_brief_before(pathlib.Path(data), today)
    if last is None or (today - last).days <= 1:
        return ""
    first, end = last + datetime.timedelta(days=1), today - datetime.timedelta(days=1)
    n = (end - first).days + 1
    span = first.isoformat() if n == 1 else f"{first}..{end}"
    runs = "1 daily run" if n == 1 else f"{n} daily runs"
    dead = no_run_days(pathlib.Path(data), first, end)
    if dead:
        ran = (f" (no pipeline run started at all on {', '.join(dead)} — host "
               "down or the timer never fired — so those days have no AAA "
               "capture, wx archive, or settle)")
        aaa = ("a no-run day's AAA print is NOT in aaa/prints.jsonl. Its "
               "national regular and diesel averages are Kalshi daily "
               "settlements, exact and dated by print day: `python3 "
               "kalshi/kalshi.py history KXAAAGASD` and `history KXDIESELD`. "
               "Mid-grade/premium survive only in the page's retention cells: "
               "the `yesterday`/`week_ago` cells of the first post-gap row "
               "(count from the raw page's 'Price as of' date, not the row's "
               "fetch day). Other gap-day prints are in aaa/prints.jsonl.")
    else:
        ran = " (settle, scan, and the AAA capture still ran)"
        aaa = "gap-day AAA prints are in aaa/prints.jsonl."
    return (
        f"PIPELINE GAP: the newest brief before today is brief-{last}.json — "
        f"{runs} ({span}) produced no brief{ran}. Before today's research, "
        "catch up: score every "
        "pre-registration and watchlist prediction that came due in the gap. "
        "Pull time-limited sources first — NWS CLI archives age out "
        "(`python3 kalshi/wx.py cli LOC --list`); market finals stay readable "
        "(`python3 kalshi/kalshi.py market TICKER`, `history SERIES`); "
        f"{aaa} Predictions that were "
        "never frozen because their run died are unscorable — say so, never "
        "reconstruct them. Name the gap and the catch-up in the brief "
        "narrative." + ("" if alerting else
        " ALERTING IS OFF: neither KALSEER_ALERT_URL nor KALSEER_ALERT_CMD "
        "is set for this pipeline, so the failed runs paged nobody. Put that "
        "in the brief's operator items: the human must configure one.")
        + ("" if heartbeat or not dead else
        " NO DEAD-MAN'S SWITCH: KALSEER_HEARTBEAT_URL is not set, and a run "
        "that never starts can't send an alert, so nothing paged for "
        f"{', '.join(dead)}. Put that in the brief's operator items: the "
        "human must point an external check (e.g. healthchecks.io, period 1 "
        "day) at KALSEER_HEARTBEAT_URL in the kalseer-daily unit."))


def main(argv: list[str]) -> int:
    today = datetime.date.today().isoformat()
    if "--today" in argv:
        i = argv.index("--today")
        today = argv[i + 1]
        argv = argv[:i] + argv[i + 2:]
    data = argv[0] if argv else os.environ.get(
        "KALSEER_DATA_DIR", pathlib.Path(__file__).parents[1] / "data")
    note = notice(data, today, alerting=alerting_configured(),
                  heartbeat=heartbeat_configured())
    if note:
        print(note)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
