"""econfreeze.py: journal the payrolls/CPI boards every morning.

The payrolls-2026-calibration watchlist item asks for "Oct CPI pre-reg ~T-5
(record board move T-5 -> T-1)", a hand-copied board on two chosen days. A run
that is busy elsewhere loses the datum (10/16: "no pre-regs frozen this run"
cost the rain family a scored day). The pipeline freezes the nearest open
event of each macro series every morning, so `moves` reads the T-n board path
back offline and `score` gives the board's Brier by days out once Kalshi
settles the first print.
"""

import datetime as dt
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import econfreeze


def market(ticker, floor, bid, ask, result="", close="2026-11-06T13:29:00Z"):
    return {"ticker": ticker, "strike_type": "greater", "floor_strike": floor,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask, "result": result,
            "close_time": close}


OCT = [market("KXPAYROLLS-26OCT-T0", 0, "0.8400", "0.8800"),
       market("KXPAYROLLS-26OCT-T50000", 50000, "0.4000", "0.4400"),
       market("KXPAYROLLS-26OCT-T100000", 100000, "0.0000", "0.0000")]


@pytest.fixture
def board(tmp_path, monkeypatch):
    monkeypatch.setattr(econfreeze, "JOURNAL", tmp_path / "econ" / "f.jsonl")
    state = {"events": {"KXPAYROLLS": ["KXPAYROLLS-26NOV", "KXPAYROLLS-26OCT"]},
             "markets": {"KXPAYROLLS-26OCT": OCT, "KXPAYROLLS-26NOV": []},
             "fail": set(), "today": dt.date(2026, 10, 30), "asked": []}

    def fake_open(series):
        if series in state["fail"]:
            raise RuntimeError("HTTP 503")
        return list(state["events"].get(series, []))

    def fake_event(ticker):
        state["asked"].append(ticker)
        return {"event_ticker": ticker, "markets": state["markets"][ticker]}
    monkeypatch.setattr(econfreeze, "open_events", fake_open)
    monkeypatch.setattr(econfreeze.kalshi, "get_event", fake_event)
    monkeypatch.setattr(econfreeze, "_today", lambda: state["today"])
    return state


def rows(board_state=None):
    return [json.loads(l) for l in
            econfreeze.JOURNAL.read_text().splitlines() if l.strip()]


def test_freeze_journals_the_nearest_event_with_exact_strings(board):
    assert econfreeze.freeze() == 1
    (r,) = rows()
    assert board["asked"] == ["KXPAYROLLS-26OCT"]  # never the far month
    assert r["event"] == "KXPAYROLLS-26OCT"
    assert r["date"] == "2026-10-30"
    assert r["close_time"] == "2026-11-06T13:29:00Z"
    assert r["days_out"] == 7
    assert r["markets"][1] == {"ticker": "KXPAYROLLS-26OCT-T50000",
                               "floor": 50000, "yes_bid": "0.4000",
                               "yes_ask": "0.4400"}


def test_nearest_event_is_by_month_not_ticker_text():
    assert econfreeze.nearest(["KXCPI-26NOV", "KXCPI-26DEC", "KXCPI-26OCT"]) \
        == "KXCPI-26OCT"
    assert econfreeze.nearest(["KXCPI-27JAN", "KXCPI-26DEC"]) == "KXCPI-26DEC"
    assert econfreeze.nearest([]) is None


def test_second_freeze_same_day_adds_nothing(board):
    econfreeze.freeze()
    assert econfreeze.freeze() == 0
    assert len(rows()) == 1
    board["today"] = dt.date(2026, 10, 31)
    assert econfreeze.freeze() == 1
    assert [r["days_out"] for r in rows()] == [7, 6]


def test_a_failed_series_is_reported_and_the_rest_still_freeze(board, capsys):
    board["events"]["KXCPI"] = ["KXCPI-26OCT"]
    board["fail"].add("KXCPI")
    assert econfreeze.freeze() == 1
    assert "KXCPI: HTTP 503" in capsys.readouterr().err


def test_main_freeze_exits_1_only_when_nothing_was_journaled(board, capsys):
    econfreeze.main(["freeze"])
    assert "econfreeze: 1 board(s) frozen" in capsys.readouterr().out
    with pytest.raises(SystemExit) as e:
        econfreeze.main(["freeze"])  # same day again: nothing new
    assert e.value.code == 1


def test_moves_prints_the_t_minus_path_and_the_move(board, capsys):
    econfreeze.freeze()
    board["today"] = dt.date(2026, 11, 5)
    board["markets"]["KXPAYROLLS-26OCT"] = [
        market("KXPAYROLLS-26OCT-T0", 0, "0.9000", "0.9200"),
        market("KXPAYROLLS-26OCT-T50000", 50000, "0.5500", "0.5900"),
        market("KXPAYROLLS-26OCT-T100000", 100000, "0.1000", "0.1200")]
    econfreeze.freeze()
    capsys.readouterr()
    econfreeze.main(["moves", "KXPAYROLLS"])
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("# KXPAYROLLS-26OCT")
    assert "T-7 2026-10-30  T0 0.86  T50000 0.42  T100000 -" in out
    assert "T-1 2026-11-05  T0 0.91  T50000 0.57  T100000 0.11" in out
    assert "# T-7 -> T-1: T0 +0.05  T50000 +0.15" in out


def test_score_gives_board_brier_by_days_out_once_settled(board, capsys):
    econfreeze.freeze()
    board["today"] = dt.date(2026, 11, 5)
    econfreeze.freeze()
    board["markets"]["KXPAYROLLS-26OCT"] = [
        market("KXPAYROLLS-26OCT-T0", 0, "", "", "yes"),
        market("KXPAYROLLS-26OCT-T50000", 50000, "", "", "no"),
        market("KXPAYROLLS-26OCT-T100000", 100000, "", "", "no")]
    capsys.readouterr()
    econfreeze.main(["score"])
    out = capsys.readouterr().out.splitlines()
    # T-7: (0.86-1)^2 + (0.42-0)^2 over 2 priced strikes (T100000 empty)
    t7 = round((0.14 ** 2 + 0.42 ** 2) / 2, 4)
    assert f"KXPAYROLLS-26OCT  T-7  BOARD B {t7:.4f} (2 strikes)" in out
    assert any(l.startswith("KXPAYROLLS-26OCT  T-1  BOARD B") for l in out)
    assert any(l.startswith("# T-7: n=1 mean B") for l in out)


def test_score_marks_an_unsettled_event_pending(board, capsys):
    econfreeze.freeze()
    capsys.readouterr()
    econfreeze.main(["score"])
    assert "KXPAYROLLS-26OCT  pending (1 freeze(s), T-7..T-7)" in (
        capsys.readouterr().out)


def test_negative_strikes_keep_their_sign():
    # live 10/30: KXPAYROLLS-26OCT-T-25000 and KXCPI-26OCT-T-0.1 read as
    # '25000' / '0.1' when split on the last dash
    assert econfreeze._strike("KXPAYROLLS-26OCT-T-25000") == "T-25000"
    assert econfreeze._strike("KXCPI-26OCT-T-0.1") == "T-0.1"
    assert econfreeze._strike("KXCPI-26OCT-T0.1") == "T0.1"


def test_daily_freezes_econ_boards_before_the_judgment_step():
    daily = (pathlib.Path(__file__).parents[2] / "bin" / "daily.sh").read_text()
    step = daily.index("run_step econfreeze")
    assert "kalshi/econfreeze.py freeze" in daily[step:daily.index("\n", step)]
    assert step < daily.index("run_step claude")
