"""fuelfreeze.py: an EMP leg, the empirical k-print change distribution.

brief-2026-10-20: "The fuelfreeze models put P(>6.38) at about 0, but their
1.3c sd is far too tight for a weekly. The September diesel weeklies went up
+30c, +33c and +28c, so I priced an up-shock tail" by hand. The trend legs'
sd is 5 daily changes x sqrt(k); the 6-print diesel changes Kalshi actually
settled since 8/14 run -12c..+33c. EMP reads P(print > strike) straight off
every k-print change in the trailing EMP_DAYS of history: Kalshi's settled
daily prints, with the AAA journal over them.
"""

import datetime as dt
import json
import pathlib
import sys
from decimal import Decimal

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze
import fuelscore

BASE = dt.date(2026, 10, 20)


def day(n):
    return (BASE - dt.timedelta(days=n)).isoformat()


def ticker(d):
    return "KXDIESELD-" + dt.date.fromisoformat(d).strftime("%y%b%d").upper()


# 30 settled diesel prints 9/20..10/19: +1c a day, except a +20c jump on 10/1
PRINTS = {}
p = Decimal("6.0000")
for n in range(30, 0, -1):
    p += Decimal("0.2000") if day(n) == "2026-10-01" else Decimal("0.0100")
    PRINTS[day(n)] = p
# journal: the last 6 prints (10/15..10/20), 10/20 flat
JOURNAL = {day(n): PRINTS[day(n)] for n in range(5, 0, -1)}
JOURNAL[day(0)] = PRINTS[day(1)]


def mkt(t, floor, bid, ask):
    return {"ticker": t, "event_ticker": t.rsplit("-", 1)[0],
            "strike_type": "greater", "floor_strike": floor,
            "yes_bid_dollars": bid, "yes_ask_dollars": ask}


@pytest.fixture
def apis(tmp_path, monkeypatch):
    prints = tmp_path / "prints.jsonl"
    prints.write_text("".join(json.dumps(
        {"date": d, "prices": {"current": {"regular": "$4.3000",
                                           "diesel": f"${v}"}}}) + "\n"
        for d, v in sorted(JOURNAL.items())))
    monkeypatch.setattr(fuelscore, "JOURNAL", prints)
    monkeypatch.setattr(fuelfreeze, "JOURNAL", tmp_path / "fuel-freeze.jsonl")
    base = JOURNAL[day(0)]
    week = [mkt("KXDIESELW-26OCT22-T%.2f" % (base + d), float(base + d),
                "0.4000", "0.5000")
            for d in (Decimal("0.015"), Decimal("0.100"))]
    open_ = {"KXDIESELW": week}
    monkeypatch.setattr(fuelfreeze.kalshi, "get_markets",
                        lambda series_ticker=None, status=None:
                        open_.get(series_ticker, []))
    settled = {"KXDIESELD": [{"event_ticker": ticker(d),
                              "expiration_value": str(v).rstrip("0")}
                             for d, v in PRINTS.items()]}
    calls = []

    def settled_markets(series, *a, **kw):
        calls.append(series)
        return settled.get(series, [])
    monkeypatch.setattr(fuelfreeze.kalshi, "settled_markets", settled_markets)
    return {"settled": settled, "calls": calls}


def frozen_week():
    rows = [json.loads(l) for l in fuelfreeze.JOURNAL.read_text().splitlines()]
    return {r["event"]: r for r in rows}["KXDIESELW-26OCT22"]


def test_emp_reads_every_k_print_change_in_the_history(apis):
    fuelfreeze.freeze()
    r = frozen_week()
    assert r["k"] == 2
    # 2-print changes ending 9/22..10/20: 29 of them; 2c except the two
    # spanning 10/1 (21c) and the last (10/20 flat: 1c)
    assert r["emp_n"] == 29
    lo, hi = r["strikes"]
    # > base + 1.5c: the 26 two-cent changes and the two 21c ones
    assert lo["p"]["EMP"] == pytest.approx(28.5 / 30)
    # > base + 10c: only the two 21c jumps
    assert hi["p"]["EMP"] == pytest.approx(2.5 / 30)
    # the trend legs never see the jump
    assert hi["p"]["DRIFT"] < 1e-6


def test_emp_falls_back_to_the_journal_when_history_fails(apis, monkeypatch,
                                                          capsys):
    monkeypatch.setattr(fuelfreeze.kalshi, "settled_markets",
                        lambda *a, **kw: (_ for _ in ()).throw(OSError("x")))
    events, failed = fuelfreeze.freeze()
    assert events == ["KXDIESELW-26OCT22"] and failed == []
    r = frozen_week()
    # 6 journal prints -> 4 two-print changes: under EMP_MIN, no EMP odds
    assert r["emp_n"] == 4
    assert r["strikes"][0]["p"]["EMP"] is None
    assert "settled history failed" in capsys.readouterr().err


def test_emp_history_is_fetched_once_per_grade(apis):
    fuelfreeze.freeze()
    assert apis["calls"].count("KXDIESELD") == 1


def test_emp_ignores_changes_older_than_the_window(apis, monkeypatch):
    monkeypatch.setattr(fuelfreeze, "EMP_DAYS", 15)
    fuelfreeze.freeze()
    r = frozen_week()
    # starts 10/5..10/18 -> 14 changes, all after the 10/1 jump
    assert r["emp_n"] == 14
    assert r["strikes"][1]["p"]["EMP"] == pytest.approx(0.5 / 15)


def test_emp_is_scored_and_tallied(apis, monkeypatch, capsys):
    fuelfreeze.freeze()
    r = frozen_week()
    markets = [{"ticker": s["ticker"], "result": res,
                "expiration_value": "6.3000"}
               for s, res in zip(r["strikes"], ("yes", "no"))]
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event",
                        lambda t: {"markets": markets})
    fuelfreeze.score()
    out = capsys.readouterr().out
    line = [l for l in out.splitlines() if "KXDIESELW-26OCT22" in l][0]
    emp = ((28.5 / 30 - 1) ** 2 + (2.5 / 30) ** 2) / 2
    assert f"EMP {emp:.4f}" in line
    assert "board-EMP " in out
