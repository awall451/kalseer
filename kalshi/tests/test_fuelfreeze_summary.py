"""fuelfreeze.py score: the summary counts every settled event, and compares
legs on the same strikes.

`fuelfreeze.py score` on 2026-10-22, the first two settled events:
KXDIESELD-26OCT21 (every book empty, so no BOARD Brier) and KXAAAGASD-26OCT21.
The summary said "# n=1 settled events ... BOARD 0.0927  RW 0.0811": n counted
only events with a board, and RW's mean ran over both events while BOARD's ran
over one, so the two numbers were not comparable. With every book empty the
summary vanished altogether. Now n is every settled event, a leg scored on
fewer events says so, and a paired line scores each model against BOARD on
exactly the board-priced strikes.
"""

import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import fuelfreeze


def strike(event, floor, bid, ask, p):
    return {"ticker": f"{event}-T{floor:.2f}", "floor": floor,
            "yes_bid": bid, "yes_ask": ask,
            "p": {"RW": p, "MOM": p, "DRIFT": p, "EMP": None}}


def rec(event, day, strikes):
    return {"event": event, "series": event.split("-")[0], "grade": "diesel",
            "date": day, "k": 1, "strikes": strikes}


def run(tmp_path, monkeypatch, capsys, recs, results):
    journal = tmp_path / "fuel-freeze.jsonl"
    journal.write_text("".join(json.dumps(r) + "\n" for r in recs))
    monkeypatch.setattr(fuelfreeze, "JOURNAL", journal)
    monkeypatch.setattr(fuelfreeze.kalshi, "get_event", lambda t: {
        "markets": [{"ticker": tk, "result": y, "expiration_value": "6.3174"}
                    for tk, y in results.items() if tk.startswith(t)]})
    fuelfreeze.score()
    return capsys.readouterr().out


def test_n_counts_events_without_a_board(tmp_path, monkeypatch, capsys):
    a = rec("KXDIESELD-26OCT21", "2026-10-21",
            [strike("KXDIESELD-26OCT21", 6.30, "0.0000", "0.0000", 1.0)])
    b = rec("KXAAAGASD-26OCT21", "2026-10-21",
            [strike("KXAAAGASD-26OCT21", 4.26, "0.4000", "0.5000", 1.0)])
    out = run(tmp_path, monkeypatch, capsys, [a, b],
              {"KXDIESELD-26OCT21-T6.30": "yes",
               "KXAAAGASD-26OCT21-T4.26": "yes"})
    summary = [l for l in out.splitlines() if l.startswith("# n=")][0]
    assert summary.startswith("# n=2 settled events")
    # BOARD is scored on one of the two events and says so; RW on both
    assert f"BOARD {0.55 ** 2:.4f} (n1)" in summary
    assert "RW 0.0000  " in summary


def test_summary_prints_when_no_event_has_a_board(tmp_path, monkeypatch,
                                                  capsys):
    a = rec("KXDIESELD-26OCT21", "2026-10-21",
            [strike("KXDIESELD-26OCT21", 6.30, "0.0000", "0.0000", 0.8)])
    out = run(tmp_path, monkeypatch, capsys, [a],
              {"KXDIESELD-26OCT21-T6.30": "yes"})
    assert "# n=1 settled events" in out
    assert f"RW {0.2 ** 2:.4f}" in out
    assert "same strikes" not in out
    assert "board-RW 0-0" in out


def test_paired_line_scores_models_on_board_priced_strikes_only(
        tmp_path, monkeypatch, capsys):
    e = "KXAAAGASD-26OCT21"
    a = rec(e, "2026-10-21",
            [strike(e, 4.24, "0.8000", "0.9000", 1.0),   # board 0.85
             strike(e, 4.26, "0.4000", "0.5000", 0.5),   # board 0.45
             strike(e, 4.28, "0.0000", "0.0000", 0.0)])  # no board
    out = run(tmp_path, monkeypatch, capsys, [a],
              {f"{e}-T4.24": "yes", f"{e}-T4.26": "yes", f"{e}-T4.28": "no"})
    pair = [l for l in out.splitlines() if "same strikes" in l][0]
    model = (0.0 + 0.25) / 2
    board = (0.15 ** 2 + 0.55 ** 2) / 2
    assert f"RW {model:.4f} vs BOARD {board:.4f} (m2)" in pair
    # EMP never priced these strikes, so it has no pair
    assert "EMP" not in pair
