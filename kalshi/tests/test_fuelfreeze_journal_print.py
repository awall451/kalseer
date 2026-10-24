"""fuelfreeze.py score: an event scores off the AAA journal before Kalshi
settles it.

Every frozen event settles on the exact AAA print dated by its ticker, and
the aaa step journals that print minutes before the judgment step, but
Kalshi settles hours later. So the first weekly tally (KXDIESELW /
KXAAAGASW-26OCT26, op note 10/23: "read the paired line") would read
"pending" at Monday's run, as the daily diesel pre-reg did on 10/23 ("The
scoring tool shows them as pending until Kalshi settles").
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze
import fuelscore
from test_fuelfreeze_summary import rec, strike

EVENT = "KXDIESELW-26OCT26"


def run(tmp_path, monkeypatch, capsys, strikes, prints, results=None):
    journal = tmp_path / "fuel-freeze.jsonl"
    journal.write_text(json.dumps(rec(EVENT, "2026-10-26", strikes)) + "\n")
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    aaa = tmp_path / "prints.jsonl"
    aaa.write_text("".join(
        json.dumps({"date": d, "prices": {"current": {"diesel": f"${p}"}}})
        + "\n" for d, p in prints.items()))
    monkeypatch.setattr(fuelscore, "JOURNAL", aaa)
    results = results or {}
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event", lambda t: {
        "markets": [{"ticker": tk, "result": y, "expiration_value": "6.3"}
                    for tk, y in results.items()]})
    fuelfreeze.score()
    return capsys.readouterr().out


def test_unsettled_event_scores_off_the_journal_print(tmp_path, monkeypatch,
                                                      capsys):
    strikes = [strike(EVENT, 6.30, "0.4000", "0.5000", 0.8),
               strike(EVENT, 6.34, "0.2000", "0.3000", 0.1)]
    out = run(tmp_path, monkeypatch, capsys, strikes,
              {"2026-10-23": "6.3172", "2026-10-26": "6.3210"})
    line = [l for l in out.splitlines() if EVENT in l][0]
    assert "pending" not in line
    # 6.3210 > 6.30 YES, not > 6.34 NO: RW (0.04 + 0.01) / 2
    assert line.startswith(f"2026-10-26  {EVENT}  6.3210  k1")
    assert "RW 0.0250" in line
    # board mids 0.45 / 0.25: (0.3025 + 0.0625) / 2
    assert "BOARD 0.1825" in line
    assert line.endswith("(AAA journal, Kalshi unsettled)")
    assert "# n=1 settled events" in out


def test_no_journal_print_stays_pending(tmp_path, monkeypatch, capsys):
    strikes = [strike(EVENT, 6.30, "0.4000", "0.5000", 0.8)]
    out = run(tmp_path, monkeypatch, capsys, strikes,
              {"2026-10-23": "6.3172"})
    assert f"2026-10-26  {EVENT}  k1  pending" in out


def test_a_print_on_a_strike_skips_that_strike(tmp_path, monkeypatch, capsys):
    strikes = [strike(EVENT, 6.30, "0.4000", "0.5000", 0.8),
               strike(EVENT, 6.32, "0.4000", "0.5000", 0.5)]
    out = run(tmp_path, monkeypatch, capsys, strikes,
              {"2026-10-26": "6.3200"})
    line = [l for l in out.splitlines() if EVENT in l][0]
    # only >6.30 (YES) is scored: RW (0.8 - 1)^2
    assert "RW 0.0400" in line


def test_kalshi_settlement_still_wins(tmp_path, monkeypatch, capsys):
    strikes = [strike(EVENT, 6.30, "0.4000", "0.5000", 0.8)]
    out = run(tmp_path, monkeypatch, capsys, strikes,
              {"2026-10-26": "6.3210"},
              results={f"{EVENT}-T6.30": "no"})
    line = [l for l in out.splitlines() if EVENT in l][0]
    assert "RW 0.6400" in line
    assert "journal" not in line
