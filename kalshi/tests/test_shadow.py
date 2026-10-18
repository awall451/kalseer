"""shadow.py: the orders a live executor WOULD send, scored against the real
order book — no keys, no money, nothing is ever sent.

Paper trading fills every trade at whatever price the judgment step names.
Real orders sit in a book: they fill at the levels that exist, partly or not
at all. Before any real money (see the wiki's Phase 2 gate), shadow mode
measures that gap on every paper open/close:
  - at decision time, the exact limit order is built and walked against the
    live book (immediate fill + VWAP; the rest would rest);
  - each run, resting remainders are reconciled against public trade prints
    (optimistic: queue position is unknown) and expire when the market closes;
  - the report compares paper P&L to what the shadow fills would have made.
"""

import json
import pathlib
import subprocess
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import kalshi
import paper
import shadow

REPO = pathlib.Path(__file__).parents[2]

# Live-API shape (2026-10-18): bids only, dollar strings, worst -> best.
BOOK = {
    "no_dollars": [["0.4000", "5.00"], ["0.4500", "10.00"]],   # YES asks .60 x5, .55 x10
    "yes_dollars": [["0.3000", "8.00"], ["0.3500", "4.00"]],   # YES bids .35 x4, .30 x8
}


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    monkeypatch.setattr(paper, "DATA", tmp_path)
    monkeypatch.setattr(paper, "PORTFOLIO", tmp_path / "portfolio.json")
    monkeypatch.setattr(paper, "CLOSED", tmp_path / "closed.jsonl")
    monkeypatch.setattr(shadow, "ENABLED", True)
    monkeypatch.setattr(kalshi, "get_orderbook", lambda t, depth=8, tries=4: BOOK)
    return tmp_path


def rows(ledger):
    return shadow.load_orders()


# --- book walk ---

def test_buy_yes_lifts_no_bids_best_first_up_to_the_limit():
    filled, vwap = shadow.simulate(BOOK, "buy", "yes", 0.55, 15)
    assert (filled, vwap) == (10, 0.55)


def test_buy_through_two_levels_gives_vwap():
    filled, vwap = shadow.simulate(BOOK, "buy", "yes", 0.60, 15)
    assert filled == 15 and vwap == pytest.approx((10 * 0.55 + 5 * 0.60) / 15)


def test_buy_no_lifts_yes_bids():
    # NO asks = 1 - YES bids: .65 x4, .70 x8
    assert shadow.simulate(BOOK, "buy", "no", 0.65, 10) == (4, 0.65)


def test_sell_yes_hits_own_side_bids_down_to_the_limit():
    assert shadow.simulate(BOOK, "sell", "yes", 0.35, 10) == (4, 0.35)
    filled, vwap = shadow.simulate(BOOK, "sell", "yes", 0.30, 10)
    assert filled == 10 and vwap == pytest.approx((4 * 0.35 + 6 * 0.30) / 10)


def test_limit_below_the_book_fills_nothing():
    assert shadow.simulate(BOOK, "buy", "yes", 0.50, 10) == (0, None)


def test_empty_book_fills_nothing():
    assert shadow.simulate({"no_dollars": [], "yes_dollars": []}, "buy", "yes", 0.9, 5) == (0, None)


# --- hooked into paper.py ---

def test_paper_open_records_a_shadow_limit_order(ledger):
    paper.cmd_open("KXTEST-1", "yes", 0.55, 15, 0.70, "test")
    [r] = rows(ledger)
    assert r["kind"] == "open" and r["ticker"] == "KXTEST-1"
    o = r["order"]
    assert o["action"] == "buy" and o["side"] == "yes" and o["type"] == "limit"
    assert o["count"] == 15 and o["yes_price_dollars"] == "0.5500"
    assert o["client_order_id"] == r["id"]
    assert r["filled_now"] == 10 and r["remaining"] == 5 and r["status"] == "partial"
    pos = json.loads((ledger / "portfolio.json").read_text())["positions"][0]
    assert pos["shadow_id"] == r["id"]


def test_rejected_paper_trade_records_no_shadow_order(ledger):
    with pytest.raises(SystemExit):
        paper.cmd_open("KXTEST-1", "yes", 0.55, 500, 0.70, "too big")
    assert rows(ledger) == []


def test_paper_close_records_a_sell(ledger):
    paper.cmd_open("KXTEST-1", "yes", 0.55, 10, 0.70, "test")
    paper.cmd_close("KXTEST-1", 0.35, "exit")
    close = rows(ledger)[-1]
    assert close["kind"] == "close" and close["order"]["action"] == "sell"
    assert close["filled_now"] == 4 and close["status"] == "partial"


def test_book_fetch_failure_never_breaks_the_paper_trade(ledger, monkeypatch):
    def boom(*a, **k):
        raise OSError("api down")
    monkeypatch.setattr(kalshi, "get_orderbook", boom)
    paper.cmd_open("KXTEST-1", "yes", 0.55, 10, 0.70, "test")
    assert json.loads((ledger / "portfolio.json").read_text())["positions"]
    [r] = rows(ledger)
    assert r["status"] == "error" and "api down" in r["error"]


def test_disabled_shadow_records_nothing(ledger, monkeypatch):
    monkeypatch.setattr(shadow, "ENABLED", False)
    paper.cmd_open("KXTEST-1", "yes", 0.55, 10, 0.70, "test")
    assert rows(ledger) == []


# --- reconcile resting remainders against public prints ---

def trade(yes, count, when):
    return {"yes_price_dollars": f"{yes:.4f}", "no_price_dollars": f"{1 - yes:.4f}",
            "count_fp": f"{count:.2f}", "created_time": when}


def test_reconcile_fills_resting_from_prints_at_or_through_the_limit(ledger, monkeypatch):
    paper.cmd_open("KXTEST-1", "yes", 0.55, 15, 0.70, "test")   # 5 resting @ .55
    created = rows(ledger)[0]["created"]
    prints = [trade(0.50, 2, "2000-01-01T00:00:00Z"),     # before the order: ignored
              trade(0.58, 9, "2099-01-01T00:00:00Z"),     # above our bid: no fill
              trade(0.55, 3, "2099-01-01T00:00:00Z"),     # at our bid: fill
              trade(0.52, 9, "2099-01-01T00:00:01Z")]     # through it: fill rest
    monkeypatch.setattr(shadow, "fetch_trades", lambda t, since: prints)
    monkeypatch.setattr(kalshi, "get_market", lambda t, tries=4: {"status": "active"})
    shadow.reconcile()
    r = rows(ledger)[0]
    assert r["filled_later"] == 5 and r["remaining"] == 0 and r["status"] == "filled"
    assert r["created"] == created


def test_reconcile_expires_resting_when_the_market_closes(ledger, monkeypatch):
    paper.cmd_open("KXTEST-1", "yes", 0.55, 15, 0.70, "test")
    monkeypatch.setattr(shadow, "fetch_trades", lambda t, since: [])
    monkeypatch.setattr(kalshi, "get_market", lambda t, tries=4: {"status": "finalized"})
    shadow.reconcile()
    r = rows(ledger)[0]
    assert r["status"] == "expired" and r["remaining"] == 5 and r["filled_now"] == 10


# --- report: what paper P&L would really have been ---

def test_summary_compares_paper_and_shadow_pnl(ledger, monkeypatch):
    paper.cmd_open("KXTEST-1", "yes", 0.55, 15, 0.70, "test")   # shadow fills 10
    monkeypatch.setattr(kalshi, "get_market",
                        lambda t, tries=4: {"status": "finalized", "result": "yes",
                                            "close_time": "2026-10-18T00:00:00Z"})
    monkeypatch.setattr(shadow, "fetch_trades", lambda t, since: [])
    paper.cmd_settle()
    shadow.reconcile()
    s = shadow.summary()
    assert s["orders"] == 1 and s["requested"] == 15 and s["filled"] == 10
    assert s["fill_rate"] == pytest.approx(10 / 15)
    [t] = s["settled"]
    assert t["paper_contracts"] == 15 and t["shadow_contracts"] == 10
    # shadow: 10 x (1 - .55) - fee
    assert t["shadow_pnl"] == pytest.approx(10 * 0.45 - kalshi.taker_fee(0.55, 10))
    assert s["paper_pnl"] == t["paper_pnl"] and s["shadow_pnl"] == t["shadow_pnl"]
    pub = json.loads((ledger / "public" / "shadow.json").read_text())
    assert pub["summary"]["filled"] == 10


# --- operator merge gate ---
# Money paths are deliberately auto-mergeable while trading is paper + shadow
# only (owner's call, 2026-10-18). This test pins that, so re-protecting them
# before live money is a conscious change here, not an accident.

def _gate_matches(path):
    text = (REPO / "bin" / "operator.sh").read_text()
    pattern = next(l for l in text.splitlines() if l.startswith("PROTECTED="))
    pattern = pattern.split("=", 1)[1].strip("'")
    return subprocess.run(["grep", "-qE", pattern], input=path, text=True).returncode == 0


def test_operator_merge_gate_protects_the_charter_and_ci():
    for path in (".github/workflows/ci.yml", "bin/operator.sh", "bin/operator-prompt.md"):
        assert _gate_matches(path), path


def test_money_paths_auto_merge_during_shadow_mode():
    for path in ("kalshi/paper.py", "kalshi/shadow.py", "kalshi/wx.py"):
        assert not _gate_matches(path), path
