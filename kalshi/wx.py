"""NWS climate-report reads for the judgment step. Stdlib only, no auth.

Scoring a rain climate day has meant hand-running the two-step recipe the
watchlist records under HAZARD 1g: list product ids at
api.weather.gov/products/types/CLI/locations/{LOC}, then fetch the product
URL for its text. This CLI does that dance:

  python3 kalshi/wx.py cli LOC              # newest CLI report (e.g. DCA, NYC)
  python3 kalshi/wx.py cli LOC --list       # every archived version, newest first
  python3 kalshi/wx.py cli LOC --id UUID    # one specific version

The report text prints verbatim — the PRECIPITATION line is a settlement
source, a display-precision hazard like every other; never reflow it.
"""

import json
import sys
import time
import urllib.request

BASE = "https://api.weather.gov"


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


def main(argv: list[str]):
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
