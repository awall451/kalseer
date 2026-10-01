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
    "Bash(python3 kalshi/portwatch.py *)",
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

def test_every_curl_host_has_quoted_url_twins():
    """The judgment session must shell-quote URLs carrying query strings,
    and the Bash matcher compares raw command text — so
    `curl -s "https://host/…?f=json"` misses the unquoted prefix rule.
    That is item #17's live failure (re-proven 9/27; reproduced by the
    operator 9/28: the identical kalshi curl was allowed unquoted and
    approval-blocked quoted). Every plain curl host rule needs its
    quoted twins or query-string fetches silently degrade to denied."""
    allow = load_allow(JUDGMENT)
    plain = [rule for rule in allow
             if rule.startswith("Bash(curl -s https://")]
    assert plain, "the curl fallback rules are gone entirely"
    for rule in plain:
        for quote in ('"', "'"):
            twin = rule.replace("curl -s https://",
                                f"curl -s {quote}https://")
            assert twin in allow, f"missing quoted twin: {twin}"


def test_middle_arg_curl_rules_have_quoted_url_twins():
    """Item #17's failure shape, one variant over: the middle-arg rules
    (`curl -s * https://host/…`) exist so extra flags can precede the URL —
    but a flag-carrying curl of a query-string URL must ALSO quote it
    (`curl -s -A "Mozilla/5.0" "https://host/…?q=1"`), and the raw-text
    matcher misses the unquoted middle-arg rule exactly as it missed the
    plain one. Every middle-arg curl rule needs its quoted twins too."""
    allow = load_allow(JUDGMENT)
    middle = [rule for rule in allow
              if rule.startswith("Bash(curl -s * https://")]
    assert middle, "the middle-arg curl rules are gone entirely"
    for rule in middle:
        for quote in ('"', "'"):
            twin = rule.replace("curl -s * https://",
                                f"curl -s * {quote}https://")
            assert twin in allow, f"missing quoted twin: {twin}"


def test_approval_market_route_hosts_have_curl_rules():
    """Item #20: realclearpolling.com 403s WebFetch server-side, so
    KXTRUMPAPPROVE is unpriceable; the watchlist names polls.votehub.com
    as the alternate route and 'try realclearpolitics.com variant next
    time'. Curl carries a different client fingerprint than WebFetch and
    can set a browser User-Agent — but only if the hosts are allowlisted;
    an unlisted curl degrades to denied in the headless run."""
    allow = load_allow(JUDGMENT)
    for host in ("polls.votehub.com", "api.votehub.com",
                 "realclearpolling.com", "www.realclearpolling.com",
                 "realclearpolitics.com", "www.realclearpolitics.com"):
        assert f"Bash(curl -s https://{host}/*)" in allow, host
        assert f"Bash(curl -s * https://{host}/*)" in allow, host
    assert "WebFetch(domain:api.votehub.com)" in allow


def test_econ_release_hosts_have_curl_rules():
    """Item #4: clevelandfed.org and bls.gov 403 WebFetch server-side (bot
    protection, proven 8/8-8/9 with same-batch controls answering), keeping
    the whole CPI/payrolls complex unpriceable. Same different-fingerprint
    logic as item #20 (#35): curl can carry a browser User-Agent, but only
    if the hosts are allowlisted — an unlisted curl degrades to denied in
    the headless run. api.bls.gov is BLS's documented programmatic host
    (public JSON timeseries API, no registration for v1) and the likeliest
    of the three fingerprints to answer a plain client."""
    allow = load_allow(JUDGMENT)
    for host in ("clevelandfed.org", "www.clevelandfed.org",
                 "bls.gov", "www.bls.gov", "api.bls.gov"):
        assert f"Bash(curl -s https://{host}/*)" in allow, host
        assert f"Bash(curl -s * https://{host}/*)" in allow, host
    # the API host and the bare clevelandfed domain had no WebFetch rules
    # either — the judgment host's other working fingerprint
    assert "WebFetch(domain:api.bls.gov)" in allow
    assert "WebFetch(domain:clevelandfed.org)" in allow


def test_votehub_cli_grant_present():
    """Item #20 companion: kalshi/votehub.py (approval/generic-ballot reads
    off api.votehub.com, VoteHub's documented public API) is invoked by
    relative path like every other repo CLI and needs its own Bash grant.
    The grant rides in the same settings edit as item #4 because two open
    PRs may not touch this file's allowlist region (the outer script cannot
    resolve cross-PR conflicts); it is inert until the CLI lands."""
    allow = load_allow(JUDGMENT)
    assert "Bash(python3 kalshi/votehub.py *)" in allow


def test_bls_cli_grant_present():
    """Item #4 companion: kalshi/bls.py (CPI/payrolls/U-3 reads off
    api.bls.gov's documented timeseries API, the route live-verified 9/30)
    is invoked by relative path like every other repo CLI and needs its own
    Bash grant — without it the judgment run falls back to hand-rolled curl
    on every release day."""
    allow = load_allow(JUDGMENT)
    assert "Bash(python3 kalshi/bls.py *)" in allow
