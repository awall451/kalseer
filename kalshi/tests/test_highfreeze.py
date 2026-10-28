"""highfreeze.py: mechanical RAW / MKT pre-regs for KXHIGH daily-high boards.

lax-santa-ana-heat (watchlist, 10/17): "NO 10/17 grid pulled this run -> no
RAW/MINE pre-reg; log board only (unscorable for RAW/MINE)" while the rule
says "need >=3 Santa Ana days with grid vs CLI before pricing a bias". The
grid-vs-settlement ledger is mechanical, like the rain family's RAW/MKT legs
(rainfreeze.py), so a run that skips the grid must not cost a datum. These
tests pin a pipeline step that freezes the NWS grid high and the bucket board
before the judgment step, and a scorer that reads them back against Kalshi's
settled expiration_value (the official max, whatever the source).
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import highfreeze


def period(name, start, temp, short, day=True):
    return {"number": 1, "name": name, "startTime": start, "isDaytime": day,
            "temperature": temp, "temperatureUnit": "F",
            "shortForecast": short, "detailedForecast": "long text"}


# 10/16 LOX grid: "Friday high near 92"
FORECASTS = {
    "/gridpoints/LOX/148,41/forecast": {"periods": [
        period("Today", "2026-10-16T06:00:00-07:00", 92, "Sunny"),
        period("Tonight", "2026-10-16T18:00:00-07:00", 68, "Clear",
               day=False)]},
    "/gridpoints/OKX/33,37/forecast": {"properties": {"periods": [
        period("Tonight", "2026-10-16T18:00:00-04:00", 51, "Clear", day=False),
        period("Saturday", "2026-10-17T06:00:00-04:00", 63, "Sunny")]}},
}


def mkt(ticker, kind, floor, cap, bid, ask, result="", value=None):
    return {"ticker": ticker, "strike_type": kind, "floor_strike": floor,
            "cap_strike": cap, "yes_bid_dollars": bid, "yes_ask_dollars": ask,
            "result": result, "expiration_value": value}


# the 10/16 board as the watchlist froze it by hand (~12:05Z)
LAX16 = [mkt("KXHIGHLAX-26OCT16-T87", "less", None, 87, "0.0000", "0.0100"),
         mkt("KXHIGHLAX-26OCT16-B87.5", "between", 87, 88, "0.0000", "0.0100"),
         mkt("KXHIGHLAX-26OCT16-B89.5", "between", 89, 90, "0.0100", "0.0200"),
         mkt("KXHIGHLAX-26OCT16-B91.5", "between", 91, 92, "0.0200", "0.0300"),
         mkt("KXHIGHLAX-26OCT16-B93.5", "between", 93, 94, "0.0900", "0.1000"),
         mkt("KXHIGHLAX-26OCT16-T94", "greater", 94, None, "0.8800", "0.9000")]

EVENTS = {"KXHIGHLAX-26OCT16": {"markets": LAX16}}


@pytest.fixture
def apis(tmp_path, monkeypatch):
    calls = []

    def nws(path, tries=3):
        calls.append(path)
        if path not in FORECASTS:
            raise OSError("nws down")
        return FORECASTS[path]

    def event(ticker):
        calls.append(ticker)
        if ticker not in EVENTS:
            raise OSError("kalshi down")
        return EVENTS[ticker]
    monkeypatch.setattr(highfreeze.wx, "_get", nws)
    monkeypatch.setattr(highfreeze.kalshi, "get_event", event)
    monkeypatch.setattr(highfreeze, "JOURNAL", tmp_path / "high-freeze.jsonl")
    monkeypatch.setattr(highfreeze, "CITIES", {"LAX": ("LOX", 148, 41),
                                               "NY": ("OKX", 33, 37)})
    monkeypatch.setattr(highfreeze, "EXTRA", {})
    return calls


def rows():
    return [json.loads(l) for l in
            highfreeze.JOURNAL.read_text().splitlines() if l.strip()]


def settle(value, winner):
    EVENTS["KXHIGHLAX-26OCT16"] = {"markets": [
        dict(m, result="yes" if m["ticker"].endswith(winner) else "no",
             expiration_value=value, yes_bid_dollars="0.0000",
             yes_ask_dollars="1.0000") for m in LAX16]}


@pytest.fixture(autouse=True)
def unsettled():
    EVENTS["KXHIGHLAX-26OCT16"] = {"markets": LAX16}


def test_freeze_records_grid_high_and_buckets(apis):
    ok, failed = highfreeze.freeze()
    lax = {r["city"]: r for r in rows()}["LAX"]
    assert lax["date"] == "2026-10-16"
    assert lax["event"] == "KXHIGHLAX-26OCT16"
    assert lax["grid"] == "LOX 148,41"
    assert lax["high"] == 92
    assert lax["short"] == "Sunny"
    top = lax["buckets"][-1]
    assert top == {"ticker": "KXHIGHLAX-26OCT16-T94", "strike_type": "greater",
                   "floor": 94, "cap": None, "yes_bid": "0.8800",
                   "yes_ask": "0.9000"}
    assert len(lax["buckets"]) == 6


def test_high_is_todays_daytime_period_not_tonights(apis):
    # OKX's first period is Tonight (run after 18:00 local): today's high has
    # rolled off, and the date is the night's, so high is None
    highfreeze.freeze()
    ny = {r["city"]: r for r in rows()}["NY"]
    assert ny["date"] == "2026-10-16"
    assert ny["high"] is None
    assert ny["event"] == "KXHIGHNY-26OCT16"


def test_failed_board_still_freezes_the_grid_leg(apis):
    ok, failed = highfreeze.freeze()
    assert ok == 1
    assert failed == ["NY"]
    ny = {r["city"]: r for r in rows()}["NY"]
    assert ny["buckets"] == []


def test_raw_bucket_probabilities_use_integer_degree_edges():
    b = {b["ticker"]: b for b in highfreeze._buckets(LAX16)}
    p = highfreeze.raw_p
    # 95+ means X > 94.5; with mu 92, sd 3: 1 - Phi(0.8333) = 0.2023
    assert p(b["KXHIGHLAX-26OCT16-T94"], 92) == pytest.approx(0.2023, abs=1e-4)
    # "86 or below" means X < 86.5
    assert p(b["KXHIGHLAX-26OCT16-T87"], 92) == pytest.approx(0.0334, abs=1e-4)
    # "91 to 92" means 90.5 < X < 92.5: Phi(0.1667) - Phi(-0.5)
    assert p(b["KXHIGHLAX-26OCT16-B91.5"], 92) == pytest.approx(0.2577,
                                                                abs=1e-4)
    assert sum(p(x, 92) for x in b.values()) == pytest.approx(1.0)


def test_score_reports_grid_error_and_both_legs(apis, capsys):
    highfreeze.freeze()
    settle("99.00", "-T94")
    highfreeze.score()
    out = capsys.readouterr().out.splitlines()
    line = [l for l in out if "LAX" in l][0]
    assert line.startswith("2026-10-16  LAX  99")
    assert "grid 92 err -7" in line
    mids = [0.005, 0.005, 0.015, 0.025, 0.095, 0.89]
    mkt_brier = sum(m * m for m in mids[:-1]) + (1 - mids[-1]) ** 2
    assert f"MKT p 0.8900 B {mkt_brier:.4f}" in line
    assert "RAW p 0.2023" in line


def test_score_summary_counts_settled_days_only(apis, capsys):
    highfreeze.freeze()
    settle("99.00", "-T94")
    highfreeze.score()
    summary = capsys.readouterr().out.splitlines()[-1]
    assert summary.startswith("# n=1 ")
    assert "grid bias -7.0F" in summary
    assert "MAE 7.0F" in summary


def test_score_marks_unsettled_days_pending(apis, capsys):
    highfreeze.freeze()
    highfreeze.score()
    line = [l for l in capsys.readouterr().out.splitlines() if "LAX" in l][0]
    assert "pending" in line
    assert "grid 92" in line


def test_first_freeze_per_city_day_is_binding(apis):
    highfreeze.freeze()
    FORECASTS["/gridpoints/LOX/148,41/forecast"]["periods"][0]["temperature"] = 97
    try:
        highfreeze.freeze()
    finally:
        FORECASTS["/gridpoints/LOX/148,41/forecast"]["periods"][0][
            "temperature"] = 92
    lax = [r for r in highfreeze.frozen() if r["city"] == "LAX"]
    assert len(lax) == 1
    assert lax[0]["high"] == 92


def test_main_freeze_exits_nonzero_only_when_nothing_answered(apis,
                                                              monkeypatch,
                                                              capsys):
    highfreeze.main(["freeze"])
    assert "1/2 cities frozen in full; failed: NY" in capsys.readouterr().out
    monkeypatch.setattr(highfreeze, "CITIES", {"XX": ("BAD", 1, 1)})
    with pytest.raises(SystemExit) as e:
        highfreeze.main(["freeze"])
    assert e.value.code == 1


def test_usage(apis):
    with pytest.raises(SystemExit) as e:
        highfreeze.main([])
    assert "freeze" in str(e.value.code)


# KXHIGHTDC / KXHIGHTOKC settle on CLIDCA / CLIOKC ("the maximum temperature
# recorded at Washington DC (CLIDCA) ..."), the same CLI stations the rain
# family's KXRAIN DC / OKC settle on — so the grids rainfreeze already
# freezes for those stations are the grids for the high boards too, and the
# temperature ledger grows without an api.weather.gov /points lookup.
def test_dc_and_okc_highs_reuse_the_rain_family_grids():
    import rainfreeze
    assert highfreeze.CITIES["TDC"] == rainfreeze.CITIES["DC"]
    assert highfreeze.CITIES["TOKC"] == rainfreeze.CITIES["OKC"]
    assert highfreeze.CITIES["LAX"] == ("LOX", 148, 41)
    assert highfreeze.CITIES["NY"] == ("OKX", 33, 37)


def test_new_city_keys_build_the_live_event_tickers():
    assert highfreeze.event_ticker("TDC", "2026-10-19") == "KXHIGHTDC-26OCT19"
    assert (highfreeze.event_ticker("TOKC", "2026-10-19")
            == "KXHIGHTOKC-26OCT19")
