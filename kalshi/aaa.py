"""Capture the AAA national-average print deterministically. Stdlib only.

The gas/diesel series settles real markets (KXAAAGASW/M, KXDIESEL*), but a
print used to be captured only if the judgment session's own page fetch
succeeded — pipeline gap #2 (12 lost runs, Sep 2026) nearly lost the series
for good; the 9/16 print came back from the page's week-ago cell on its last
recoverable day. This step archives the raw page BEFORE parsing, so a fetch
that succeeds can never lose a print even when AAA redesigns the page, and
journals the page's exact strings (display-precision hazard: AAA shows 4
decimals; never round them through float).

  python3 kalshi/aaa.py               # fetch, archive raw, parse, append
  python3 kalshi/aaa.py --parse FILE  # re-parse an archived page (recovery)

Exit codes: 0 parsed + journaled; 1 fetch failed (nothing saved, alert-worthy
— the retention cells put a hard deadline on recovering a missed day);
2 raw archived but parse failed (print recoverable from the archive).
"""

import datetime as dt
import gzip
import json
import os
import pathlib
import re
import sys
import time
import urllib.request
from html.parser import HTMLParser

URL = "https://gasprices.aaa.com/"

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
AAA_DIR = DATA / "aaa"
RAW_DIR = AAA_DIR / "raw"
JOURNAL = AAA_DIR / "prints.jsonl"

PRICE_RE = re.compile(r"^\$\d+\.\d+$")

# Header cells -> journal keys; row labels -> journal keys. Matched by
# substring so cosmetic wording changes ("Current Avg." vs "Current Average")
# don't break the parse.
GRADES = [("regular", "regular"), ("mid", "mid_grade"),
          ("premium", "premium"), ("diesel", "diesel")]
ROWS = [("current", "current"), ("yesterday", "yesterday"),
        ("week", "week_ago"), ("month", "month_ago"), ("year", "year_ago")]


class ParseError(Exception):
    pass


class _Tables(HTMLParser):
    """Collect every table as rows of stripped cell texts."""

    def __init__(self):
        super().__init__()
        self.tables, self._stack, self._cell = [], [], None

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self._stack.append([])
        elif tag == "tr" and self._stack:
            self._stack[-1].append([])
        elif tag in ("td", "th") and self._stack:
            self._cell = []

    def handle_endtag(self, tag):
        if tag == "table" and self._stack:
            self.tables.append(self._stack.pop())
        elif tag in ("td", "th") and self._cell is not None:
            if self._stack and self._stack[-1]:
                self._stack[-1][-1].append(" ".join("".join(self._cell).split()))
            self._cell = None

    def handle_data(self, data):
        if self._cell is not None:
            self._cell.append(data)


def _grade_columns(row):
    """Map cell index -> grade key if this looks like the header row."""
    cols = {}
    for i, cell in enumerate(row):
        for word, key in GRADES:
            if word in cell.lower():
                cols[i] = key
                break
    return cols if len(cols) == len(GRADES) else None


def parse(html: str) -> dict:
    """Extract the national-average table as exact strings.

    Returns {"current": {"regular": "$4.4744", ...}, "yesterday": {...}, ...}
    keeping only price-shaped cells. Raises ParseError unless a fully priced
    "current" row is found — anything less means the settlement print is
    missing and the step must fail loudly.
    """
    parser = _Tables()
    parser.feed(html)
    for table in parser.tables:
        cols = next((c for row in table if (c := _grade_columns(row))), None)
        if not cols:
            continue
        rows = {}
        for row in table:
            if not row:
                continue
            key = next((k for word, k in ROWS if word in row[0].lower()), None)
            if key is None:
                continue
            prices = {g: row[i] for i, g in cols.items()
                      if i < len(row) and PRICE_RE.match(row[i])}
            if prices:
                rows[key] = prices
        if len(rows.get("current", {})) == len(GRADES):
            return rows
    raise ParseError("no fully priced national-average table found")


def fetch(tries: int = 3) -> str:
    req = urllib.request.Request(URL, headers={"User-Agent": "paper-research/0.1"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read().decode("utf-8", "replace")
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def _read(path: pathlib.Path) -> str:
    raw = path.read_bytes()
    if path.suffix == ".gz":
        raw = gzip.decompress(raw)
    return raw.decode("utf-8", "replace")


def main(argv) -> int:
    if argv[:1] == ["--parse"]:
        try:
            print(json.dumps(parse(_read(pathlib.Path(argv[1]))), indent=1))
            return 0
        except ParseError as e:
            print(f"aaa: parse failed: {e}", file=sys.stderr)
            return 2

    try:
        html = fetch()
    except Exception as e:
        print(f"aaa: fetch failed: {e}", file=sys.stderr)
        return 1

    # Raw first: once the fetch succeeded, today's print is safe on disk no
    # matter what the parser thinks of the page.
    today = dt.date.today().isoformat()
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    raw_name = f"aaa-{today}.html.gz"
    (RAW_DIR / raw_name).write_bytes(gzip.compress(html.encode()))

    try:
        prices = parse(html)
    except ParseError as e:
        print(f"aaa: parse failed ({e}); raw archived at aaa/raw/{raw_name}",
              file=sys.stderr)
        return 2

    rec = {"date": today,
           "fetched_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "source": URL,
           "raw": f"aaa/raw/{raw_name}",
           "prices": prices}
    with open(JOURNAL, "a") as f:
        f.write(json.dumps(rec) + "\n")
    cur = prices["current"]
    print(f"aaa: {cur['regular']} regular / {cur['diesel']} diesel "
          f"({len(prices)} rows) -> {JOURNAL}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
