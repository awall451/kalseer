"""prereg.py edges: split each forecaster's taken edges by what they cost.

#142's `edges` showed every forecaster's >= 0.10 odds edges losing on both
fuels (11/22, 26 events: gas MINE taken 95 won 5 got -5.96, diesel MINE
taken 47 won 12 got -0.83), and op-2026-11-21 asked whether those losses
are the cheap lottery tickets (a YES at ask 0.06, a NO under a 0.98 bid)
or the mid-range edges the prompt's ~10c rule is about. A pooled line
can't say. A `# edges SERIES TAG by cost:` line splits the trades by the
price of the side taken (ask for YES, 1 - bid for NO) and puts the
forecaster's own mean P of winning next to how many won.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg
from test_prereg_odds import _p, _write
from test_prereg_odds import env  # noqa: F401  (fixture)
from test_prereg_edges import EVENT, _frozen, _history, _line, _run


def test_edges_by_cost_splits_cheap_from_mid_range(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys)
    p20, p30 = _p(5.920, 5.9338), _p(5.930, 5.9338)
    # T5.930 YES at 0.06 is a cheap ticket that loses; T5.920 YES at 0.62 is
    # mid-range and wins
    assert _line(out, "# edges KXDIESELD MINE by cost:") == (
        f"# edges KXDIESELD MINE by cost: <0.25 taken 1 won 0 (said "
        f"{p30:.2f}) got -0.06 | 0.25-0.75 taken 1 won 1 (said {p20:.2f}) "
        f"got +0.38 | >0.75 taken 0")


def test_edges_by_cost_prices_a_no_at_one_minus_the_bid(env, capsys):
    p = _p(5.930, 5.9218)
    _write(_history() + [_frozen("5.9218", board={
        f"{EVENT}-T5.930": ["0.9800", "0.9900"]})])
    out = _run(capsys)
    # NO under a 0.98 bid costs 0.02: a cheap ticket, and the print 5.9298
    # settles NO, so it wins +0.98
    assert _line(out, "# edges KXDIESELD MINE by cost:") == (
        f"# edges KXDIESELD MINE by cost: <0.25 taken 1 won 1 (said "
        f"{1 - p:.2f}) got +0.98 | 0.25-0.75 taken 0 | >0.75 taken 0")


def test_edges_by_cost_bands_are_the_constant():
    assert prereg.COST_BANDS == (0.25, 0.75)


def test_edges_pooled_line_is_unchanged_by_the_split(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys)
    pooled = [l for l in out if l.startswith("# edges KXDIESELD MINE")]
    assert len(pooled) == 2
    assert pooled[0].startswith("# edges KXDIESELD MINE: n=1 events, taken 2")


def test_prompt_names_the_by_cost_line():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "# edges KXDIESELD MINE by cost:" in prompt
