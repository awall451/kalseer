"""prereg.py edges --sd-mult K: replay the edges with every odds sd x K.

#143's by-cost split showed the losses sit in the cheap-ticket band (11/23,
26 events: gas MINE `<0.25 taken 83 won 1 (said 0.35)`, RW `<0.25 taken 249
won 0 (said 0.44)`), while the diesel mid band is about break-even. op-11-23
asked (note (b)) whether any sd multiplier brings the <0.25 band's "said"
near its hit rate: if one does, `SD_PER_MAE` is the knob; if none does, the
normal's shape is the problem. `--sd-mult K` reruns the same replay with
every forecaster's sd scaled by K, read-only, so the sweep is a tool line
and `odds` itself is unchanged.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import prereg
from test_prereg_odds import SD, _p, _write
from test_prereg_odds import env  # noqa: F401  (fixture)
from test_prereg_edges import EVENT, _frozen, _history, _line, _run


def test_edges_sd_mult_scales_every_sd(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys, "--sd-mult", "0.5")
    p20, p30 = _p(5.920, 5.9338, SD * 0.5), _p(5.930, 5.9338, SD * 0.5)
    claimed = (p20 - 0.62) + (p30 - 0.06)
    line = _line(out, f"2026-11-18  {EVENT}  = 5.9298  n2  ")
    assert f"MINE 5.9338 taken 2 claimed {claimed:+.2f} got +0.32" in line
    mine = (p20 - 1) ** 2 + p30 ** 2
    assert _line(out, "# edges KXDIESELD MINE (sd x0.50):").endswith(
        f"Brier {mine:.4f} vs BOARD {(0.61 - 1) ** 2 + 0.05 ** 2:.4f} "
        "over 2 strikes")


def test_edges_sd_mult_tags_the_summary_lines(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys, "--sd-mult", "2")
    # a multiplied replay never reads as the default line the prompt quotes
    assert not [l for l in out if l.startswith("# edges KXDIESELD MINE:")
                or l.startswith("# edges KXDIESELD MINE by cost:")]
    assert _line(out, "# edges KXDIESELD MINE (sd x2.00) by cost:")
    assert _line(out, "# edges: sd x2.00 (--sd-mult)").endswith(
        f"sd = {prereg.SD_PER_MAE * 2:.4f} x MAE")


def test_edges_sd_mult_one_is_the_default_output(env, capsys):
    _write(_history() + [_frozen()])
    assert _run(capsys, "--sd-mult", "1") == _run(capsys)


def test_edges_sd_mult_combines_with_days_and_prefix(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys, "--days", "30", "--sd-mult", "0.5", "KXDIESELD")
    assert _line(out, "# edges KXDIESELD MINE (sd x0.50):")
    out = _run(capsys, "--sd-mult", "0.5", "--days", "30", "KXDIESELD")
    assert _line(out, "# edges KXDIESELD MINE (sd x0.50):")


def test_edges_sd_mult_keeps_the_sd_floor(env, capsys):
    _write(_history() + [_frozen()])
    out = _run(capsys, "--sd-mult", "0.0001")
    floor = prereg.fuelfreeze.SD_FLOOR
    p20, p30 = _p(5.920, 5.9338, floor), _p(5.930, 5.9338, floor)
    mine = (p20 - 1) ** 2 + p30 ** 2
    assert f"Brier {mine:.4f} vs BOARD" in _line(
        out, "# edges KXDIESELD MINE (sd x0.00):")


def test_prompt_names_the_sd_mult_sweep():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "`python3 kalshi/prereg.py edges --sd-mult K`" in prompt
