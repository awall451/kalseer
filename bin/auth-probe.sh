#!/usr/bin/env bash
# Probe the claude CLI's credentials the evening before they're needed.
#
# Gap #2 (2026-09-06..09-17): a silent OAuth expiry cost 12 straight briefs.
# daily.sh names the condition reactively (operator item #18), but at 08:00
# the run is already lost and the human is asleep. This spends one trivial
# claude call on an evening timer instead: a dead login alerts a human who
# is awake, with the whole evening to /login before the next brief.
#
# Usage: auth-probe.sh   (see systemd/kalseer-authprobe.timer; alerts via
#                         the same KALSEER_ALERT_URL / KALSEER_ALERT_CMD
#                         the pipeline uses)
# Exit codes:
#   0  credentials work — or no network, which is not an auth verdict
#   1  probe failed; alert sent best-effort
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# No network is not an auth failure (and the alert could not send anyway):
# skip quietly, the morning run's own gate handles that class.
if ! bash "$ROOT/bin/wait-net.sh" "" "${KALSEER_AUTHPROBE_NET_WAIT:-60}" 5; then
  echo "auth-probe: no network; skipping (not an auth verdict)"
  exit 0
fi

OUT="$(mktemp)"
trap 'rm -f "$OUT"' EXIT

timeout "${KALSEER_AUTHPROBE_TIMEOUT:-300}" claude -p "Reply with exactly: ok" \
  --permission-mode default >"$OUT" 2>&1
RC=$?
# Same failure signature daily.sh greps for reactively — an expired login
# has surfaced in output with a success exit code before.
if [ "$RC" -eq 0 ] && \
   ! grep -qiE "oauth.*(expired|could not be refreshed)|failed to authenticate" "$OUT"; then
  echo "auth-probe: ok"
  exit 0
fi

echo "auth-probe: FAILED (exit $RC)"
cat "$OUT"
MSG="$(date +%F): claude CLI auth probe FAILED this evening — ssh to the \
pipeline host and run 'claude' to /login tonight, or tomorrow's 08:00 brief \
is lost. Tail: $(tail -c 200 "$OUT" | tr '\n' ' ')"
# A CLI too old for the pinned model fails this probe too (2026-10-02..10-08,
# 7 briefs) — and /login would not fix it; say what will.
if grep -qiE "does not support this model|or newer is required" "$OUT"; then
  MSG="$(date +%F): claude CLI too OLD for the configured model — ssh to the \
pipeline host and run 'claude update' tonight, or tomorrow's 08:00 brief is \
lost. Tail: $(tail -c 200 "$OUT" | tr '\n' ' ')"
fi
[ -n "${KALSEER_ALERT_CMD:-}" ] && $KALSEER_ALERT_CMD "$MSG" || true
[ -n "${KALSEER_ALERT_URL:-}" ] && \
  curl -sf --max-time 15 -H "Title: kalseer" -d "$MSG" "$KALSEER_ALERT_URL" \
    >/dev/null || true
exit 1
