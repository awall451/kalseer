#!/usr/bin/env bash
# Kalseer morning-brief pipeline. Deterministic outer shell; headless Claude is
# one replaceable step. Every step is attempted even after a failure so the
# dashboard always redeploys with an honest status banner.
#
# Config (env):
#   KALSEER_DATA_DIR    mutable state: ledger, briefs, logs, public/ JSON
#                       (default: ./data — point it at your private data repo)
#   KALSEER_PORT        local dashboard port for docker compose (default: 8085)
#   KALSEER_DEPLOY      "compose" (default) runs `docker compose up -d`;
#                       "none" skips it (something else serves the dashboard)
#   KALSEER_HEALTH_URL  URL to curl after deploy
#                       (default: http://localhost:$KALSEER_PORT/data/aggregates.json)
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
export KALSEER_DATA_DIR="$(realpath -m "${KALSEER_DATA_DIR:-$ROOT/data}")"
DATA_DIR="$KALSEER_DATA_DIR"
PORT="${KALSEER_PORT:-8085}"
DEPLOY="${KALSEER_DEPLOY:-compose}"
HEALTH_URL="${KALSEER_HEALTH_URL:-http://localhost:$PORT/data/aggregates.json}"
STATUS_FILE="$DATA_DIR/public/status.json"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR" "$DATA_DIR/public"
LOG="$LOG_DIR/daily-$(date +%F).log"
exec >>"$LOG" 2>&1

echo "=== daily run $(date -Is) (data: $DATA_DIR) ==="
FAILED_STEP=""

run_step() { # run_step <name> <cmd...>
  local name="$1"; shift
  echo "--- step: $name"
  if "$@"; then
    echo "--- ok: $name"
  else
    local rc=$?
    echo "--- FAILED: $name (exit $rc)"
    [ -z "$FAILED_STEP" ] && FAILED_STEP="$name"
  fi
}

claude_step() {
  # 25-minute cap so a hung research session can't stall the pipeline
  timeout 1500 claude -p "Data directory: $DATA_DIR
$(cat bin/daily-prompt.md)" \
    --permission-mode default
}

run_step settle  python3 kalshi/paper.py settle
run_step scan    python3 kalshi/scanner.py --days 7 --min-volume 1000
run_step claude  claude_step

# Judgment step must leave a brief for today; if not, that's a failure too.
BRIEF="$DATA_DIR/brief-$(date +%F).json"
if [ ! -f "$BRIEF" ] && [ -z "$FAILED_STEP" ]; then
  echo "--- FAILED: claude (no $BRIEF produced)"
  FAILED_STEP="claude"
fi

run_step publish python3 kalshi/publish.py
if [ "$DEPLOY" = "compose" ]; then
  run_step deploy docker compose up -d
fi

# Write status.json (read by the dashboard banner) BEFORE the data-repo
# commit+push, so the served status reflects this run.
LAST_SUCCESS="$(python3 -c "
import json,sys,datetime
try: prev = json.load(open('$STATUS_FILE'))
except Exception: prev = {}
now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds')
ok = '$FAILED_STEP' == ''
json.dump({'ok': ok, 'failed_step': '$FAILED_STEP' or None,
           'finished_at': now,
           'last_success': now if ok else prev.get('last_success')},
          open('$STATUS_FILE','w'))
print('ok' if ok else 'failed')
")"
echo "--- status: $LAST_SUCCESS"

# Commit the day's data (audit trail) even on partial failure — the data dir
# is its own git repo (e.g. a private kalseer-data checkout). Push if it has
# a remote; skip silently if it isn't a repo at all.
if git -C "$DATA_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  OPENED="$(python3 -c "
import json
try: print(len(json.load(open('$BRIEF')).get('trades_opened',[])))
except Exception: print('?')
")"
  PNL="$(python3 -c "
import json
try: print('%+.2f' % json.load(open('$DATA_DIR/public/aggregates.json'))['stats']['total_pnl'])
except Exception: print('?')
")"
  git -C "$DATA_DIR" add -A
  if ! git -C "$DATA_DIR" diff --cached --quiet; then
    git -C "$DATA_DIR" commit -m "brief: $(date +%F) (pnl \$${PNL}, ${OPENED} opened)$(
      [ -n "$FAILED_STEP" ] && echo " [FAILED: $FAILED_STEP]")" || \
      { [ -z "$FAILED_STEP" ] && FAILED_STEP="git"; }
    if git -C "$DATA_DIR" remote get-url origin >/dev/null 2>&1; then
      run_step push git -C "$DATA_DIR" push
    fi
  fi
else
  echo "--- note: $DATA_DIR is not a git repo; skipping audit-trail commit"
fi

# Health last: with a git-synced dashboard the data has to land upstream first.
run_step health curl -sf -o /dev/null --retry 5 --retry-delay 5 "$HEALTH_URL"

echo "=== done $(date -Is) failed_step='${FAILED_STEP}' ==="
[ -z "$FAILED_STEP" ]
