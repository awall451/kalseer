#!/usr/bin/env bash
# Fast-forward an engine checkout to origin before a pipeline run, so PRs the
# nightly operator merged overnight actually reach production. (Found
# 2026-09-23: nothing deployed the engine — operator.sh keeps the pipeline's
# checkout pristine on purpose, daily.sh never pulled, and the checkout was
# running three merged PRs behind.)
#
# Usage: self-update.sh <repo-root> [<watch-file>]
# Exit codes:
#   0  up to date, updated, or safely skipped (dirty tree, diverged history,
#      unreachable remote) — never fails the caller's run
#   3  updated AND <watch-file> changed: the caller should re-exec itself
set -u

ROOT="$1"; WATCH="${2:-}"
cd "$ROOT" || exit 0

# Never touch a tree with local edits — a human mid-change beats freshness.
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "self-update: working tree dirty, skipping"
  exit 0
fi

BEFORE="$(git rev-parse HEAD)"
# ff-only: refuses on diverged history rather than inventing a merge commit.
if ! git pull --ff-only; then
  echo "self-update: pull failed, continuing on $(git rev-parse --short HEAD)"
  exit 0
fi
AFTER="$(git rev-parse HEAD)"
[ "$BEFORE" = "$AFTER" ] && exit 0

echo "self-update: ${BEFORE:0:7} -> ${AFTER:0:7}"
if [ -n "$WATCH" ] && ! git diff --quiet "$BEFORE" "$AFTER" -- "$WATCH"; then
  exit 3
fi
exit 0
