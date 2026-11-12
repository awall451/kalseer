"""futures.py closes: say LIVE on a bar the exchange hasn't settled yet.

The judgment step runs ~08:00 ET, before the ~14:30 ET NYMEX settle, so the
newest bar it reads is usually today's live price. On 11/10 it read the
ULSD bar 4.0471 as the day's level; HOZ26 settled 4.1309, and the 11/11
brief concluded "live ULSD bars are unreliable" (it "overstated the drop by
8c"). The row only said `latest`, which a reader can take as a settle. The
archive already skips bars dated on or after the exchange's today; closes
now tags such a bar `LIVE` and names the newest settled close in the footer.
"""

import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parent))
from test_futures import api, body, data_lines, futures, ts  # noqa: F401


def test_todays_bar_before_settle_is_live(api, monkeypatch, capsys):
    monkeypatch.setattr(futures, "_now", lambda: ts(13, 8))  # 08:00 ET 10/13
    futures.main(["closes", "ulsd"])
    out = capsys.readouterr().out.splitlines()
    rows = [line for line in out if not line.startswith("#")]
    assert "LIVE" in rows[0]
    assert "LIVE" not in rows[1]
    footer = [line for line in out if line.startswith("# ulsd = HO=F")][0]
    assert "newest settled 2026-10-12 = 4.7232" in footer


def test_a_past_days_bar_is_not_live(api, monkeypatch, capsys):
    monkeypatch.setattr(futures, "_now", lambda: ts(14, 8))  # next morning
    futures.main(["closes", "ulsd"])
    out = capsys.readouterr().out
    assert "LIVE" not in out
    assert "newest settled" not in out


def test_prompt_names_the_live_tag():
    prompt = (pathlib.Path(__file__).parents[2] / "bin"
              / "daily-prompt.md").read_text()
    assert "`LIVE` row" in prompt
    assert "`newest settled`" in prompt


def test_live_tag_keeps_latest(api, monkeypatch, capsys):
    # older readers (and the prompt) key on `latest`
    monkeypatch.setattr(futures, "_now", lambda: ts(13, 8))
    futures.main(["closes", "ulsd"])
    assert "latest" in data_lines(capsys)[0]
