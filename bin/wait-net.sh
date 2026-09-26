#!/usr/bin/env bash
# Hold a pipeline run until the network answers. A Persistent= catch-up run
# (host asleep at the scheduled time) fires the moment the machine wakes,
# sometimes before DNS is up: gap #1 (2026-08-31..09-02) burned the whole
# 14:09 catch-up run — settle, scan, publish, push, AND the failure alert —
# on name-resolution errors.
#
# Usage: wait-net.sh [<probe-url>] [<max-wait-secs>] [<poll-secs>]
# Defaults: probe api.elections.kalshi.com (a host the run needs anyway,
# overridable via KALSEER_NET_PROBE_URL), wait up to 600s
# (KALSEER_NET_WAIT), poll every 15s.
# Exit codes:
#   0  the probe answered — the run can do its job
#   1  deadline passed with no network; the caller decides how to degrade
set -u

URL="${1:-${KALSEER_NET_PROBE_URL:-https://api.elections.kalshi.com/trade-api/v2/exchange/status}}"
MAX="${2:-${KALSEER_NET_WAIT:-600}}"
POLL="${3:-15}"

DEADLINE=$(( $(date +%s) + MAX ))
while true; do
  curl -sf --max-time 10 -o /dev/null "$URL" && exit 0
  [ "$(date +%s)" -ge "$DEADLINE" ] && exit 1
  sleep "$POLL"
done
