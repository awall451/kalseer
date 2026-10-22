## What

This is the same bug class that #77 fixed in fuelfreeze, in the three other board scorers. The operator memory (2026-10-21) records it: "Kalshi reports an empty book as the strings "0.0000"/"0.0000" (truthy!), and a one-sided one as e.g. "0.0100"/"0.9900". Any mid/board logic must check `bid < ask` and the spread, not truthiness." The live trigger was daily-2026-10-20.log, where every KXDIESELD-26OCT21 strike printed `board 0.00` off an empty book.

`prereg.py`, `highfreeze.py` and `rainfreeze.py` still used the truthy `bid and ask` check:
- **prereg score:** an empty book scored BOARD at a mid of **0.00**, so a YES outcome cost the board 1.0. The intended rule for an unpriced market is 0.5, which costs 0.25. A 0.01/0.99 book scored as 0.50.
- **highfreeze score:** an empty bucket entered the all-bucket MKT leg at 0.00, and a one-sided tail bucket entered at 0.50.
- **rainfreeze score:** MKT got a mid of 0.00 off an empty book.

The current journals show **0 incidences** (I counted 15 rain, 84 high-bucket and 14 prereg quotes), so no past score changes. This is hardening before the bad case shows up. The KXDIESELD daily books are routinely empty at the 12Z freeze (brief 10/21: "The diesel daily book is empty"). So the first daily-fuel `prereg.py add` would hit the prereg case.

## Why this fixes it

- **New shared helper.** `kalshi.board_mid(bid, ask)` uses the #77 rule: Decimal, `bid < ask <= bid + MAX_SPREAD (0.20)`, else None.
- **The three scorers now call it,** each keeping its existing None semantics:
  - prereg: unpriced, scored 0.5;
  - highfreeze: no MKT leg that day;
  - rainfreeze: `MKT -`.
- **fuelfreeze is deliberately untouched** so it can't conflict with tonight's #79. Its `_mid` is the same rule.

## How verified

- I wrote 5 tests in a new file, `kalshi/tests/test_board_mid.py`. All 5 fail on main and pass on this branch.
- `python3 -m pytest -q kalshi/tests`: 439 passed.
- **Live regression check** (read-only Kalshi): the `highfreeze.py score`, `rainfreeze.py score` and `prereg.py score` summaries against the real journals are identical before and after:
  - highfreeze: `RAW B 0.8034  MKT B 0.4048`
  - rainfreeze: `RAW 0.1193  MKT 0.0001`
  - prereg: both rows still pending.
- These PR hunks don't overlap #79, which only touches `fuelfreeze.py` and its own new test file.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
