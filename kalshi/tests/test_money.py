"""Money-math tests: fees, guardrails, settlement, calibration bucketing."""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import kalshi
import paper


@pytest.fixture
def ledger(tmp_path, monkeypatch):
    """Fresh isolated ledger in tmp_path."""
    monkeypatch.setattr(paper, "DATA", tmp_path)
    monkeypatch.setattr(paper, "PORTFOLIO", tmp_path / "portfolio.json")
    monkeypatch.setattr(paper, "CLOSED", tmp_path / "closed.jsonl")
    return tmp_path


# --- fees ---

def test_fee_round_half_dollar():
    assert kalshi.taker_fee(0.50, 100) == 1.75


def test_fee_ceils_to_cent():
    # 0.07 * 120 * 0.33 * 0.67 = 1.85724 -> ceil -> 1.86
    assert kalshi.taker_fee(0.33, 120) == 1.86
    # 0.07 * 50 * 0.98 * 0.02 = 0.0686 -> 0.07
    assert kalshi.taker_fee(0.98, 50) == 0.07


def test_fee_minimum_one_cent():
    assert kalshi.taker_fee(0.99, 1) == 0.01


# --- guardrails ---

def open_n(n, price=0.10, contracts=10):
    for i in range(n):
        paper.cmd_open(f"TEST-{i}", "yes", price, contracts, 0.5, "test")


def test_daily_trade_cap(ledger):
    open_n(3)
    with pytest.raises(SystemExit) as e:
        paper.cmd_open("TEST-4", "yes", 0.10, 10, 0.5, "test")
    assert e.value.code == paper.EXIT_GUARDRAIL


def test_single_position_cap(ledger):
    # $60 position on $500 equity > 10%
    with pytest.raises(SystemExit) as e:
        paper.cmd_open("BIG", "yes", 0.60, 100, 0.9, "test")
    assert e.value.code == paper.EXIT_GUARDRAIL


def test_total_exposure_cap(ledger, monkeypatch):
    monkeypatch.setattr(paper, "MAX_TRADES_PER_DAY", 100)
    monkeypatch.setattr(paper, "MAX_POSITION_FRAC", 1.0)
    # each position ~ $45+fee on $500 equity; 5th push past 40% ($200)
    with pytest.raises(SystemExit) as e:
        open_n(6, price=0.45, contracts=100)
    assert e.value.code == paper.EXIT_GUARDRAIL
    p = paper.load()
    exposure = sum(paper.position_cost(x) for x in p["positions"])
    assert exposure <= 0.40 * (p["bankroll"] + exposure) + 1e-9


def test_allowed_trade_passes(ledger):
    paper.cmd_open("OK", "yes", 0.30, 100, 0.5, "test")  # $30 + fee, fine
    p = paper.load()
    assert len(p["positions"]) == 1
    assert p["bankroll"] < 500


# --- settlement ---

def test_settle_win_and_loss(ledger, monkeypatch):
    paper.cmd_open("WINNER", "yes", 0.40, 50, 0.6, "test")
    paper.cmd_open("LOSER", "no", 0.40, 50, 0.6, "test")
    results = {"WINNER": "yes", "LOSER": "yes"}  # LOSER held NO, result yes
    monkeypatch.setattr(paper.kalshi, "get_market",
                        lambda t: {"status": "settled", "result": results[t]})
    bankroll_before = paper.load()["bankroll"]
    paper.cmd_settle()
    p = paper.load()
    assert p["positions"] == []
    closed = [json.loads(l) for l in paper.CLOSED.read_text().splitlines()]
    win = next(x for x in closed if x["ticker"] == "WINNER")
    lose = next(x for x in closed if x["ticker"] == "LOSER")
    fee = kalshi.taker_fee(0.40, 50)
    assert win["won"] and win["payout"] == 50.0
    assert win["pnl"] == pytest.approx(50 - 0.40 * 50 - fee)
    assert not lose["won"] and lose["payout"] == 0.0
    assert lose["pnl"] == pytest.approx(-(0.40 * 50) - fee)
    assert p["bankroll"] == pytest.approx(bankroll_before + 50.0)


@pytest.mark.parametrize("status", ["settled", "finalized"])
def test_settle_accepts_both_resolved_statuses(ledger, monkeypatch, status):
    """Live Kalshi reports resolved markets as "finalized"; "settled" is also
    seen. Treating only "settled" as resolved silently strands every position
    in the ledger forever, so both must settle."""
    paper.cmd_open("DONE", "yes", 0.40, 10, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market",
                        lambda t: {"status": status, "result": "yes"})
    paper.cmd_settle()
    assert paper.load()["positions"] == []


def test_settle_leaves_unresolved_open(ledger, monkeypatch):
    paper.cmd_open("PENDING", "yes", 0.40, 10, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market",
                        lambda t: {"status": "active", "result": ""})
    paper.cmd_settle()
    assert len(paper.load()["positions"]) == 1


# --- closing early ---

def test_close_returns_proceeds_and_records_row(ledger):
    paper.cmd_open("EXIT", "yes", 0.40, 50, 0.6, "test")
    bankroll = paper.load()["bankroll"]
    paper.cmd_close("EXIT", "0.55", "thesis dead, salvaging value")
    p = paper.load()
    assert p["positions"] == []
    exit_fee = kalshi.taker_fee(0.55, 50)
    assert p["bankroll"] == pytest.approx(bankroll + 0.55 * 50 - exit_fee)
    row = json.loads(paper.CLOSED.read_text().splitlines()[0])
    entry_fee = kalshi.taker_fee(0.40, 50)
    assert row["result"] == "closed"
    assert "won" not in row  # no market outcome — must never score calibration
    assert row["exit_price"] == 0.55
    assert row["exit_fee"] == exit_fee
    assert row["payout"] == pytest.approx(0.55 * 50 - exit_fee)
    assert row["pnl"] == pytest.approx(0.55 * 50 - exit_fee - 0.40 * 50 - entry_fee)
    assert row["settled"] == row["recorded"]


def test_close_without_position_exits(ledger):
    with pytest.raises(SystemExit):
        paper.cmd_close("GHOST", "0.50", "nothing there")


def test_close_takes_oldest_of_duplicate_tickers(ledger):
    paper.cmd_open("DUP", "yes", 0.10, 10, 0.5, "first")
    paper.cmd_open("DUP", "yes", 0.20, 10, 0.5, "second")
    paper.cmd_close("DUP", "0.30", "exit one")
    p = paper.load()
    assert [x["entry_price"] for x in p["positions"]] == [0.20]
    row = json.loads(paper.CLOSED.read_text().splitlines()[0])
    assert row["entry_price"] == 0.10


def test_closing_does_not_refund_the_daily_cap(ledger):
    """The cap counts opens, not open positions — closing must not create
    room for a fourth entry on the same day."""
    open_n(3)
    paper.cmd_close("TEST-0", "0.50", "exit")
    with pytest.raises(SystemExit) as e:
        paper.cmd_open("TEST-4", "yes", 0.10, 10, 0.5, "test")
    assert e.value.code == paper.EXIT_GUARDRAIL


def test_report_scores_only_resolved_rows(ledger, capsys):
    rows = [
        {"result": "yes", "won": True, "fair_value": 0.95, "pnl": 1.0,
         "entry_price": 0.9, "contracts": 1, "fee_paid": 0.01},
        {"result": "closed", "fair_value": 0.95, "pnl": -0.5,
         "entry_price": 0.9, "contracts": 1, "fee_paid": 0.01},
    ]
    with paper.CLOSED.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    paper.cmd_report()
    out = capsys.readouterr().out
    # money counts both rows; skill counts only the resolved one
    assert "$+0.50" in out
    assert "said 90%-100%: happened 100% (n=1)" in out


def test_report_survives_only_early_closes(ledger, capsys):
    row = {"result": "closed", "fair_value": 0.5, "pnl": -0.5,
           "entry_price": 0.4, "contracts": 1, "fee_paid": 0.01}
    paper.CLOSED.write_text(json.dumps(row) + "\n")
    paper.cmd_report()  # must not divide by zero resolved rows


# --- calibration bucketing ---

def test_calibration_buckets(ledger, capsys):
    rows = [
        {"fair_value": 0.95, "won": True, "pnl": 1.0, "entry_price": 0.9,
         "contracts": 1, "fee_paid": 0.01},
        {"fair_value": 0.95, "won": False, "pnl": -1.0, "entry_price": 0.9,
         "contracts": 1, "fee_paid": 0.01},
        {"fair_value": 0.05, "won": False, "pnl": -0.1, "entry_price": 0.05,
         "contracts": 1, "fee_paid": 0.01},
    ]
    with paper.CLOSED.open("w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")
    paper.cmd_report()
    out = capsys.readouterr().out
    assert "said 90%-100%: happened 50% (n=2)" in out
    assert "said 0%-10%: happened 0% (n=1)" in out


# --- settlement timestamps ---

def test_settle_stamps_market_close_not_poller_clock(ledger, monkeypatch):
    """A settle poller that is days behind must not backdate the equity curve
    to its own catch-up run — that stacks weeks of trades on one instant."""
    paper.cmd_open("LATE", "yes", 0.40, 10, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market",
                        lambda t: {"status": "finalized", "result": "yes",
                                   "close_time": "2026-07-13T14:00:00Z"})
    paper.cmd_settle()
    row = json.loads(paper.CLOSED.read_text().splitlines()[0])
    assert row["settled"] == "2026-07-13T14:00:00+00:00"
    assert row["recorded"] > row["settled"]  # poller noticed later


def test_settle_falls_back_to_now_without_close_time(ledger, monkeypatch):
    paper.cmd_open("NOTIME", "yes", 0.40, 10, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market",
                        lambda t: {"status": "finalized", "result": "yes"})
    paper.cmd_settle()
    row = json.loads(paper.CLOSED.read_text().splitlines()[0])
    assert row["settled"] == row["recorded"]


@pytest.mark.parametrize("field", ["close_time", "expected_expiration_time",
                                   "expiration_time"])
def test_market_close_time_field_order(field):
    assert paper.market_close_time({field: "2026-07-20T14:00:00Z"}) == \
        "2026-07-20T14:00:00+00:00"


def test_market_close_time_ignores_unparseable():
    assert paper.market_close_time({"close_time": "not a date"}) is None


# --- status mark-to-market ---

def test_status_marks_yes_position_at_its_bid(ledger, monkeypatch, capsys):
    paper.cmd_open("MTM-YES", "yes", 0.40, 50, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market", lambda t, **kw: {
        "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.57"})
    capsys.readouterr()
    paper.cmd_status()
    out = capsys.readouterr().out
    # a YES exit fetches the yes bid; unrealized = proceeds net of exit fee
    proceeds = 0.55 * 50 - kalshi.taker_fee(0.55, 50)
    cost = 0.40 * 50 + kalshi.taker_fee(0.40, 50)
    assert "now 0.55" in out
    assert f"unreal ${proceeds - cost:+.2f}" in out


def test_status_marks_no_position_at_one_minus_yes_ask(ledger, monkeypatch, capsys):
    paper.cmd_open("MTM-NO", "no", 0.40, 50, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market", lambda t, **kw: {
        "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.70"})
    capsys.readouterr()
    paper.cmd_status()
    out = capsys.readouterr().out
    assert "now 0.30" in out  # 1 - yes_ask: what the NO side sells for


def test_status_survives_api_failure(ledger, monkeypatch, capsys):
    paper.cmd_open("MTM-DOWN", "yes", 0.40, 50, 0.6, "test")

    def boom(t, **kw):
        raise OSError("api down")

    monkeypatch.setattr(paper.kalshi, "get_market", boom)
    capsys.readouterr()
    paper.cmd_status()
    out = capsys.readouterr().out
    assert "MTM-DOWN" in out
    assert "now ?" in out


def test_status_skips_mark_on_empty_book(ledger, monkeypatch, capsys):
    paper.cmd_open("MTM-THIN", "no", 0.40, 50, 0.6, "test")
    monkeypatch.setattr(paper.kalshi, "get_market", lambda t, **kw: {
        "yes_bid_dollars": "0", "yes_ask_dollars": "0"})
    capsys.readouterr()
    paper.cmd_status()
    out = capsys.readouterr().out
    # 1 - 0 would price the NO exit at a fantasy 1.00; an empty book is no mark
    assert "now ?" in out
