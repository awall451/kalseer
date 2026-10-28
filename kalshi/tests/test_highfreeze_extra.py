"""highfreeze.py EXTRA cities: the busiest KXHIGH boards outside its four.

highfreeze covers LAX / NY / TDC / TOKC (the Santa Ana ledger plus the rain
family's stations), but those aren't where the KXHIGH volume is. Kalshi's 24h
volume at 06Z 10/28 on the 10/28 events: MIA 13,659, CHI 8,162, AUS 7,471,
against TOKC's 1,960 and TDC's 1,627. They settle on CLIMIA / CLIMDW
(Midway) / CLIAUS, so grid-vs-settled-max and RAW vs MKT are the same
calibration question with more volume behind it. As in rainfreeze (#97),
their grids are resolved from the CLI station's coordinates via NWS /points
each run and journaled with the row, and their scores get their own
`# extra` summary, so the family's summary line stays LAX/NY/TDC/TOKC.
"""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_highfreeze import (EVENTS, FORECASTS, apis, highfreeze, mkt,  # noqa: F401
                             period, rows, settle, unsettled)

MIA = (25.7881, -80.3169)
POINTS = "/points/25.7881,-80.3169"
MIA16 = [mkt("KXHIGHMIA-26OCT16-T83", "less", None, 83, "0.0400", "0.0600"),
         mkt("KXHIGHMIA-26OCT16-B83.5", "between", 83, 84, "0.3000", "0.3200"),
         mkt("KXHIGHMIA-26OCT16-B85.5", "between", 85, 86, "0.4400", "0.4600"),
         mkt("KXHIGHMIA-26OCT16-T86", "greater", 86, None, "0.1700", "0.1900")]


@pytest.fixture
def mia(apis, monkeypatch):
    monkeypatch.setattr(highfreeze, "EXTRA", {"MIA": MIA})
    monkeypatch.setitem(FORECASTS, POINTS, {
        "gridId": "MFL", "gridX": 106, "gridY": 51})
    monkeypatch.setitem(FORECASTS, "/gridpoints/MFL/106,51/forecast", {
        "periods": [
            period("Today", "2026-10-16T06:00:00-04:00", 85, "Mostly Sunny"),
            period("Tonight", "2026-10-16T18:00:00-04:00", 74, "Clear",
                   day=False)]})
    monkeypatch.setitem(EVENTS, "KXHIGHMIA-26OCT16", {"markets": MIA16})
    return apis


def test_the_extra_cities_are_the_busiest_boards():
    assert set(highfreeze.EXTRA) == {"MIA", "CHI", "AUS"}
    assert highfreeze.event_ticker("CHI", "2026-10-28") == "KXHIGHCHI-26OCT28"
    assert not set(highfreeze.EXTRA) & set(highfreeze.CITIES)


def test_extra_city_grid_is_resolved_and_journaled(mia):
    ok, failed = highfreeze.freeze()
    assert (ok, failed) == (2, ["NY"])
    r = {x["city"]: x for x in rows()}["MIA"]
    assert r["grid"] == "MFL 106,51" and r["high"] == 85
    assert r["event"] == "KXHIGHMIA-26OCT16" and len(r["buckets"]) == 4
    assert POINTS in mia


def test_a_geojson_points_reply_also_resolves(mia, monkeypatch):
    monkeypatch.setitem(FORECASTS, POINTS, {"properties": {
        "gridId": "MFL", "gridX": 106, "gridY": 51}})
    highfreeze.freeze()
    assert {x["city"]: x for x in rows()}["MIA"]["grid"] == "MFL 106,51"


def test_a_failed_points_lookup_keeps_the_board(mia, monkeypatch):
    monkeypatch.delitem(FORECASTS, POINTS)
    ok, failed = highfreeze.freeze(today="2026-10-16")
    assert ok == 1 and failed == ["NY", "MIA"]
    r = {x["city"]: x for x in rows()}["MIA"]
    assert r["high"] is None and len(r["buckets"]) == 4
    assert r["grid"] == "points 25.7881,-80.3169"


def test_main_counts_the_extra_cities(mia, capsys):
    highfreeze.main(["freeze"])
    assert "2/3 cities frozen in full; failed: NY" in capsys.readouterr().out


def test_extra_cities_score_in_their_own_summary(mia, monkeypatch, capsys):
    highfreeze.freeze()
    settle("99.00", "-T94")
    monkeypatch.setitem(EVENTS, "KXHIGHMIA-26OCT16", {"markets": [
        dict(m, result="yes" if m["ticker"].endswith("-B85.5") else "no",
             expiration_value="86.00") for m in MIA16]})
    highfreeze.score()
    out = capsys.readouterr().out.splitlines()
    assert any(l.startswith("2026-10-16  MIA  86  grid 85 err -1")
               for l in out)
    family = next(l for l in out if l.startswith("# n="))
    extra = next(l for l in out if l.startswith("# extra n="))
    # the family line is LAX alone (grid 92 vs 99), MIA is only in extra
    assert family.startswith("# n=1 ") and "grid bias -7.0F" in family
    assert extra.startswith("# extra n=1 ") and "MIA" in extra
    assert "grid bias -1.0F" in extra and "RAW B" in extra
    assert any(l.startswith("# MIA: n=1 grid bias -1.0F") for l in out)


def test_the_prompt_names_the_extra_cities():
    prompt = (pathlib.Path(highfreeze.__file__).parents[1] / "bin"
              / "daily-prompt.md").read_text()
    assert "MIA/CHI/AUS" in prompt
