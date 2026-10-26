"""Check a daily brief against the schema before anything reads it. Stdlib only.

Every downstream reader (publish.py, speak.py, the dashboard, daily.sh's
commit message) json.loads $DATA/brief-<date>.json and trusts the shape the
daily prompt documents. publish.py reads every brief on every run, so one
malformed file would break the dashboard until a human fixed it. The 10-25
judgment run couldn't check its own brief ("the command needed approval");
this is the granted check, and daily.sh runs it after the judgment step.

  python3 kalshi/brief.py check [PATH]   # default $DATA/brief-<today>.json

Prints "brief OK: ..." and exits 0, or prints each problem and exits 2.
"""

import datetime as dt
import json
import os
import pathlib
import re
import sys

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))
REQUIRED = ("date", "narrative", "trades_opened", "trades_settled",
            "considered_but_passed", "bankroll", "at_risk", "sources_checked")
TRADE_LISTS = ("trades_opened", "trades_settled", "considered_but_passed")
NAME = re.compile(r"^brief-(\d{4}-\d{2}-\d{2})\.json$")


def _today() -> str:
    return dt.date.today().isoformat()


def problems(path: pathlib.Path) -> list[str]:
    """Everything wrong with the brief at path; [] when it's fine."""
    try:
        text = path.read_text()
    except OSError as e:
        return [f"cannot read {path}: {e}"]
    try:
        d = json.loads(text)
    except ValueError as e:
        return [f"not valid JSON: {e}"]
    if not isinstance(d, dict):
        return ["top level must be a JSON object"]
    out = [f"missing key {k!r}" for k in REQUIRED if k not in d]
    m = NAME.match(path.name)
    if m and "date" in d and d["date"] != m.group(1):
        out.append(f"date {d['date']!r} does not match filename {m.group(1)}")
    for k in ("narrative", "narrative_spoken"):
        if k in d and not (isinstance(d[k], str) and d[k].strip()):
            out.append(f"{k} must be non-empty text")
    for k in TRADE_LISTS:
        if k not in d:
            continue
        if not isinstance(d[k], list):
            out.append(f"{k} must be a list")
            continue
        for i, t in enumerate(d[k]):
            if not (isinstance(t, dict) and isinstance(t.get("ticker"), str)):
                out.append(f"{k}[{i}] must be an object with a ticker")
    for k in ("bankroll", "at_risk"):
        v = d.get(k)
        if k in d and (isinstance(v, bool) or not isinstance(v, (int, float))):
            out.append(f"{k} must be a number, got {v!r}")
    if "sources_checked" in d and not isinstance(d["sources_checked"], list):
        out.append("sources_checked must be a list")
    return out


def main(argv: list[str]) -> int:
    if not argv or argv[0] != "check" or len(argv) > 2:
        print(__doc__.strip(), file=sys.stderr)
        return 2
    path = (pathlib.Path(argv[1]) if len(argv) == 2
            else DATA / f"brief-{_today()}.json")
    found = problems(path)
    if found:
        for p in found:
            print(f"brief: {path.name}: {p}", file=sys.stderr)
        return 2
    d = json.loads(path.read_text())
    print(f"brief OK: {path.name} ({len(d['trades_opened'])} opened, "
          f"{len(d['trades_settled'])} settled, "
          f"{len(d['considered_but_passed'])} passed)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
