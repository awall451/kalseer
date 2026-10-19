"""futures.py closes: a bar that repeats a recent close to the last digit.

Brief 10/18: "Wholesale finally reads consistently: ULSD 10/16 4.7232 (-12c)
... But 4.7232 matches the 10/12 settle to the last digit, so I'm keeping
10/16 unverified". #65 catches a last-trade quote equal to an older close,
but here the quote agreed with its bar: the BAR itself was the recycled
number, and only a hand comparison caught it (two runs running). A 4-digit
repeat within two weeks of sessions is a stale-feed signature, not a market.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures
from test_futures import body, ts

# the 10/18 read: 10/12..10/16 with 10/16 == 10/12, quote agreeing with it
WEEK = ([ts(12), ts(13), ts(14), ts(15), ts(16)],
        [4.7232, 4.9344, 4.9274, 4.8456, 4.723200035095215])


def run(monkeypatch, capsys, stamps, closes, last):
    monkeypatch.setattr(futures, "_fetch",
                        lambda s: body("HO=F", stamps, closes, last=last))
    futures.main(["closes", "ulsd"])
    return capsys.readouterr().out.splitlines()


def test_newest_bar_repeating_an_older_close_warns(monkeypatch, capsys):
    out = run(monkeypatch, capsys, *WEEK, last=(4.7232, ts(16, 14)))
    warns = [l for l in out if l.startswith("# WARNING")]
    assert len(warns) == 1
    assert "2026-10-16 bar 4.7232 repeats the 2026-10-12 close" in warns[0]
    assert "unverified" in warns[0]


def test_repeating_rows_are_tagged_in_the_table(monkeypatch, capsys):
    out = run(monkeypatch, capsys, *WEEK, last=(4.7232, ts(16, 14)))
    row = [l for l in out if l.startswith("2026-10-16")][0]
    assert "= 2026-10-12 close" in row
    assert not any("= 2026-" in l for l in out
                   if l.startswith(("2026-10-12", "2026-10-13")))


def test_no_repeat_no_warning(monkeypatch, capsys):
    stamps, closes = WEEK
    out = run(monkeypatch, capsys, stamps, closes[:-1] + [4.7101],
              last=(4.7101, ts(16, 14)))
    assert not any(l.startswith("# WARNING") for l in out)
    assert not any("close" in l for l in out if not l.startswith("#"))


def test_repeat_older_than_the_window_is_not_flagged(monkeypatch, capsys):
    days = list(range(1, 17))
    stamps = [ts(d) for d in days]
    closes = [4.0 + d / 100 for d in days]
    closes[-1] = closes[0]   # 10/16 repeats 10/1: 15 sessions back
    out = run(monkeypatch, capsys, stamps, closes,
              last=(closes[-1], ts(16, 14)))
    assert not any("repeats" in l for l in out)


def test_quote_conflict_warning_still_gets_its_own_line(monkeypatch, capsys):
    # #65's case: the quote disagrees with its bar -> both facts surface
    out = run(monkeypatch, capsys, *WEEK, last=(4.8991, ts(16, 14)))
    warns = [l for l in out if l.startswith("# WARNING")]
    assert len(warns) == 2
    assert any("disagrees" in w for w in warns)
    assert any("repeats" in w for w in warns)
