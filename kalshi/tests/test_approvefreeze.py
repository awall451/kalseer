"""approvefreeze.py: mechanical RW / EMP pre-regs on the daily RCP approval board.

KXTRUMPAPPROVE is one of the busiest boards in every scan (20-58k contracts a
day on single buckets), and the judgment step passes on it every run because
"we still can't read its source" (RCP is 403 server-side; watchlist operator
item #20). But Kalshi's own settled expiration_values ARE the RCP series, one
per day since early September, so a no-change walk and the empirical
distribution of daily moves can be frozen against the board every morning
and scored once it settles. These tests pin that step and its scorer.
"""

import json
import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import approvefreeze as af

# settled RCP averages, Kalshi expiration_values 10/14 .. 10/25
SERIES = {"2026-10-14": "38.6", "2026-10-15": "38.8", "2026-10-16": "38.7",
          "2026-10-17": "38.7", "2026-10-18": "38.9", "2026-10-19": "38.9",
          "2026-10-20": "38.8", "2026-10-21": "38.3", "2026-10-22": "38.4",
          "2026-10-23": "38.8", "2026-10-24": "38.8", "2026-10-25": "38.5"}


def ev(day):
    return "KXTRUMPAPPROVE-" + af.dt.date.fromisoformat(day).strftime(
        "%y%b%d").upper()


def mkt(event, suffix, kind, floor, cap, bid="", ask="", result="",
        value=None):
    return {"ticker": f"{event}-{suffix}", "event_ticker": event,
            "strike_type": kind, "floor_strike": floor, "cap_strike": cap,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "result": result,
            "expiration_value": value}


def settled_rows(series=SERIES):
    return [mkt(ev(d), f"E{v}", "between", v, v, result="yes", value=v)
            for d, v in series.items()]


E26 = ev("2026-10-26")
# the 10/26 board at ~06Z
BOARD26 = [mkt(E26, "U38.5", "less", None, 38.5, "0.3300", "0.3400"),
           mkt(E26, "E38.5", "between", 38.5, 38.5, "0.4000", "0.4100"),
           mkt(E26, "E38.6", "between", 38.6, 38.6, "0.1100", "0.1200"),
           mkt(E26, "E38.7", "between", 38.7, 38.7, "0.0500", "0.0700"),
           mkt(E26, "A38.7", "greater", 38.7, None, "0.0400", "0.0600")]


@pytest.fixture
def apis(tmp_path, monkeypatch):
    state = {"settled": settled_rows(), "open": list(BOARD26)}
    monkeypatch.setattr(af, "JOURNAL", tmp_path / "rcp" / "approve-freeze.jsonl")
    monkeypatch.setattr(af.kalshi, "settled_markets",
                        lambda series, **kw: state["settled"])
    monkeypatch.setattr(af.kalshi, "get_markets",
                        lambda **kw: state["open"])
    return state


def test_history_reads_tenths_per_day():
    h = af.history(settled_rows())
    assert h["2026-10-25"] == 385 and h["2026-10-21"] == 383 and len(h) == 12


def test_history_takes_percent_signs_and_skips_junk():
    # live 10/26: older settlements read '38.7%', which broke float()
    rows = settled_rows({"2026-10-24": "38.8%", "2026-10-25": "38.5"})
    rows.append(mkt(ev("2026-10-23"), "E1", "between", 1, 1, value="n/a"))
    assert af.history(rows) == {"2026-10-24": 388, "2026-10-25": 385}


def test_hits_follow_the_bucket_wording():
    less, between, greater = (af.bucket(m) for m in
                              (BOARD26[0], BOARD26[1], BOARD26[4]))
    assert af.hits(less, 384) and not af.hits(less, 385)
    assert af.hits(between, 385) and not af.hits(between, 386)
    assert af.hits(greater, 388) and not af.hits(greater, 387)


def test_k_day_changes_end_inside_the_window():
    h = af.history(settled_rows())
    assert af.changes(h, "2026-10-25", 1) == [2, -1, 0, 2, 0, -1, -5, 1, 4,
                                              0, -3]
    assert af.changes(h, "2026-10-25", 2)[:2] == [1, -1]


def test_rw_is_a_normal_on_tenths_with_edge_continuity():
    b = af.bucket(BOARD26[1])
    p = af.rw_p(b, 385, 2.0)
    assert p == pytest.approx(math.erf(0.5 / (2.0 * math.sqrt(2))))
    total = sum(af.rw_p(af.bucket(m), 385, 2.0) for m in
                [BOARD26[0], BOARD26[1], BOARD26[2], BOARD26[3], BOARD26[4]])
    assert total == pytest.approx(1.0)


def test_emp_is_the_smoothed_share_of_past_moves():
    b = af.bucket(BOARD26[1])
    chg = [0, 0, 1, -1, 2, -3]
    assert af.emp_p(b, 385, chg) == pytest.approx((2 + 0.5) / (6 + 1))
    assert af.emp_p(b, 385, chg[:af.EMP_MIN - 1]) is None


def test_freeze_journals_board_and_legs_against_the_last_settle(apis, capsys):
    ok, failed = af.freeze()
    assert ok == 1 and failed == []
    (row,) = [json.loads(l) for l in af.JOURNAL.read_text().splitlines()]
    assert row["event"] == E26 and row["date"] == "2026-10-26"
    assert row["base_day"] == "2026-10-25" and row["base"] == "38.5"
    assert row["k"] == 1 and row["n_emp"] == 11
    b = {x["ticker"]: x for x in row["buckets"]}
    assert b[f"{E26}-E38.5"]["yes_bid"] == "0.4000"
    assert sum(x["RW"] for x in row["buckets"]) == pytest.approx(1.0, abs=1e-3)
    assert sum(x["EMP"] for x in row["buckets"]) > 0.9
    out = capsys.readouterr().out
    assert E26 in out and "base 38.5" in out


def test_freeze_skips_an_event_the_history_already_settles(apis):
    apis["open"] = [mkt(ev("2026-10-25"), "E38.5", "between", 38.5, 38.5,
                        "0.9", "0.95")]
    ok, failed = af.freeze()
    assert ok == 0 and not af.JOURNAL.exists()


def test_freeze_without_history_records_the_board_only(apis):
    apis["settled"] = []
    ok, failed = af.freeze()
    (row,) = [json.loads(l) for l in af.JOURNAL.read_text().splitlines()]
    assert row["base"] is None and failed == [E26]
    assert all(x["RW"] is None and x["EMP"] is None for x in row["buckets"])


def test_score_rates_each_leg_on_the_winning_bucket(apis, capsys):
    af.freeze()
    settled = settled_rows()
    for m in BOARD26:
        won = m["ticker"].endswith("-U38.5")
        settled.append(dict(m, result="yes" if won else "no",
                            expiration_value="38.4"))
    apis["settled"] = settled
    af.score()
    out = capsys.readouterr().out
    line = next(l for l in out.splitlines() if l.startswith("2026-10-26"))
    assert "38.4" in line and "BOARD p 0.3350" in line
    assert "RW p" in line and "EMP p" in line
    assert "# n=1 settled days" in out


def test_score_marks_an_unsettled_event_pending(apis, capsys):
    af.freeze()
    af.score()
    assert "2026-10-26  pending" in capsys.readouterr().out


def test_first_freeze_per_event_is_binding(apis):
    af.freeze()
    apis["open"] = [dict(m, yes_bid_dollars="0.0100") for m in BOARD26]
    af.freeze()
    (row,) = af.frozen()
    assert row["buckets"][0]["yes_bid"] == "0.3300"


def test_daily_runs_the_freeze_before_the_judgment_step():
    text = (pathlib.Path(af.__file__).parents[1] / "bin" / "daily.sh").read_text()
    assert text.index("kalshi/approvefreeze.py freeze") < text.index(
        "run_step claude")


def test_judgment_is_granted_the_scorer():
    repo = pathlib.Path(af.__file__).parents[1]
    allow = json.loads((repo / ".claude" / "settings.json").read_text())[
        "permissions"]["allow"]
    assert "Bash(python3 kalshi/approvefreeze.py *)" in allow
    assert "approvefreeze.py score" in (repo / "bin" / "daily-prompt.md").read_text()
