# How this dashboard works

The morning brief is the visible end of an automated pipeline that runs on this machine every day at **8:00 AM** (systemd timer; if the PC was off, it catches up at next boot).

## Live numbers (from today's data)

Current bankroll **{{bankroll}}** · equity **{{equity}}** · at risk **{{exposure}}** across **{{open_positions}}** open positions · **{{settled}}** settled trades · win rate **{{win_rate}}** · total P&L **{{total_pnl}}** · fees paid **{{fees_paid}}**.

(These fill from the same data the dashboard charts read — they're live, not typed.)

## The daily pipeline

```
08:00 systemd timer → bin/daily.sh
  1. settle   — check the API, close any finished positions
  2. scan     — pull ~300k open markets, filter to liquid, near-term candidates
  3. claude   — headless Claude researches candidates against primary
                sources, opens edge-positive paper trades, writes the brief
  4. publish  — regenerate the JSON this dashboard reads
  5. deploy   — nginx container serves the updated site
  6. commit   — everything lands in git as a timestamped audit trail
```

Steps 1, 2, 4, 5, 6 are dumb scripts. Step 3 is the judgment: reading settlement fine print, checking AAA/NWS/Rotten Tomatoes numbers, estimating fair probabilities, and deciding what (if anything) is worth a paper trade.

## The guardrails

Enforced in code, not in the prompt — a confused AI morning can't override them:

- Max **3 new positions** per day
- Max **10% of equity** per position
- Max **40% of equity** at risk total

A rejected trade prints `REJECTED` with the reason and the pipeline moves on. Rejection is data.

## What the charts mean

- **Equity over time** — bankroll plus open positions at cost. The "is this working" line.
- **Calibration (said vs happened)** — every settled trade recorded a fair-value estimate at entry. Buckets compare *stated* probability to *actual* win rate. Honest system: this chart is allowed to look bad; it's not allowed to lie.
- **Brier score** (stat tile) — one-number calibration: 0 is an oracle, 0.25 is coin-flip guessing.

## Paper vs real

Everything here is **paper money** — a $500 pretend bankroll. The experiment: 4 weeks, ~50 settled trades, then a decision.

!!! important "The Phase 2 gate"
    Real money only if ALL hold: (1) ROI after fees positive across the sample, not rescued by one lucky hit; (2) calibration tracks the diagonal; (3) guardrails never had to save the system from itself; (4) four weeks of unattended 8am runs with no babysitting.

## Failure honesty

If any step fails, the dashboard shows a red banner naming the failed step, and a "stale data" banner if the last successful run is older than 36 hours. The git log keeps every day's brief, reasoning, and results — including the losing ones. The audit trail is the product.
