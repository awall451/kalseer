"""The judgment step's allowlist survives scripted edits.

.claude/settings.json is harness-protected, so every operator change to it
lands via a raw python script (PRs #14, #23, #27 so far). A typo there would
not fail the pipeline — the run would "succeed" while every research fetch
silently fell back to denied, costing a full day of judgment with no alert.
CI is the only place to catch that before merge.

bin/operator-settings.json gets the same parse check (read-only: the file
itself is off-limits to the operator by charter).
"""

import json
import pathlib

REPO = pathlib.Path(__file__).parents[2]
JUDGMENT = REPO / ".claude" / "settings.json"
OPERATOR = REPO / "bin" / "operator-settings.json"

# Tools the daily prompt and watchlist recipes depend on every single run.
# Additions never break this; an edit that clobbers instead of appends does.
CORE_JUDGMENT_GRANTS = [
    "Bash(python3 kalshi/paper.py *)",
    "Bash(python3 kalshi/scanner.py *)",
    "Bash(python3 kalshi/kalshi.py *)",
    "Bash(python3 kalshi/wx.py *)",
    "Bash(python3 -c *)",
    "WebSearch",
    "WebFetch(domain:gasprices.aaa.com)",
    "WebFetch(domain:api.weather.gov)",
    "WebFetch(domain:api.elections.kalshi.com)",
]


def load_allow(path):
    settings = json.loads(path.read_text())
    allow = settings["permissions"]["allow"]
    assert isinstance(allow, list)
    return allow


def test_judgment_settings_parse_with_an_allow_list():
    allow = load_allow(JUDGMENT)
    assert all(isinstance(rule, str) and rule.strip() == rule and rule
               for rule in allow)


def test_judgment_allowlist_has_no_duplicates():
    allow = load_allow(JUDGMENT)
    assert len(allow) == len(set(allow))


def test_judgment_rules_have_balanced_parens():
    # "WebFetch(domain:x)" with a lost paren still parses as JSON but never
    # matches anything — the exact silent-degrade shape this file guards.
    for rule in load_allow(JUDGMENT):
        assert rule.count("(") == rule.count(")") <= 1, rule
        assert (rule.count("(") == 0) or rule.endswith(")"), rule


def test_core_judgment_grants_present():
    allow = load_allow(JUDGMENT)
    missing = [rule for rule in CORE_JUDGMENT_GRANTS if rule not in allow]
    assert not missing, f"core grants clobbered: {missing}"


def test_operator_settings_parse():
    allow = load_allow(OPERATOR)
    assert "Bash(gh pr create *)" in allow  # the operator's whole job
    deny = json.loads(OPERATOR.read_text())["permissions"]["deny"]
    assert "Bash(gh pr merge *)" in deny  # the operator never merges
