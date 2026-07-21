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
