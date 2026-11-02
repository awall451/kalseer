"""rainfreeze.py BUSY cities: the day's busiest KXRAIN boards, whichever they are.

The fixed EXTRA cities (SEA/PHIL/DEN) were the busiest boards on 10/27, but
rain volume follows the weather. The 11/1 scan's rain candidates were
Lexington (10,943), Milwaukee (9,816) and Indianapolis (8,815), none of them
frozen, and the brief said "I did not research the RT, Lexington/Indy rain,
or LAX/NY high boards today". At 06Z 11/2 KXRAIN listed 37 cities. So each
run also freezes the BUSY (4) busiest cities outside CITIES/EXTRA by summed
24h volume. The station comes from the board's own rules ("total
precipitation at CLILEX in Lexington"), its coordinates from NWS
/stations/K<code>, then /points as for EXTRA. Their rows score in the
`# extra` summaries, so the family's lines stay DC/NYC/OKC.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_rainfreeze import (BOARDS, FORECASTS, apis, period,  # noqa: F401
                             rainfreeze, rows)


def board(ticker, vol, city="Lexington", station="CLILEX"):
    day = "Oct 15, 2026"
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0],
            "volume_24h_fp": vol, "yes_bid_dollars": "0.4000",
            "yes_ask_dollars": "0.4200",
            "rules_primary": f"If the total precipitation at {station} in "
                             f"{city} in {day} is strictly greater than 0 "
                             "inches, then the market resolves to Yes."}


LISTED = [
    board("KXRAIN-26OCT15-LEX", "10942.91"),
    board("KXRAIN-26OCT16-LEX", "3028.32"),
    board("KXRAIN-26OCT15-MKE", "9816.22", "Milwaukee", "CLIMKE"),
    board("KXRAIN-26OCT15-IND", "8815.30", "Indianapolis", "CLIIND"),
    board("KXRAIN-26OCT15-EWR", "41.93", "Newark", "CLIEWR"),
    # family / EXTRA cities never count as busy, however busy
    board("KXRAIN-26OCT15-SEA", "99999.00", "Seattle", "CLISEA"),
    board("KXRAIN-26OCT15-NYC", "99999.00", "New York City", "CLINYC"),
]


@pytest.fixture
def busy(apis, monkeypatch):
    monkeypatch.setattr(rainfreeze, "BUSY", 1)
    monkeypatch.setattr(rainfreeze, "EXTRA", {"SEA": (47.4444, -122.3139)})
    monkeypatch.setattr(rainfreeze.kalshi, "get_markets",
                        lambda **kw: list(LISTED))
    monkeypatch.setitem(FORECASTS, "/stations/KLEX", {
        "geometry": {"type": "Point", "coordinates": [-84.6114, 38.0408]}})
    monkeypatch.setitem(FORECASTS, "/points/38.0408,-84.6114", {
        "gridId": "LMK", "gridX": 81, "gridY": 70})
    monkeypatch.setitem(FORECASTS, "/gridpoints/LMK/81,70/forecast", {
        "periods": [
            period("Today", "2026-10-15T08:00:00-04:00", 60, "Showers"),
            period("Tonight", "2026-10-15T18:00:00-04:00", 30, "Showers",
                   day=False)]})
    monkeypatch.setitem(BOARDS, "KXRAIN-26OCT15-LEX", LISTED[0])
    return apis


def test_busiest_ranks_by_summed_volume_outside_family_and_extra(busy):
    assert rainfreeze.busiest(3) == [("LEX", "LEX"), ("MKE", "MKE"),
                                     ("IND", "IND")]


def test_busiest_is_empty_when_off_or_the_board_fails(busy, monkeypatch,
                                                      capsys):
    assert rainfreeze.busiest(0) == []

    def down(**kw):
        raise OSError("kalshi down")
    monkeypatch.setattr(rainfreeze.kalshi, "get_markets", down)
    assert rainfreeze.busiest(4) == []
    assert "KXRAIN listing failed" in capsys.readouterr().err


def test_a_board_without_a_cli_station_in_its_rules_is_skipped(busy,
                                                               monkeypatch):
    odd = dict(LISTED[0], rules_primary="Resolves on something else.")
    monkeypatch.setattr(rainfreeze.kalshi, "get_markets",
                        lambda **kw: [odd, LISTED[2]])
    assert rainfreeze.busiest(4) == [("MKE", "MKE")]


def test_busy_city_is_frozen_with_its_station_and_grid(busy):
    ok, failed = rainfreeze.freeze()
    assert failed == ["SEA"]  # no SEA forecast in this fixture
    r = {x["city"]: x for x in rows()}["LEX"]
    assert r["station"] == "CLILEX" and r["grid"] == "LMK 81,70"
    assert r["raw"] == 0.6 and r["ticker"] == "KXRAIN-26OCT15-LEX"
    assert (r["yes_bid"], r["yes_ask"]) == ("0.4000", "0.4200")
    assert "/stations/KLEX" in busy


def test_a_failed_station_lookup_keeps_the_board(busy, monkeypatch):
    monkeypatch.delitem(FORECASTS, "/stations/KLEX")
    rainfreeze.freeze(today="2026-10-15")
    r = {x["city"]: x for x in rows()}["LEX"]
    assert r["grid"] == "station KLEX" and r["raw"] is None
    assert r["yes_bid"] == "0.4000"


def test_main_counts_busy_cities_in_the_total(busy, capsys):
    rainfreeze.main(["freeze"])
    out = capsys.readouterr().out
    assert "rainfreeze: 4/5 cities frozen in full; failed: SEA" in out


def test_busy_cities_score_in_the_extra_summary(busy, monkeypatch, capsys):
    rainfreeze.freeze()
    results = {"KXRAIN-26OCT15-DC": "yes", "KXRAIN-26OCT15-NYC": "no",
               "KXRAIN-26OCT15-OKC": "yes", "KXRAIN-26OCT15-LEX": "yes"}
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t, tries=4: {"ticker": t,
                                            "result": results.get(t, "")})
    rainfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    assert next(l for l in out if l.startswith("# n=")).startswith("# n=3 ")
    extra = next(l for l in out if l.startswith("# extra n="))
    # LEX YES: RAW 0.60 -> 0.16, MKT 0.41 -> 0.3481
    assert extra.startswith("# extra n=1 ") and "LEX" in extra
    assert "RAW 0.1600" in extra and "MKT 0.3481" in extra


def test_the_prompt_mentions_the_busy_cities():
    prompt = (pathlib.Path(rainfreeze.__file__).parents[1] / "bin"
              / "daily-prompt.md").read_text()
    assert "4 busiest other KXRAIN cities" in prompt and "BUSY" in prompt
