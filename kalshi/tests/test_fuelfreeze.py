"""fuelfreeze.py: mechanical RW / MOM / DRIFT odds on every open fuel strike.

aaa-gas-tracking-oct (watchlist, 10/19): "DIVERGENCE DATUM #4 RESOLVED:
4.2953 > 4.2900 -> board (0.96) right, DRIFT/MOM (~0.5) wrong; deference
lesson holds again (board now 3-1 on divergence datums)". Each datum is hand
arithmetic: a k-print normal around each model's centre, read against the
board at a strike, frozen in watchlist prose and scored by hand days later
(datum #1 was still "now very likely RW" a week on). The models and the board
are mechanical, so the pipeline freezes them; these tests pin the horizon
maths, the binding first freeze, and a scorer that tallies board-vs-model
divergences against Kalshi's settled results.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze
import fuelscore


def row(date, regular, diesel):
    return {"date": date, "prices": {"current": {
        "regular": regular, "mid_grade": "$4.8000", "premium": "$5.2000",
        "diesel": diesel}}}


# regular, cents changes 10/14..10/18: -1.0 -0.5 -1.5 -0.5 -1.0
# (mean -0.9, sample sd 0.4183); diesel flat to the last digit
SERIES = [("2026-10-13", "$4.3400"), ("2026-10-14", "$4.3300"),
          ("2026-10-15", "$4.3250"), ("2026-10-16", "$4.3100"),
          ("2026-10-17", "$4.3050"), ("2026-10-18", "$4.2950")]


def mkt(ticker, floor, bid, ask, result="", value=None):
    return {"ticker": ticker, "event_ticker": ticker.rsplit("-", 1)[0],
            "strike_type": "greater", "floor_strike": floor,
            "cap_strike": None, "yes_bid_dollars": bid,
            "yes_ask_dollars": ask, "result": result,
            "expiration_value": value}


# the weekly settles on the 10/20 print: k = 2 prints from the 10/18 base
GASW = [mkt("KXAAAGASW-26OCT20-4.3000", 4.3, "0.1400", "0.1700"),
        mkt("KXAAAGASW-26OCT20-4.2900", 4.29, "0.9500", "0.9700"),
        mkt("KXAAAGASW-26OCT20-4.2800", 4.28, "0.9900", "1.0000")]
OPEN = {"KXAAAGASW": GASW,
        # settles on the 10/18 print already journaled: nothing left to model
        "KXAAAGASD": [mkt("KXAAAGASD-26OCT18-4.2950", 4.295, "0.0000",
                          "1.0000")],
        "KXDIESELW": [mkt("KXDIESELW-26OCT20-T6.30", 6.30, "0.4000",
                          "0.6000")]}
EVENTS = {}


@pytest.fixture
def apis(tmp_path, monkeypatch):
    prints = tmp_path / "prints.jsonl"
    prints.write_text("".join(
        json.dumps(row(d, p, "$6.3000")) + "\n" for d, p in SERIES))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    monkeypatch.setattr(fuelfreeze, "JOURNAL", tmp_path / "fuel-freeze.jsonl")
    calls = []

    def markets(series_ticker=None, status=None):
        calls.append((series_ticker, status))
        if series_ticker == "KXDIESELD":
            raise OSError("kalshi down")
        return OPEN.get(series_ticker, [])

    def event(ticker):
        calls.append(ticker)
        if ticker not in EVENTS:
            raise OSError("kalshi down")
        return EVENTS[ticker]
    monkeypatch.setattr(fuelfreeze.kalshi, "get_markets", markets)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event", event)
    monkeypatch.setattr(fuelfreeze.kalshi, "settled_markets",
                        lambda *a, **kw: [])
    EVENTS.clear()
    return calls


def frozen_rows():
    return [json.loads(l) for l in
            fuelfreeze.JOURNAL.read_text().splitlines() if l.strip()]


def settle(value, winners):
    EVENTS["KXAAAGASW-26OCT20"] = {"markets": [
        dict(m, result="yes" if m["floor_strike"] in winners else "no",
             expiration_value=value) for m in GASW]}


def test_freeze_records_board_and_k_print_model_odds(apis):
    events, failed = fuelfreeze.freeze()
    rows = {r["event"]: r for r in frozen_rows()}
    gas = rows["KXAAAGASW-26OCT20"]
    assert gas["grade"] == "regular"
    assert gas["date"] == "2026-10-20"
    assert gas["base_date"] == "2026-10-18" and gas["base"] == "4.2950"
    assert gas["k"] == 2 and gas["window"] == 5
    # centres: RW today; MOM k x today's change; DRIFT k x the window mean
    assert gas["centre"] == {"RW": "4.2950", "MOM": "4.2750",
                             "DRIFT": "4.2770"}
    assert gas["sd"] == pytest.approx(0.4183 * 2 ** 0.5, abs=1e-3)
    s = {x["floor"]: x for x in gas["strikes"]}
    assert s[4.29]["yes_bid"] == "0.9500" and s[4.29]["yes_ask"] == "0.9700"
    # P(print > 4.29): RW 0.5c over a 0.59c k-print sd; DRIFT 1.3c under
    assert s[4.29]["p"]["RW"] == pytest.approx(0.801, abs=0.002)
    assert s[4.29]["p"]["DRIFT"] == pytest.approx(0.014, abs=0.002)
    assert s[4.29]["p"]["MOM"] < s[4.29]["p"]["DRIFT"]


def test_freeze_skips_events_the_journal_already_settles(apis):
    fuelfreeze.freeze()
    assert "KXAAAGASD-26OCT18" not in {r["event"] for r in frozen_rows()}


def test_a_flat_series_still_prices_with_a_floor_sd(apis):
    # diesel never moved: sd 0 would divide by zero; the floor keeps it a
    # near-step at the centre instead
    fuelfreeze.freeze()
    d = {r["event"]: r for r in frozen_rows()}["KXDIESELW-26OCT20"]
    assert d["grade"] == "diesel"
    p = d["strikes"][0]["p"]
    assert p["RW"] == pytest.approx(0.5, abs=1e-9)  # 6.3000 at strike 6.30


def test_a_failed_series_does_not_stop_the_others(apis):
    events, failed = fuelfreeze.freeze()
    assert failed == ["KXDIESELD"]
    assert sorted(events) == ["KXAAAGASW-26OCT20", "KXDIESELW-26OCT20"]


def test_freeze_prints_board_model_divergences(apis, capsys):
    fuelfreeze.main(["freeze"])
    out = capsys.readouterr().out
    assert "fuelfreeze: 2 events frozen" in out
    # 4.29: board 0.96 vs DRIFT 0.01 / MOM ~0 -> a datum; RW 0.80 is not
    line = [l for l in out.splitlines() if "4.29 " in l][0]
    assert "board 0.96" in line and "DRIFT 0.01" in line
    assert "RW" not in line


def test_freeze_exits_1_when_nothing_answers(apis, monkeypatch):
    monkeypatch.setattr(fuelfreeze.kalshi, "get_markets",
                        lambda **kw: (_ for _ in ()).throw(OSError("down")))
    with pytest.raises(SystemExit) as e:
        fuelfreeze.main(["freeze"])
    assert e.value.code == 1


def test_score_reads_the_first_freeze_as_binding(apis, capsys):
    fuelfreeze.freeze()
    GASW[1]["yes_bid_dollars"] = "0.5000"
    try:
        fuelfreeze.freeze()
    finally:
        GASW[1]["yes_bid_dollars"] = "0.9500"
    settle("4.2953", {4.29, 4.28})
    fuelfreeze.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "KXAAAGASW-26OCT20" in l][0]
    assert line.startswith("2026-10-20")
    assert "4.2953" in line
    # board mids 0.155 / 0.96 / 0.995 vs outcomes NO / YES / YES
    board = (0.155 ** 2 + 0.04 ** 2 + 0.005 ** 2) / 3
    assert f"BOARD {board:.4f}" in line


def test_score_tallies_divergences_by_closeness(apis, capsys):
    fuelfreeze.freeze()
    settle("4.2953", {4.29, 4.28})
    fuelfreeze.score()
    out = capsys.readouterr().out
    summary = [l for l in out.splitlines() if l.startswith("# divergences")][0]
    # 4.29 YES: board 0.96 beats DRIFT 0.01 and MOM ~0; 4.28 YES: board 0.995
    # beats DRIFT and MOM there too (both well under 0.75); RW never diverges
    assert "board-DRIFT 2-0" in summary
    assert "board-MOM 2-0" in summary
    assert "board-RW 0-0" in summary


def test_score_marks_unsettled_events_pending(apis, capsys):
    fuelfreeze.freeze()
    fuelfreeze.score()
    out = capsys.readouterr().out
    assert any(l.startswith("2026-10-20") and "pending" in l
               for l in out.splitlines() if "KXAAAGASW" in l)


def test_fuelfreeze_step_runs_after_aaa_before_judgment():
    sh = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    step = sh.index("run_step fuelfreeze python3 kalshi/fuelfreeze.py freeze")
    assert sh.index("run_step aaa ") < step < sh.index("run_step claude ")


def test_fuelfreeze_cli_grant_present():
    settings = pathlib.Path(__file__).parents[2] / ".claude" / "settings.json"
    allow = json.loads(settings.read_text())["permissions"]["allow"]
    assert "Bash(python3 kalshi/fuelfreeze.py *)" in allow
