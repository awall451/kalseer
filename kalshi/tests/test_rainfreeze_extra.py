"""rainfreeze.py EXTRA cities: the busiest KXRAIN boards outside the family.

rainfreeze covers the watchlist family (DC / NYC / OKC), but the rain boards
the scan surfaces are elsewhere. 10/26 scan: KXRAIN-26OCT26-SEA 22,951
contracts, PHIL 10,224. Kalshi's 24h volume at 06Z 10/27: SEA 62,953,
PHIL 56,050, DEN 50,551, against OKC's 28,039 and DC's 1,796. They settle
on CLISEA / CLIPHL / CLIDEN, so RAW (NWS daytime PoP) vs MKT is the same
calibration question with more volume behind it. Their grids are resolved
at run time from the station's coordinates via NWS /points and journaled
with each row. Their Brier gets its own `# extra` summary, so the family's
lines (the watchlist's cli-precip-day-boundary ledger) are unchanged.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_rainfreeze import (BOARDS, FORECASTS, apis, period,  # noqa: F401
                             rainfreeze, rows)

SEA = (47.4444, -122.3139)
POINTS = "/points/47.4444,-122.3139"


@pytest.fixture
def sea(apis, monkeypatch):
    monkeypatch.setattr(rainfreeze, "EXTRA", {"SEA": SEA})
    monkeypatch.setitem(FORECASTS, POINTS, {
        "gridId": "SEW", "gridX": 124, "gridY": 61})
    monkeypatch.setitem(FORECASTS, "/gridpoints/SEW/124,61/forecast", {
        "periods": [
            period("Today", "2026-10-15T05:00:00-07:00", 90, "Rain"),
            period("Tonight", "2026-10-15T18:00:00-07:00", 70, "Rain",
                   day=False)]})
    monkeypatch.setitem(BOARDS, "KXRAIN-26OCT15-SEA", {
        "ticker": "KXRAIN-26OCT15-SEA", "status": "active",
        "yes_bid_dollars": "0.8100", "yes_ask_dollars": "0.8200"})
    return apis


def test_the_extra_cities_are_the_busiest_boards():
    assert set(rainfreeze.EXTRA) == {"SEA", "PHIL", "DEN"}
    assert rainfreeze.ticker("PHIL", "2026-10-27") == "KXRAIN-26OCT27-PHIL"


def test_extra_city_grid_is_resolved_and_journaled(sea):
    ok, failed = rainfreeze.freeze()
    assert (ok, failed) == (4, [])
    r = {x["city"]: x for x in rows()}["SEA"]
    assert r["grid"] == "SEW 124,61" and r["raw"] == 0.9
    assert (r["yes_bid"], r["yes_ask"]) == ("0.8100", "0.8200")
    assert r["date"] == "2026-10-15" and r["ticker"] == "KXRAIN-26OCT15-SEA"
    assert POINTS in sea


def test_a_geojson_points_reply_also_resolves(sea, monkeypatch):
    monkeypatch.setitem(FORECASTS, POINTS, {"properties": {
        "gridId": "SEW", "gridX": 124, "gridY": 61}})
    rainfreeze.freeze()
    assert {x["city"]: x for x in rows()}["SEA"]["grid"] == "SEW 124,61"


def test_a_failed_points_lookup_keeps_the_board(sea, monkeypatch):
    monkeypatch.delitem(FORECASTS, POINTS)
    ok, failed = rainfreeze.freeze(today="2026-10-15")
    assert ok == 3 and failed == ["SEA"]
    r = {x["city"]: x for x in rows()}["SEA"]
    assert r["raw"] is None and r["yes_bid"] == "0.8100"
    assert r["grid"] == "points 47.4444,-122.3139"


def test_extra_cities_score_in_their_own_summary(sea, monkeypatch, capsys):
    rainfreeze.freeze()
    results = {"KXRAIN-26OCT15-DC": "yes", "KXRAIN-26OCT15-NYC": "no",
               "KXRAIN-26OCT15-OKC": "yes", "KXRAIN-26OCT15-SEA": "no"}
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t, tries=4: {"ticker": t,
                                            "result": results.get(t, "")})
    rainfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    assert any(l[:4].isdigit() and l.split()[1:3] == ["SEA", "no"]
               for l in out)
    family = next(l for l in out if l.startswith("# n="))
    extra = next(l for l in out if l.startswith("# extra n="))
    assert family.startswith("# n=3 ")
    # SEA NO: RAW 0.90 -> 0.81, MKT 0.815 -> 0.6642
    assert extra.startswith("# extra n=1 ") and "SEA" in extra
    assert "RAW 0.8100" in extra and "MKT 0.6642" in extra


def test_the_prompt_names_the_extra_cities():
    prompt = (pathlib.Path(rainfreeze.__file__).parents[1] / "bin"
              / "daily-prompt.md").read_text()
    assert "SEA/PHIL/DEN" in prompt and "# extra" in prompt
