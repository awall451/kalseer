"""Dashboard aggregate tests: marks, equity curve, calibration intervals."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import publish  # noqa: E402


def pos(ticker, side="yes", entry=0.40, n=100, fee=1.0, opened="2026-07-01",
        **kw):
    return dict({"ticker": ticker, "side": side, "entry_price": entry,
                 "contracts": n, "fee_paid": fee, "fair_value": 0.6,
                 "edge_at_entry": 0.2, "reasoning": "test",
                 "opened": f"{opened}T12:00:00+00:00"}, **kw)


def closed(ticker, won, settled, **kw):
    p = pos(ticker, **kw)
    payout = p["contracts"] * (1.0 if won else 0.0)
    p.update({"won": won, "result": "yes", "payout": payout,
              "pnl": round(payout - p["entry_price"] * p["contracts"] - p["fee_paid"], 2),
              "settled": f"{settled}T14:00:00+00:00"})
    return p


# --- marks survive a resolving market ---

def test_yes_price_uses_mid_of_live_book():
    assert publish.yes_price({"yes_bid_dollars": "0.40",
                              "yes_ask_dollars": "0.44"}) == pytest.approx(0.42)


def test_yes_price_falls_back_when_book_empties():
    """A market about to resolve quotes 0.0000/1.0000 — a degenerate spread,
    not a real mid. The old guard rejected it and froze the sparkline days
    before the outcome."""
    m = {"yes_bid_dollars": "0.0000", "yes_ask_dollars": "1.0000",
         "last_price_dollars": "0.9900"}
    assert publish.yes_price(m) == pytest.approx(0.99)


def test_yes_price_none_when_never_traded():
    assert publish.yes_price({"yes_bid_dollars": "0.0000",
                              "yes_ask_dollars": "1.0000",
                              "last_price_dollars": "0.0000"}) is None


def test_yes_price_ignores_crossed_book():
    m = {"yes_bid_dollars": "0.60", "yes_ask_dollars": "0.40",
         "last_price_dollars": "0.50"}
    assert publish.yes_price(m) == pytest.approx(0.50)


# --- equity curve ---

def test_curve_spreads_settles_over_real_days():
    """Two trades settling on different days must land on different x
    positions even if one poller run closed both."""
    rows = [closed("A", True, "2026-07-03", opened="2026-07-01"),
            closed("B", False, "2026-07-05", opened="2026-07-01")]
    curve = publish.equity_curve(rows, {"bankroll": 0, "positions": []}, {},
                                 today="2026-07-06")
    by_day = {p["t"][:10]: p for p in curve[1:]}
    assert by_day["2026-07-03"]["events"][0]["ticker"] == "A"
    assert by_day["2026-07-05"]["events"][0]["ticker"] == "B"
    assert by_day["2026-07-04"]["events"] == []
    assert by_day["2026-07-03"]["equity"] != by_day["2026-07-05"]["equity"]


def test_curve_marks_open_positions_to_market():
    """Held at cost the curve is flat; the book moved 20c."""
    p = pos("HELD", entry=0.40, n=100, fee=1.0, opened="2026-07-01")
    hist = {"HELD": [{"date": "2026-07-01", "mark": 0.40},
                     {"date": "2026-07-03", "mark": 0.60}]}
    curve = publish.equity_curve([], {"bankroll": 459.0, "positions": [p]},
                                 hist, today="2026-07-03")
    by_day = {pt["t"][:10]: pt for pt in curve[1:]}
    assert by_day["2026-07-01"]["unrealized"] == pytest.approx(-1.0)  # fee
    assert by_day["2026-07-03"]["unrealized"] == pytest.approx(19.0)
    assert by_day["2026-07-03"]["equity"] > by_day["2026-07-01"]["equity"]


def test_curve_carries_last_mark_forward_over_gaps():
    p = pos("GAPPY", entry=0.40, opened="2026-07-01")
    hist = {"GAPPY": [{"date": "2026-07-01", "mark": 0.70}]}
    curve = publish.equity_curve([], {"bankroll": 459.0, "positions": [p]},
                                 hist, today="2026-07-04")
    by_day = {pt["t"][:10]: pt for pt in curve[1:]}
    assert by_day["2026-07-04"]["unrealized"] == by_day["2026-07-01"]["unrealized"]


def test_curve_starts_at_first_open_not_first_settle():
    """The old version backfilled the start point with the first settlement,
    erasing every day before it."""
    rows = [closed("A", False, "2026-07-20", opened="2026-07-11")]
    curve = publish.equity_curve(rows, {"bankroll": 0, "positions": []}, {},
                                 today="2026-07-20")
    assert curve[0]["t"][:10] == "2026-07-11"
    assert curve[0]["equity"] == publish.paper.STARTING_BANKROLL


def test_curve_cash_reconciles_with_ledger(capsys):
    rows = [closed("A", True, "2026-07-03", opened="2026-07-01")]
    start = publish.paper.STARTING_BANKROLL
    cost = 0.40 * 100 + 1.0
    curve = publish.equity_curve(rows, {"bankroll": start - cost + 100.0,
                                        "positions": []}, {}, today="2026-07-04")
    assert curve[-1]["cash"] == pytest.approx(start - cost + 100.0)
    assert "drift" not in capsys.readouterr().out


def test_curve_warns_on_ledger_drift(capsys):
    rows = [closed("A", True, "2026-07-03", opened="2026-07-01")]
    publish.equity_curve(rows, {"bankroll": 1.0, "positions": []}, {},
                         today="2026-07-04")
    assert "drift" in capsys.readouterr().out


def test_curve_empty_without_trades():
    assert publish.equity_curve([], {"bankroll": 500.0, "positions": []}, {}) == []


# --- calibration ---

def test_wilson_spans_almost_everything_at_n1():
    lo, hi = publish.wilson(1, 1)
    assert lo < 0.25 and hi == 1.0


def test_wilson_tightens_with_n():
    narrow = publish.wilson(50, 100)
    wide = publish.wilson(5, 10)
    assert (narrow[1] - narrow[0]) < (wide[1] - wide[0])


def test_calibration_carries_interval():
    rows = [closed("A", False, "2026-07-03", fair_value=0.78)]
    [b] = publish.calibration(rows)
    assert b["n"] == 1 and b["actual"] == 0.0
    assert b["lo95"] == 0.0 and b["hi95"] > 0.7  # one loss proves nothing


# --- stats ---

def test_stats_separates_the_two_returns():
    rows = [closed("A", False, "2026-07-03", entry=0.40, n=100, fee=1.0)]
    s = publish.stats(rows, {"bankroll": 459.0, "positions": []}, {})
    assert s["staked"] == pytest.approx(41.0)
    assert s["roi_staked"] == pytest.approx(-1.0)          # lost all of it
    assert s["return_total"] == pytest.approx(-41.0 / 500)  # of the fund


def test_stats_equity_moves_with_marks():
    p = pos("HELD", entry=0.40, n=100, fee=1.0)
    hist = {"HELD": [{"date": "2026-07-03", "mark": 0.60}]}
    s = publish.stats([], {"bankroll": 459.0, "positions": [p]}, hist)
    assert s["unrealized_pnl"] == pytest.approx(19.0)
    assert s["equity"] == pytest.approx(519.0)


def test_stats_brier_baseline_is_the_yardstick():
    """Brier alone has no scale; compare against always predicting the base
    rate. Confident-and-wrong must score worse than the no-skill baseline."""
    rows = [closed("A", False, "2026-07-03", fair_value=0.9),
            closed("B", False, "2026-07-04", fair_value=0.9),
            closed("C", True, "2026-07-05", fair_value=0.9)]
    s = publish.stats(rows, {"bankroll": 0, "positions": []}, {})
    assert s["brier"] > s["brier_baseline"]
