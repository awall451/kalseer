# Kalseer

**A Kalshi paper-trading experiment with a daily AI research pipeline and a
morning-brief dashboard.**

Every morning, a pipeline settles yesterday's positions against the live
Kalshi API, scans ~300k open markets for research candidates, hands the short
list to a headless [Claude Code](https://claude.com/claude-code) session that
researches them against primary sources (settlement-source data, weather
station observations, review aggregators, econ nowcasts), opens paper trades
within hard code-enforced guardrails, and publishes a static dashboard with an
equity curve, a calibration chart, and a daily brief explaining every decision.

> **This is an experiment, not financial advice.** Kalseer trades pretend
> money to measure whether careful research has any fee-adjusted edge in thin
> prediction markets. Nothing here recommends real trades, and past paper
> performance predicts nothing. If you point it at real money, that's on you.

## How it works

```
systemd timer (08:00)
  └─ bin/daily.sh
       ├─ paper.py settle      settle finished markets against the live API
       ├─ scanner.py           scan + rank research candidates
       ├─ claude -p            headless research & judgment (bin/daily-prompt.md)
       ├─ publish.py           ledger + briefs → <data dir>/public/ JSON
       ├─ docker compose up    serve the dashboard (local mode)
       └─ git commit + push    audit trail in your private data repo
```

The judgment step is sandboxed by design: guardrails live in `paper.py`
(**max 3 trades/day, ≤10% of equity per position, ≤40% total exposure**) and
are enforced in code, not in the prompt — a bad reasoning day can't blow up
the bankroll. A no-trade day is a valid outcome; the brief just explains why.

Every position records the model's fair-value estimate, so the dashboard
tracks **calibration** (when it says 70%, does it happen 70% of the time?)
alongside P&L — honest measurement is the entire point.

## Layout

- `kalshi/kalshi.py` — public API client (stdlib-only, no auth) + taker-fee math
- `kalshi/scanner.py` — scan open markets, filter parlays/dead markets, rank
  candidates → `<data dir>/candidates-YYYY-MM-DD.json`
- `kalshi/paper.py` — paper ledger: `open` / `settle` / `status` / `report`
- `kalshi/publish.py` — ledger + briefs → `<data dir>/public/` JSON for the dashboard
- `kalshi/tests/` — pytest for the money math
- `bin/daily.sh` — pipeline orchestrator; `bin/daily-prompt.md` — instructions
  for the headless judgment step
- `frontend/` — Svelte 5 + Vite + ECharts dashboard (`npm run build` → `site/`)
- `systemd/` — user timer unit templates
- `.claude/settings.json` — permission allowlist for the headless step

## Data lives outside this repo

The engine repo never contains trading data. All mutable state — portfolio,
settled trades, daily briefs, watchlist, logs, and the published dashboard
JSON — lives in `KALSEER_DATA_DIR` (default: `./data`, gitignored).

Make that directory its own **private** git repo and `daily.sh` will commit
and push the day's changes automatically — a tamper-evident audit trail of
every trade and brief. If it's not a git repo, the commit step is skipped.

```
<data dir>/
  portfolio.json           open positions + bankroll
  closed.jsonl             settled trades (feeds the calibration report)
  watchlist.json           markets to re-check in a future date window
  candidates-YYYY-MM-DD.json
  brief-YYYY-MM-DD.json    daily narrative + trades
  series-cache.json
  logs/                    pipeline logs
  public/                  JSON the dashboard fetches (served at ./data/)
```

## Setup

Requirements: Python 3.11+ (stdlib only), Node 20+ (dashboard build), Docker
(local serving), and the [`claude` CLI](https://claude.com/claude-code) with an
active subscription — the research step runs `claude -p` headlessly.

```bash
git clone https://github.com/<you>/kalseer && cd kalseer

# 1. tests
python3 -m pytest kalshi/tests/

# 2. build the dashboard
(cd frontend && npm install && npm run build)

# 3. create your data dir (ideally a private git repo)
git init data   # or: export KALSEER_DATA_DIR=~/kalseer-data

# 4. one manual run end-to-end
bin/daily.sh
# watch: tail -f data/logs/daily-$(date +%F).log

# 5. dashboard
open http://localhost:8085
```

### Schedule it

```bash
mkdir -p ~/.config/systemd/user
cp systemd/kalseer-daily.{service,timer} ~/.config/systemd/user/
# edit kalseer-daily.service: set the real /path/to/kalseer + env config
systemctl --user daemon-reload
systemctl --user enable --now kalseer-daily.timer
```

`Persistent=true` means a missed 08:00 (machine asleep) runs on next boot.

### Configuration

| Env var | Default | Meaning |
|---|---|---|
| `KALSEER_DATA_DIR` | `./data` | where all mutable state lives |
| `KALSEER_PORT` | `8085` | local dashboard port (docker compose) |
| `KALSEER_DEPLOY` | `compose` | `none` = something else serves the dashboard |
| `KALSEER_HEALTH_URL` | `http://localhost:$PORT/data/aggregates.json` | post-run healthcheck |
| `KALSEER_STARTING_BANKROLL` | `500` | pretend dollars at t=0 |

If `KALSEER_DATA_DIR` is outside the repo, mirror it in
`.claude/settings.local.json` so the headless step may write there, e.g.
`"Write(//home/you/kalseer-data/**)"`.

## Dashboard

Today's brief by default, date picker for history, equity curve and
calibration charts from all-time data, live status banner (red when a pipeline
step failed), dark/light theme.

There's also a **wiki tab** (`#/wiki/<slug>`): markdown pages in
`frontend/src/content/` (manifest in `manifest.json`) with admonition callouts
(`!!! warning "Title"`), auto-TOC, heading anchors, client-side search, and
`{{token}}` fills from live stats (see `statsTokens` in
`frontend/src/lib/wiki.js`). Adding a page = new `.md` + manifest entry +
`npm run build`.

## License

MIT — see [LICENSE](LICENSE).
