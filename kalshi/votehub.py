"""VoteHub poll reads for the judgment step. Stdlib only, no auth.

Both RCP domains 403 WebFetch server-side (realclearpolling 9/28,
realclearpolitics 9/29, same-batch controls answered), leaving
KXTRUMPAPPROVE unpriceable (item #20). VoteHub publishes a documented
public API (votehub.com/polls/api, data CC BY 4.0) and the watchlist names
it as the alternate route; KXGENERICBALLOTVOTEHUB-* settles on VoteHub's
aggregate outright.

  python3 kalshi/votehub.py polls approval                  # last 30 days
  python3 kalshi/votehub.py polls approval --subject Trump
  python3 kalshi/votehub.py polls generic-ballot --since 2026-09-01

Poll types per the docs: approval, favorability, generic-ballot (subject
and pollster filters treat dashes and spaces as interchangeable). The
summary means are UNWEIGHTED across the listed polls — they are pricing
context, not a settlement value: KXGENERICBALLOTVOTEHUB settles on
VoteHub's own published average and KXTRUMPAPPROVE on the RCP average.
Schema pinned from the docs sight-unseen (the operator sandbox cannot
reach the host), so an unexpected body shape is a loud exit, never an
empty print.
"""

import datetime
import json
import sys
import urllib.parse
import urllib.request

POLLS_URL = "https://api.votehub.com/polls"


def _fetch(params: dict) -> object:
    req = urllib.request.Request(
        POLLS_URL + "?" + urllib.parse.urlencode(params),
        headers={"User-Agent": "paper-research/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _day(value: str) -> str:
    """Dates may carry a time part; only the day matters for poll windows."""
    return datetime.date.fromisoformat(value[:10]).isoformat()


def _polls(body: object) -> list[dict]:
    if isinstance(body, dict) and isinstance(body.get("polls"), list):
        return body["polls"]
    if isinstance(body, list):
        return body
    print(f"votehub: unexpected response shape: {str(body)[:200]}",
          file=sys.stderr)
    sys.exit(2)


def fetch_polls(poll_type: str, subject: str | None,
                since: str) -> list[dict]:
    """Polls of one type ending on/after `since`, newest end_date first."""
    params = {"poll_type": poll_type}
    if subject:
        params["subject"] = subject
    rows = [poll for poll in _polls(_fetch(params))
            if _day(poll["end_date"]) >= since]
    return sorted(rows, key=lambda poll: _day(poll["end_date"]),
                  reverse=True)


def _line(poll: dict) -> str:
    parts = [_day(poll["end_date"]), poll.get("pollster", "?")]
    if poll.get("sample_size"):
        size = f"n={poll['sample_size']}"
        if poll.get("population"):
            size += f" {poll['population']}"
        parts.append(size)
    parts += [f"{a['choice']} {a['pct']:g}" for a in poll.get("answers", [])]
    return "  ".join(parts)


def main(argv: list[str]):
    if argv[:1] != ["polls"] or len(argv) < 2 or argv[1].startswith("--"):
        sys.exit(__doc__)
    poll_type, subject, since, opts = argv[1], None, None, argv[2:]
    while opts:
        if opts[:1] == ["--subject"] and len(opts) > 1:
            subject, opts = opts[1], opts[2:]
        elif opts[:1] == ["--since"] and len(opts) > 1:
            since, opts = opts[1], opts[2:]
        else:
            sys.exit(__doc__)
    if since is None:
        since = (datetime.datetime.now(tz=datetime.timezone.utc).date()
                 - datetime.timedelta(days=30)).isoformat()
    rows = fetch_polls(poll_type, subject, since)
    if not rows:
        print(f"# no polls for {poll_type} since {since}")
        return
    for poll in rows:
        print(_line(poll))
    newest = _day(rows[0]["end_date"])
    lag = (datetime.datetime.now(tz=datetime.timezone.utc).date()
           - datetime.date.fromisoformat(newest)).days
    print(f"# {len(rows)} polls since {since}; "
          f"newest end_date: {newest} (lag {lag}d)")
    sums: dict[str, list[float]] = {}
    for poll in rows:
        for answer in poll.get("answers", []):
            sums.setdefault(answer["choice"], []).append(answer["pct"])
    means = "  ".join(f"{choice} {sum(vals) / len(vals):.1f}"
                      for choice, vals in sums.items())
    if means:
        print(f"# unweighted means (not a settlement value): {means}")


if __name__ == "__main__":
    main(sys.argv[1:])
