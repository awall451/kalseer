#!/usr/bin/env bash
# Kalseer nightly operator: a headless Claude session that works through the
# backlog the daily judgment step emits (operator items in briefs/watchlist),
# one PR per item, then this script — not the model — merges the PRs whose CI
# is green. Deterministic outer shell, same shape as daily.sh.
#
# Config (env):
#   KALSEER_DATA_DIR          data repo checkout (briefs, watchlist, logs) — required
#   KALSEER_OPERATOR_WORKDIR  dedicated engine checkout the operator may dirty
#                             (default: ~/kalseer-op; NEVER the pipeline's checkout)
#   KALSEER_OPERATOR_TIMEOUT  wall-clock cap for the Claude session in seconds
#                             (default: 5400 = 90 min)
#   KALSEER_ALERT_URL         same ntfy-style endpoint daily.sh uses (optional)
#   GH_TOKEN / gh auth        gh CLI must be authenticated with repo scope
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATA_DIR="$(realpath -m "${KALSEER_DATA_DIR:?KALSEER_DATA_DIR is required}")"
WORK="${KALSEER_OPERATOR_WORKDIR:-$HOME/kalseer-op}"
REPO_URL="$(git -C "$ROOT" remote get-url origin)"
LOG_DIR="$DATA_DIR/logs"
mkdir -p "$LOG_DIR"
LOG="$LOG_DIR/operator-$(date +%F).log"
exec >>"$LOG" 2>&1

echo "=== operator run $(date -Is) (work: $WORK) ==="
FAILED=""

alert() { # best-effort, never fails the run
  [ -n "${KALSEER_ALERT_URL:-}" ] && \
    curl -sf --max-time 15 -H "Title: kalseer operator" -d "$1" "$KALSEER_ALERT_URL" \
      >/dev/null || true
  return 0
}

# --- fresh, disposable checkout (the pipeline's checkout stays pristine) ---
if [ ! -d "$WORK/.git" ]; then
  git clone "$REPO_URL" "$WORK" || { alert "operator: clone failed"; exit 1; }
fi
cd "$WORK"
git fetch origin || { alert "operator: fetch failed"; exit 1; }
git checkout -B main origin/main
git clean -fd

# --- the improvement session -----------------------------------------------
# One PR per item, labeled 'operator'. The model opens PRs; it never merges.
gh label create operator --force --color 5319e7 \
  --description "opened by the nightly operator session" >/dev/null 2>&1 || true

timeout "${KALSEER_OPERATOR_TIMEOUT:-5400}" claude -p "Data directory: $DATA_DIR
Time budget: you are running under a $((${KALSEER_OPERATOR_TIMEOUT:-5400}/60))-minute wall clock; leave the last 10 minutes for wrap-up.
$(cat "$WORK/bin/operator-prompt.md")" \
  --settings "$WORK/bin/operator-settings.json" \
  --permission-mode acceptEdits || { FAILED="claude"; echo "--- FAILED: claude session (exit $?)"; }

# --- deterministic merge gate ----------------------------------------------
# Auto-merge operator PRs when CI is green, UNLESS they touch paths that
# guard the loop itself (its own charter, or the CI that gates the merges).
# Those stay open for a human.
PROTECTED='^(\.github/workflows/|bin/operator)'
opened=0; merged=0; held=0; red=0
for pr in $(gh pr list --label operator --state open --json number -q '.[].number'); do
  opened=$((opened+1))
  if gh pr diff "$pr" --name-only | grep -qE "$PROTECTED"; then
    echo "--- PR #$pr touches protected paths; leaving open for review"
    gh pr comment "$pr" -b "operator: touches protected paths (charter/CI) — auto-merge skipped, needs a human." >/dev/null || true
    held=$((held+1)); continue
  fi
  if gh pr checks "$pr" --watch --fail-fast; then
    if gh pr merge "$pr" --squash --delete-branch; then
      echo "--- merged PR #$pr"; merged=$((merged+1))
    else
      echo "--- merge failed for PR #$pr"; held=$((held+1))
    fi
  else
    echo "--- PR #$pr CI red; leaving open"; red=$((red+1))
  fi
done

# --- audit trail into the data repo ----------------------------------------
if git -C "$DATA_DIR" rev-parse --git-dir >/dev/null 2>&1; then
  git -C "$DATA_DIR" add -A
  git -C "$DATA_DIR" diff --cached --quiet || {
    git -C "$DATA_DIR" commit -m "operator: $(date +%F) (${opened} PRs, ${merged} merged, ${held} held, ${red} red)$([ -n "$FAILED" ] && echo " [FAILED: $FAILED]")"
    git -C "$DATA_DIR" push || true
  }
fi

MSG="$(date +%F): operator run — ${opened} PRs opened, ${merged} auto-merged, ${held} held for review, ${red} CI-red$([ -n "$FAILED" ] && echo " (claude session FAILED — check $LOG)")"
alert "$MSG"
echo "=== done $(date -Is) $MSG ==="
[ -z "$FAILED" ]
