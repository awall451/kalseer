"""prereg.py edges: replay `odds` on each frozen board and score the edges.

#140's `odds` prints a YES/NO edge per strike, and the daily passes read
large ones every day (11/19 "MINE puts P(>5.900) ~0.73 vs ask 0.06", 11/20
"MINE P(>5.860) 0.92 vs ask 0.74") and pass them because the board keeps
the better centre record. op-2026-11-20 flagged that a model whose
MAE-based tails leave +0.4-0.8 "edges" while the board keeps winning may be
mis-specified at the tails. Nothing measured it: the judgment step would
have to freeze `add EVENT MINE` probabilities every day. `edges` replays
`odds` on the board each daily point row froze, takes every edge >= 0.10 at
the frozen quote, and scores it on the print: claimed vs realized, and each
forecaster's Brier against the board's.
"""

import math
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg
from test_prereg_odds import DIESEL, SD, _day, _event, _p, _point, _write
from test_prereg_odds import env  # noqa: F401  (fixture)

EVENT = "KXDIESELD-26NOV19"  # printed 5.9298
AT = "2026-11-18T13:04:00+00:00"


def _history(n=6):
    """n scored MINE points ending 11/18, each 0.40c off (signs alternate)."""
    out = []
    for i in range(n):
        day = _day(17 - i)
        sign = 1 if i % 2 else -1
        value = float(DIESEL[17 - i]) + 0.0040 * sign
        out.append(_point(_event(day), f"{value:.4f}",
                          at=f"{day}T00:00:00+00:00"))
    return out


def _frozen(value="5.9338", event=EVENT, at=AT, board=None):
    row = _point(event, value, at=at)
    row["board"] = board if board is not None else {
        f"{event}-T5.920": ["0.6000", "0.6200"],
        f"{event}-T5.930": ["0.0400", "0.0600"],
        f"{event}-T5.940": ["0.0000", "0.0000"]}
    return row


def _run(capsys, *args):
    capsys.readouterr()
    prereg.main(["edges", *args])
    return capsys.readouterr().out.splitlines()


def _line(out, start):
    return next(l for l in out if l.startswith(start))


def test_edges_takes_each_edge_at_the_frozen_quote(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys)
    assert out[0].startswith("# edges: ")
    p20, p30 = _p(5.920, 5.9338), _p(5.930, 5.9338)
    claimed = (p20 - 0.62) + (p30 - 0.06)
    # T5.920 YES at 0.62 wins (+0.38), T5.930 YES at 0.06 loses (-0.06);
    # the empty T5.940 book is not a trade
    line = _line(out, f"2026-11-18  {EVENT}  = 5.9298  n2  ")
    assert f"MINE 5.9338 taken 2 claimed {claimed:+.2f} got +0.32" in line


def test_edges_summary_scores_claimed_realized_and_brier(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys)
    p20, p30 = _p(5.920, 5.9338), _p(5.930, 5.9338)
    claimed = (p20 - 0.62) + (p30 - 0.06)
    mine = (p20 - 1) ** 2 + p30 ** 2
    board = (0.61 - 1) ** 2 + 0.05 ** 2
    assert _line(out, "# edges KXDIESELD MINE:") == (
        f"# edges KXDIESELD MINE: n=1 events, taken 2 (edge >= 0.10), won 1, "
        f"claimed {claimed:+.2f} got +0.32 per contract; Brier {mine:.4f} vs "
        f"BOARD {board:.4f} over 2 strikes")


def test_edges_a_small_edge_is_scored_but_not_taken(env, capsys):
    # MINE P(>5.930) at a centre of 5.9338 is about 0.78: under 0.10 off
    # an 0.70 ask, so no trade, but the strike still counts in the Brier
    p30 = _p(5.930, 5.9338)
    assert 0 < p30 - 0.70 < prereg.EDGE_MIN
    _write(_history() + [_frozen(board={f"{EVENT}-T5.930": ["0.6800",
                                                            "0.7000"]})])
    out = _run(capsys)
    assert "MINE 5.9338 taken 0 claimed +0.00 got +0.00" in _line(
        out, f"2026-11-18  {EVENT}")
    assert "taken 0 (edge >= 0.10), won 0" in _line(
        out, "# edges KXDIESELD MINE:")
    assert f"Brier {p30 ** 2:.4f}" in _line(out, "# edges KXDIESELD MINE:")


def test_edges_takes_the_no_side_under_the_bid(env, capsys):
    p = _p(5.930, 5.9218)  # MINE low: the 0.60 bid is far above it
    _write(_history() + [_frozen("5.9218", board={
        f"{EVENT}-T5.930": ["0.6000", "0.6200"]})])
    out = _run(capsys)
    # NO at 1 - 0.60 = 0.40, and the print 5.9298 settles NO: +0.60
    assert (f"MINE 5.9218 taken 1 claimed {0.60 - p:+.2f} got +0.60"
            in _line(out, f"2026-11-18  {EVENT}"))


def test_edges_skips_a_print_on_a_strike_and_pends_unprinted(env, capsys):
    _write(_history() + [
        _frozen(board={f"{EVENT}-T5.9298": ["0.4000", "0.4200"],
                       f"{EVENT}-T5.920": ["0.6000", "0.6200"]}),
        _frozen(event="KXDIESELD-26NOV20", at="2026-11-19T13:04:00+00:00",
                board={"KXDIESELD-26NOV20-T5.900": ["0.0400", "0.0600"]})])
    out = _run(capsys)
    assert f"2026-11-18  {EVENT}  = 5.9298  n1  " in "\n".join(out)
    assert "2026-11-19  KXDIESELD-26NOV20  pending" in out


def test_edges_uses_the_first_point_rows_board(env, capsys):
    late = _frozen("5.9500", at="2026-11-18T20:00:00+00:00", board={
        f"{EVENT}-T5.930": ["0.9000", "0.9200"]})
    late["leg"] = "MINE2"
    _write(_history() + [_frozen(), late])
    line = _line(_run(capsys), f"2026-11-18  {EVENT}")
    assert "n2" in line.split()  # the 13:04 board's two priced strikes
    assert "MINE2 5.9500 (n0: no odds)" in line  # no scored MINE2 history


def test_edges_filters_by_prefix_and_window(env, capsys):
    rows = _history()
    old = "KXDIESELD-26NOV13"
    assert rows[5]["event"] == old
    rows[5]["board"] = {f"{old}-T5.990": ["0.4000", "0.6000"]}
    _write(rows + [_frozen()])
    assert not any(l.startswith("2026-11-18  ")
                   for l in _run(capsys, "KXAAAGASD"))
    assert any(l.startswith(f"2026-11-18  {EVENT}")
               for l in _run(capsys, "--days", "0"))
    # the window counts back from the newest printed event: 11/19's print
    # day, so 11/13's goes at --days 3
    assert any(old in l for l in _run(capsys))
    assert not any(old in l for l in _run(capsys, "--days", "3"))


def test_edges_never_reads_the_live_board(env, capsys, monkeypatch):
    monkeypatch.setattr(prereg.kalshi, "get_event", lambda t: pytest.fail(
        "edges is offline"))
    _write(_history() + [_frozen()])
    assert _run(capsys)


def test_prompt_names_the_edges_verb():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "prereg.py edges [--days N] [PREFIX]" in prompt
    assert "# edges KXDIESELD MINE:" in prompt


def test_sd_matches_odds():
    assert math.isclose(SD, 0.0040 * prereg.SD_PER_MAE)
