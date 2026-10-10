"""NWS climate-report reads for the judgment step. Stdlib only, no auth.

Scoring a rain climate day has meant hand-running the two-step recipe the
watchlist records under HAZARD 1g: list product ids at
api.weather.gov/products/types/CLI/locations/{LOC}, then fetch the product
URL for its text. This CLI does that dance:

  python3 kalshi/wx.py cli LOC              # newest CLI report (e.g. DCA, NYC)
  python3 kalshi/wx.py cli LOC --list       # every archived version, newest first
  python3 kalshi/wx.py cli LOC --id UUID    # one specific version
  python3 kalshi/wx.py archive [LOC ...]    # pipeline step: save new versions

The report text prints verbatim — the PRECIPITATION line is a settlement
source, a display-precision hazard like every other; never reflow it.

NWS keeps only about 7 days of CLI reports: by 10/9 the 10/1 finals were
gone (gap #3). `archive` runs daily in bin/daily.sh and saves every version
it hasn't seen to $DATA/wx/cli/<LOC>/<id>.json (the API's id, issuanceTime,
issuingOffice, productText — verbatim), so a dead judgment run can no
longer cost a settlement day. Exit 1 only if no location answered at all.
"""

import json
import os
import pathlib
import re
import sys
import time
import urllib.request

BASE = "https://api.weather.gov"

DATA = pathlib.Path(os.environ.get("KALSEER_DATA_DIR",
                                   pathlib.Path(__file__).parents[1] / "data"))

# CLI station codes named in Kalshi's KXRAIN / KXHIGH* settlement rules
# (read live 2026-10-10). Not the market suffixes: NOLA -> MSY, DAL -> DFW,
# LV -> LAS, MIN -> MSP, SATX -> SAT; Chicago rain settles on ORD but the
# Chicago high on MDW. DTW is in the watchlist's scoring history.
DEFAULT_LOCATIONS = (
    "ABQ", "ATL", "AUS", "BOS", "CLL", "CMH", "DCA", "DEN", "DFW", "DTW",
    "EWR", "HOU", "IND", "LAS", "LAX", "LEX", "MDW", "MIA", "MKE", "MSP",
    "MSY", "NYC", "OKC", "ORD", "PHL", "PHX", "PIT", "PVD", "SAT", "SEA",
    "SFO", "SGF", "TTN",
)

SAFE_ID = re.compile(r"^[A-Za-z0-9-]+$")


def _get(path: str, tries: int = 3) -> dict:
    req = urllib.request.Request(BASE + path,
                                 headers={"User-Agent": "paper-research/0.1",
                                          "Accept": "application/ld+json"})
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.load(r)
        except Exception:
            if attempt == tries - 1:
                raise
            time.sleep(2 ** attempt)


def list_cli_products(location: str) -> list[dict]:
    """All archived CLI reports for a location code, newest first."""
    graph = _get(f"/products/types/CLI/locations/{location}").get("@graph", [])
    return sorted(graph, key=lambda p: p.get("issuanceTime", ""), reverse=True)


def print_product(product_id: str):
    p = _get(f"/products/{product_id}")
    print(f"=== CLI issued {p.get('issuanceTime', '-')} ({p.get('id', '-')})")
    print(p.get("productText", ""))


def archive(data, locations) -> tuple[int, list[str]]:
    """Save every not-yet-archived CLI version. Returns (saved, failed
    locations); a location fails if its listing or any product fetch did."""
    saved, failed = 0, []
    for loc in locations:
        out = pathlib.Path(data) / "wx" / "cli" / loc
        ok = True
        try:
            products = list_cli_products(loc)
        except Exception as e:
            print(f"wx archive: {loc}: listing failed: {e}", file=sys.stderr)
            failed.append(loc)
            continue
        for p in products:
            pid = str(p.get("id", ""))
            if not SAFE_ID.match(pid):
                print(f"wx archive: {loc}: refusing id {pid!r}", file=sys.stderr)
                ok = False
                continue
            dest = out / f"{pid}.json"
            if dest.exists():
                continue
            try:
                full = _get(f"/products/{pid}")
            except Exception as e:
                print(f"wx archive: {loc}: {pid}: {e}", file=sys.stderr)
                ok = False
                continue
            rec = {k: full.get(k) for k in
                   ("id", "issuanceTime", "issuingOffice", "productText")}
            out.mkdir(parents=True, exist_ok=True)
            tmp = dest.with_suffix(".tmp")
            tmp.write_text(json.dumps(rec, indent=1) + "\n")
            tmp.replace(dest)
            saved += 1
        if not ok:
            failed.append(loc)
    return saved, failed


def main(argv: list[str]):
    if argv[:1] == ["archive"]:
        locations = argv[1:] or DEFAULT_LOCATIONS
        saved, failed = archive(DATA, locations)
        print(f"wx archive: {saved} new CLI versions saved; "
              f"{len(locations) - len(failed)}/{len(locations)} locations ok"
              + (f"; failed: {' '.join(failed)}" if failed else ""))
        if len(failed) == len(locations):
            sys.exit(1)
        return
    if argv[:1] != ["cli"] or len(argv) < 2:
        sys.exit(__doc__)
    location, opts = argv[1], argv[2:]
    if opts[:1] == ["--id"] and len(opts) > 1:
        print_product(opts[1])
        return
    products = list_cli_products(location)
    if not products:
        print(f"wx: no CLI products for location {location}", file=sys.stderr)
        sys.exit(1)
    if opts[:1] == ["--list"]:
        for p in products:
            print(f"{p.get('issuanceTime', '-')}  {p.get('id', '-')}  "
                  f"{p.get('issuingOffice', '-')}")
        return
    print_product(products[0]["id"])


if __name__ == "__main__":
    main(sys.argv[1:])
