"""rainfreeze.py: mechanical RAW / MKT pre-regs for the KXRAIN family.

The rain family (DC / NYC / OKC) is the experiment's largest scored family
(n=64 by 10/16), scored as Brier for RAW (NWS "Today" PoP), MKT (the 12Z
board mid) and MINE. RAW and MKT need no judgment, yet on 10/16 no pre-regs
were frozen ("grids not pulled; time spent on LAX heat + diesel -> 10/16
UNSCORABLE for this family"), and 10/3-10/9 were lost the same way. These
tests pin a pipeline step that freezes both legs before the judgment step,
and a scorer that reads them back against Kalshi's results.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import rainfreeze


def period(name, start, pop, short, day=True):
    return {"number": 1, "name": name, "startTime": start, "isDaytime": day,
            "probabilityOfPrecipitation": {"unitCode": "wmoUnit:percent",
                                           "value": pop},
            "shortForecast": short, "detailedForecast": "long text"}


# shapes as wx._get receives them (Accept: application/ld+json -> top-level
# "periods"); the 10/15 DC freeze was Today 77 'Rain Showers', Tonight 27
FORECASTS = {
    "/gridpoints/LWX/97,69/forecast": {"periods": [
        period("Today", "2026-10-15T08:00:00-04:00", 77, "Rain Showers"),
        period("Tonight", "2026-10-15T18:00:00-04:00", 27, "Chance Showers",
               day=False),
        period("Friday", "2026-10-16T06:00:00-04:00", 5, "Sunny")]},
    "/gridpoints/OKX/33,37/forecast": {"properties": {"periods": [
        period("Today", "2026-10-15T08:00:00-04:00", None, "Mostly Sunny"),
        period("Tonight", "2026-10-15T18:00:00-04:00", 79,
               "Mostly Cloudy then Rain Showers", day=False)]}},
    "/gridpoints/OUN/94,90/forecast": {"periods": [
        period("Today", "2026-10-15T07:00:00-05:00", 96, "Rain")]},
}

BOARDS = {
    "KXRAIN-26OCT15-DC": {"ticker": "KXRAIN-26OCT15-DC", "status": "active",
                          "yes_bid_dollars": "0.6600",
                          "yes_ask_dollars": "0.6700"},
    "KXRAIN-26OCT15-NYC": {"ticker": "KXRAIN-26OCT15-NYC", "status": "active",
                           "yes_bid_dollars": "0.1100",
                           "yes_ask_dollars": "0.1200"},
    "KXRAIN-26OCT15-OKC": {"ticker": "KXRAIN-26OCT15-OKC", "status": "active",
                           "yes_bid_dollars": "0.9900",
                           "yes_ask_dollars": "1.0000"},
}


@pytest.fixture
def apis(tmp_path, monkeypatch):
    calls = []

    def nws(path, tries=3):
        calls.append(path)
        if path not in FORECASTS:
            raise OSError("nws down")
        return FORECASTS[path]

    def market(ticker, tries=4):
        calls.append(ticker)
        if ticker not in BOARDS:
            raise OSError("kalshi down")
        return BOARDS[ticker]
    monkeypatch.setattr(rainfreeze.wx, "_get", nws)
    monkeypatch.setattr(rainfreeze.kalshi, "get_market", market)
    monkeypatch.setattr(rainfreeze, "JOURNAL", tmp_path / "rain-freeze.jsonl")
    return calls


def rows():
    return [json.loads(l) for l in
            rainfreeze.JOURNAL.read_text().splitlines() if l.strip()]


def test_freeze_records_raw_and_board_per_city(apis):
    ok, failed = rainfreeze.freeze()
    assert (ok, failed) == (3, [])
    by_city = {r["city"]: r for r in rows()}
    dc = by_city["DC"]
    assert dc["date"] == "2026-10-15"
    assert dc["ticker"] == "KXRAIN-26OCT15-DC"
    assert dc["raw"] == 0.77
    assert (dc["yes_bid"], dc["yes_ask"]) == ("0.6600", "0.6700")
    assert dc["grid"] == "LWX 97,69"
    # first periods kept verbatim for the record (Tonight is the straddle
    # flag), the long detailedForecast dropped
    assert [p["name"] for p in dc["periods"]] == ["Today", "Tonight"]
    assert dc["periods"][1]["pop"] == 27
    assert dc["periods"][1]["short"] == "Chance Showers"
    assert "fetched_at" in dc


def test_null_pop_is_zero_and_properties_shape_is_read(apis):
    rainfreeze.freeze()
    nyc = {r["city"]: r for r in rows()}["NYC"]
    assert nyc["raw"] == 0.0
    assert nyc["periods"][0]["pop"] is None


def test_okc_dates_by_its_own_local_start(apis):
    rainfreeze.freeze()
    okc = {r["city"]: r for r in rows()}["OKC"]
    assert okc["ticker"] == "KXRAIN-26OCT15-OKC" and okc["raw"] == 0.96


def test_raw_is_none_when_the_day_period_is_gone():
    # an evening run: first period is Tonight, the day's PoP no longer shown
    periods = [period("Tonight", "2026-10-15T18:00:00-04:00", 40, "Rain",
                      day=False),
               period("Friday", "2026-10-16T06:00:00-04:00", 5, "Sunny")]
    assert rainfreeze.raw_pop(periods, "2026-10-15") is None


def test_nws_down_still_freezes_the_board_and_reports(apis, monkeypatch):
    del FORECASTS["/gridpoints/OUN/94,90/forecast"]
    try:
        ok, failed = rainfreeze.freeze(today="2026-10-15")
    finally:
        FORECASTS["/gridpoints/OUN/94,90/forecast"] = {"periods": [
            period("Today", "2026-10-15T07:00:00-05:00", 96, "Rain")]}
    assert failed == ["OKC"]
    okc = {r["city"]: r for r in rows()}["OKC"]
    assert okc["raw"] is None and okc["yes_ask"] == "1.0000"


def test_main_exits_1_only_when_nothing_answered(apis, monkeypatch, capsys):
    monkeypatch.setattr(rainfreeze.wx, "_get",
                        lambda p, tries=3: (_ for _ in ()).throw(OSError()))
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t, tries=4: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SystemExit) as e:
        rainfreeze.main(["freeze"])
    assert e.value.code == 1
    assert not rainfreeze.JOURNAL.exists()


def test_score_brier_per_leg_first_freeze_wins(apis, monkeypatch, capsys):
    rainfreeze.freeze()
    # a later re-run the same day must not overwrite the binding freeze
    BOARDS["KXRAIN-26OCT15-DC"]["yes_bid_dollars"] = "0.9000"
    BOARDS["KXRAIN-26OCT15-DC"]["yes_ask_dollars"] = "0.9100"
    try:
        rainfreeze.freeze()
    finally:
        BOARDS["KXRAIN-26OCT15-DC"]["yes_bid_dollars"] = "0.6600"
        BOARDS["KXRAIN-26OCT15-DC"]["yes_ask_dollars"] = "0.6700"
    results = {"KXRAIN-26OCT15-DC": "yes", "KXRAIN-26OCT15-NYC": "no",
               "KXRAIN-26OCT15-OKC": ""}
    monkeypatch.setattr(rainfreeze.kalshi, "get_market",
                        lambda t, tries=4: {"ticker": t, "result": results[t]})
    rainfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    by_city = {l.split()[1]: l for l in out if l[:4].isdigit()}
    # the 10/16 brief's hand scoring of the 10/15 pre-regs:
    # DC YES RAW 0.77 Brier 0.0529 / MKT 0.665 0.1122
    assert "yes" in by_city["DC"]
    assert "RAW 0.77 0.0529" in by_city["DC"]
    assert "MKT 0.665 0.1122" in by_city["DC"]
    # NYC NO RAW 0.00 0.0000 / MKT 0.115 0.0132
    assert "RAW 0.00 0.0000" in by_city["NYC"]
    assert "MKT 0.115 0.0132" in by_city["NYC"]
    assert "pending" in by_city["OKC"]
    summary = [l for l in out if l.startswith("# n=")][0]
    assert summary.startswith("# n=2")
    assert "RAW 0.0265" in summary and "MKT 0.0627" in summary


def test_daily_freezes_rain_before_the_judgment_step():
    daily = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    step = daily.index("run_step rainfreeze")
    assert "kalshi/rainfreeze.py freeze" in daily[step:daily.index("\n", step)]
    assert step < daily.index("run_step claude")


def test_judgment_allowlist_grants_the_cli():
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(python3 kalshi/rainfreeze.py *)" in allow


def test_usage_on_unknown_command():
    with pytest.raises(SystemExit) as e:
        rainfreeze.main(["melt"])
    assert "freeze" in str(e.value.code)
