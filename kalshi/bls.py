"""BLS timeseries reads for the judgment step. Stdlib only, no key.

clevelandfed.org and bls.gov 403 WebFetch server-side (proven 8/8-8/9 with
same-batch controls answering), keeping the CPI/payrolls complex unpriceable
(item #4). api.bls.gov is BLS's documented programmatic host (public JSON
timeseries API, no registration) and its curl route was live-verified 9/30:
CUUR0000SA0 -> Aug 334.980, REQUEST_SUCCEEDED. This wraps that exact GET
interface so release-day reads are structured and repeatable.

  python3 kalshi/bls.py series cpi                # CUUR0000SA0, CPI-U NSA
  python3 kalshi/bls.py series cpi-sa             # CUSR0000SA0, CPI-U SA
  python3 kalshi/bls.py series payrolls           # CES0000000001, total
                                                  # nonfarm SA, thousands
  python3 kalshi/bls.py series u3                 # LNS14000000, U-3 rate SA
  python3 kalshi/bls.py series LNS14000000 --months 6

Unkeyed GET returns roughly the last three years, newest printed first with
MoM/YoY deltas (the payrolls MoM column IS the jobs number in thousands).
[P] marks a preliminary print, 'latest' the newest row — BLS revises and
Kalshi settles on the first print, so the flags matter. An unexpected body
shape or a non-success status is a loud exit, never a quiet wrong delta.
"""

import json
import sys
import urllib.request

SERIES_URL = "https://api.bls.gov/publicAPI/v2/timeseries/data/"

ALIASES = {
    "cpi": "CUUR0000SA0",        # CPI-U all items, NSA (the YoY basis)
    "cpi-sa": "CUSR0000SA0",     # CPI-U all items, SA (the MoM basis)
    "payrolls": "CES0000000001",  # all employees total nonfarm, SA, thousands
    "u3": "LNS14000000",         # unemployment rate U-3, SA
}


def _fetch(series_id: str) -> object:
    req = urllib.request.Request(
        SERIES_URL + series_id,
        headers={"User-Agent": "paper-research/0.1"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def _rows(body: object, series_id: str) -> list[dict]:
    if not isinstance(body, dict) or "status" not in body:
        print(f"bls: unexpected response shape: {str(body)[:200]}",
              file=sys.stderr)
        sys.exit(2)
    if body["status"] != "REQUEST_SUCCEEDED":
        print(f"bls: {body.get('status')}: "
              f"{' | '.join(body.get('message', []))}", file=sys.stderr)
        sys.exit(2)
    try:
        (series,) = body["Results"]["series"]
        data = series["data"]
        assert isinstance(data, list)
    except (KeyError, TypeError, ValueError, AssertionError):
        print(f"bls: unexpected response shape: {str(body)[:200]}",
              file=sys.stderr)
        sys.exit(2)
    # M13 is the annual average, not a print anyone settles on
    monthly = [row for row in data
               if row["period"].startswith("M") and row["period"] != "M13"]
    return sorted(monthly, key=lambda row: (row["year"], row["period"]),
                  reverse=True)


def _month(row: dict) -> tuple[int, int]:
    return int(row["year"]), int(row["period"][1:])


def _delta(value: float, base: dict | None, label: str) -> str | None:
    if base is None:
        return None
    d = value - float(base["value"])
    return f"{label} {d:+g} ({d / float(base['value']) * 100:+.2f}%)"


def _line(row: dict, by_month: dict) -> str:
    year, month = _month(row)
    value = float(row["value"])
    prior = (year, month - 1) if month > 1 else (year - 1, 12)
    parts = [f"{year}-{month:02d}", row["value"],
             _delta(value, by_month.get(prior), "mom"),
             _delta(value, by_month.get((year - 1, month)), "yoy")]
    codes = [f["code"] for f in row.get("footnotes", []) if f.get("code")]
    if codes:
        parts.append(f"[{','.join(codes)}]")
    if row.get("latest") == "true":
        parts.append("latest")
    return "  ".join(p for p in parts if p)


def main(argv: list[str]):
    if argv[:1] != ["series"] or len(argv) < 2 or argv[1].startswith("--"):
        sys.exit(__doc__)
    name, months, opts = argv[1], 14, argv[2:]
    while opts:
        if opts[:1] == ["--months"] and len(opts) > 1:
            months, opts = int(opts[1]), opts[2:]
        else:
            sys.exit(__doc__)
    series_id = ALIASES.get(name, name)
    rows = _rows(_fetch(series_id), series_id)
    if not rows:
        print(f"# no data for {series_id}")
        return
    by_month = {_month(row): row for row in rows}
    for row in rows[:months]:
        print(_line(row, by_month))
    newest = rows[0]
    label = f"{name} = {series_id}" if name in ALIASES else series_id
    year, month = _month(newest)
    print(f"# {label}: {len(rows)} monthly obs, latest {year}-{month:02d} "
          f"({newest['periodName']}) = {newest['value']}")


if __name__ == "__main__":
    main(sys.argv[1:])
