"""kalshi.py event prints the board's implied centre for a 'greater' ladder.

The fuel and macro freezers grade the board's centre (#119, #120), but
every board they don't freeze is still centred by eye in the brief
(11/9: Hormuz week 8 "centred ~23", KXAAAGASM "~3.785", KXDIESELW-26NOV16
"~6.05"). `event` now ends with '# board centre: X', where the mids cross
0.5 between the two bracketing priced floors (the freezers' rule).
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import kalshi


def strike(floor, bid, ask, kind="greater"):
    return {"ticker": f"E-T{floor}", "strike_type": kind,
            "floor_strike": floor, "yes_bid_dollars": bid,
            "yes_ask_dollars": ask}


# KXHORMUZWEEKLY-26NOV08 as read live 2026-11-10 02:00 ET
HORMUZ = [strike(15, "0.9800", "0.9900"), strike(20, "0.9100", "0.9300"),
          strike(23, "0.4500", "0.5000"), strike(25, "0.3100", "0.3800"),
          strike(27, "0.0900", "0.1000"), strike(30, "0.0100", "0.0200"),
          strike(35, "0.0000", "0.0100")]


def test_centre_interpolates_between_the_bracketing_floors():
    side, v = kalshi.board_centre(HORMUZ)
    # 20 @ 0.92 -> 23 @ 0.475: 20 + 3 * 0.42 / 0.445
    assert side == "" and abs(v - (20 + 3 * 0.42 / 0.445)) < 1e-9


def test_centre_skips_empty_and_one_sided_books():
    # KXDIESELW-26NOV16 at its 13:01Z listing: every book "0.0000"/"0.0000",
    # and a "0.0100"/"0.9900" book is no price either
    ms = [strike(6.0, "0.0000", "0.0000"), strike(6.02, "0.0100", "0.9900"),
          strike(6.04, "0.6000", "0.6400"), strike(6.08, "0.2000", "0.2400")]
    side, v = kalshi.board_centre(ms)
    assert side == "" and abs(v - (6.04 + 0.04 * 0.12 / 0.40)) < 1e-9
    assert kalshi.board_centre(ms[:2]) == ("-", None)


def test_centre_off_the_ladder_says_which_side():
    assert kalshi.board_centre([strike(3.9, "0.2000", "0.2200"),
                                strike(4.0, "0.0500", "0.0700")]) == ("<", 3.9)
    assert kalshi.board_centre([strike(3.9, "0.8000", "0.8200"),
                                strike(4.0, "0.6000", "0.6200")]) == (">", 4.0)


def test_centre_ignores_bucket_markets():
    # KXHIGH-style 'between' buckets are no survival ladder
    ms = [dict(strike(70, "0.4000", "0.4400", kind="between"), cap_strike=71)]
    assert kalshi.board_centre(ms) == ("-", None)
    assert kalshi.centre_line(ms) is None
    # KXHIGHLAX-26NOV10 live: 'less'/'between' buckets plus one 'greater'
    # tail read '<89.0' before this guard
    ms += [strike(89, "0.0100", "0.0300"),
           dict(strike(None, "0.0100", "0.0300", kind="less"), cap_strike=80)]
    assert kalshi.centre_line(ms) is None


def test_centre_line_precision_follows_the_floors():
    assert kalshi.centre_line(HORMUZ) == "# board centre: 22.8"
    gas = [strike(3.975, "0.6900", "0.7200"), strike(3.98, "0.4200", "0.4600")]
    assert kalshi.centre_line(gas) == "# board centre: 3.9789"
    nfp = [strike(50000, "0.7000", "0.7400"), strike(75000, "0.4000", "0.4400")]
    assert kalshi.centre_line(nfp) == "# board centre: 68333"
    assert kalshi.centre_line([strike(1, "0.2", "0.3")]) == "# board centre: <1.0"
    assert (kalshi.centre_line([strike(1, "0.0000", "0.0000")])
            == "# board centre: - (no priced strike)")


def test_main_event_ends_with_the_centre_line(monkeypatch, capsys):
    monkeypatch.setattr(kalshi, "get_event", lambda et: {
        "event_ticker": et, "title": "Hormuz", "markets": HORMUZ})
    kalshi.main(["event", "KXHORMUZWEEKLY-26NOV08"])
    lines = capsys.readouterr().out.splitlines()
    assert lines[-1] == "# board centre: 22.8"
    assert len(lines) == 1 + len(HORMUZ) + 1


def test_main_event_without_a_ladder_prints_no_centre(monkeypatch, capsys):
    monkeypatch.setattr(kalshi, "get_event", lambda et: {
        "event_ticker": et, "title": "Rain", "markets": [
            {"ticker": "KXRAIN-26NOV10-DC", "yes_bid_dollars": "0.10",
             "yes_ask_dollars": "0.12"}]})
    kalshi.main(["event", "KXRAIN-26NOV10"])
    assert "centre" not in capsys.readouterr().out
