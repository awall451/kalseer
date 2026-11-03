"""fuelfreeze.py: a log-only WKDAY leg on next-print gas dailies.

Brief 2026-11-02: "The weekday falsifier goes 2-0 for WKDAY ... Per the rule I
wrote yesterday: operator item, consider adding a day-of-week term to
fuelscore's gas race. WKDAY stays log-only for trading until about 3 more
weekend pairs agree." fuelscore scores WKDAY's point forecast (#106), but the
board question is odds: on KXAAAGASD-26NOV03 the board sat at ~4.155 (WKDAY
4.1531) while MOM put 0.91 on >4.155, and that divergence was read by hand.
So fuelfreeze freezes WKDAY's odds next to the other legs on every k=1
KXAAAGASD event (fuelscore.wkday is a one-print forecast; diesel showed no
weekday effect, 9-9) and `score` grades it in its own line, never in the
summary, the paired line, or the divergence tally, so their numbers don't move.
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
from test_fuelfreeze import mkt, row
from test_fuelfreeze_summary import run


def weeks(end="2026-11-02", days=29):
    """Gas prints ending Monday `end`: Mondays fall 0.4c, Tuesdays 2.0c,
    every other day 1.0c, so WKDAY's Monday->Tuesday scale is 5x. The
    29-day run ends on 4.1650: MOM 4.1610 and WKDAY 4.1450 straddle 4.155."""
    last = dt.date.fromisoformat(end)
    price, out = Decimal("4.4650") + Decimal("0.0100") * (29 - days), []
    for back in range(days, -1, -1):
        d = last - dt.timedelta(days=back)
        if out:
            price -= {0: Decimal("0.004"), 1: Decimal("0.020")}.get(
                d.weekday(), Decimal("0.010"))
        out.append((d.isoformat(), f"${price:.4f}"))
    return out


GASD = [mkt("KXAAAGASD-26NOV03-4.1550", 4.155, "0.4600", "0.4700"),
        mkt("KXAAAGASD-26NOV03-4.1650", 4.165, "0.0600", "0.0800")]
OPEN = {"KXAAAGASD": GASD,
        "KXAAAGASW": [mkt("KXAAAGASW-26NOV09-4.1000", 4.1, "0.5000",
                          "0.6000")],
        "KXDIESELD": [mkt("KXDIESELD-26NOV03-6.2900", 6.29, "0.5000",
                          "0.6000")]}


@pytest.fixture
def journal(tmp_path, monkeypatch):
    def setup(series):
        prints = tmp_path / "prints.jsonl"
        prints.write_text("".join(
            json.dumps(row(d, p, "$6.3000")) + "\n" for d, p in series))
        monkeypatch.setattr(fuelscore, "JOURNAL", prints)
        monkeypatch.setattr(fuelfreeze, "JOURNAL",
                            tmp_path / "fuel-freeze.jsonl")
        monkeypatch.setattr(fuelfreeze.kalshi, "get_markets",
                            lambda series_ticker=None, status=None:
                            OPEN.get(series_ticker, []))
        monkeypatch.setattr(fuelfreeze.kalshi, "settled_markets",
                            lambda *a, **kw: [])
        fuelfreeze.freeze()
        return {r["event"]: r for r in map(
            json.loads, fuelfreeze.JOURNAL.read_text().splitlines())}
    return setup


def test_freeze_prices_wkday_on_next_print_gas_dailies(journal):
    rows = journal(weeks())
    gas = rows["KXAAAGASD-26NOV03"]
    base = Decimal(gas["base"])
    prices = dict(fuelscore.series("regular"))
    # the same centre fuelscore's log-only line names for the next print
    assert gas["centre"]["WKDAY"] == f"{fuelscore.wkday(prices, '2026-11-02'):.4f}"
    assert Decimal(gas["centre"]["WKDAY"]) == base - Decimal("0.0200")
    assert gas["centre"]["MOM"] == f"{base - Decimal('0.0040'):.4f}"
    # odds: a normal around the WKDAY centre with the legs' shared k-print sd
    s = {x["floor"]: x["p"] for x in gas["strikes"]}
    sd = gas["sd"] / 100
    for floor, p in s.items():
        assert p["WKDAY"] == pytest.approx(
            fuelfreeze._p_above(floor, float(gas["centre"]["WKDAY"]), sd),
            abs=1e-4)  # the journal's sd is rounded
    assert s[4.155]["WKDAY"] < s[4.155]["MOM"]


def test_wkday_only_on_k1_gas_dailies(journal):
    rows = journal(weeks())
    for event in ("KXAAAGASW-26NOV09", "KXDIESELD-26NOV03"):
        assert "WKDAY" not in rows[event]["centre"]
        assert all("WKDAY" not in s["p"] for s in rows[event]["strikes"])


def test_wkday_is_none_short_of_three_of_each_weekday(journal):
    # 12 prints: only two Monday changes, so fuelscore.wkday is None
    gas = journal(weeks(days=12))["KXAAAGASD-26NOV03"]
    assert gas["centre"]["WKDAY"] is None
    assert all(s["p"]["WKDAY"] is None for s in gas["strikes"])
    assert gas["centre"]["MOM"] is not None


def strike(event, floor, bid, ask, p, wk):
    return {"ticker": f"{event}-T{floor:.3f}", "floor": floor,
            "yes_bid": bid, "yes_ask": ask,
            "p": {"RW": p, "MOM": p, "DRIFT": p, "EMP": None, "EMPD": None,
                  "WKDAY": wk}}


def rec(event, day, strikes):
    return {"event": event, "series": "KXAAAGASD", "grade": "regular",
            "date": day, "k": 1, "strikes": strikes}


def test_score_grades_wkday_on_its_own_line(tmp_path, monkeypatch, capsys):
    e = "KXAAAGASD-26NOV03"
    a = rec(e, "2026-11-03",
            [strike(e, 4.155, "0.4600", "0.4700", 0.9, 0.4),   # board 0.465
             strike(e, 4.165, "0.0000", "0.0000", 0.5, 0.1)])  # no board
    # an older freeze from before the leg existed: no WKDAY key at all
    old = rec("KXAAAGASD-26NOV02", "2026-11-02",
              [strike("KXAAAGASD-26NOV02", 4.17, "0.4000", "0.5000", 0.5,
                      0.5)])
    del old["strikes"][0]["p"]["WKDAY"]
    out = run(tmp_path, monkeypatch, capsys, [old, a],
              {f"{e}-T4.155": "no", f"{e}-T4.165": "no",
               "KXAAAGASD-26NOV02-T4.170": "no"})
    lines = out.splitlines()
    summary = [l for l in lines if l.startswith("# n=")][0]
    pair = [l for l in lines if "same strikes" in l][0]
    tally = [l for l in lines if l.startswith("# divergences")][0]
    for line in (summary, pair, tally):
        assert "WKDAY" not in line
    wk = [l for l in lines if l.startswith("# log-only WKDAY")][0]
    # one event, two strikes: WKDAY vs MOM on the same strikes
    assert "n=1 events (m2 strikes)" in wk
    assert f"WKDAY {(0.4 ** 2 + 0.1 ** 2) / 2:.4f}" in wk
    assert f"vs MOM {(0.9 ** 2 + 0.5 ** 2) / 2:.4f}" in wk
    # board-priced strikes only (m1), against BOARD
    assert f"WKDAY {0.4 ** 2:.4f} vs BOARD {0.465 ** 2:.4f} (m1)" in wk
    # the event's own line names WKDAY's Brier; the old event's doesn't
    ev = [l for l in lines if l.startswith("2026-11-03")][0]
    assert f"WKDAY {(0.4 ** 2 + 0.1 ** 2) / 2:.4f}" in ev
    assert "WKDAY" not in [l for l in lines if l.startswith("2026-11-02")][0]


def test_score_has_no_wkday_line_without_wkday_freezes(tmp_path, monkeypatch,
                                                       capsys):
    e = "KXAAAGASD-26NOV03"
    a = rec(e, "2026-11-03", [strike(e, 4.155, "0.4600", "0.4700", 0.9,
                                     None)])
    out = run(tmp_path, monkeypatch, capsys, [a], {f"{e}-T4.155": "no"})
    assert "log-only WKDAY" not in out
