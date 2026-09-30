"""votehub.py CLI: poll reads off api.votehub.com for the approval family.

Both RCP domains 403 server-side (realclearpolling 9/28, realclearpolitics
9/29, same-batch controls answered), leaving KXTRUMPAPPROVE unpriceable —
item #20. VoteHub's documented public API (votehub.com/polls/api, CC BY 4.0)
is the alternate route the watchlist names, and KXGENERICBALLOTVOTEHUB-*
settles on VoteHub's aggregate outright. These tests pin the documented
response schema (id, pollster, subject, start/end dates, sample_size,
population, answers[{choice, pct}]) — the operator sandbox cannot reach the
host, so the schema is fixture-pinned from the docs and the first live read
belongs to the judgment run. The tool must treat schema drift the way
portwatch treats it: loudly, never silently.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import votehub

POLLS = [
    # oldest deliberately first: order must come from the tool
    {
        "id": "a1", "poll_type": "approval", "pollster": "Quinnipiac",
        "subject": "Trump", "sample_size": 1330, "population": "rv",
        "start_date": "2026-09-20", "end_date": "2026-09-22",
        "created_at": "2026-09-23T14:00:00Z",
        "answers": [{"choice": "Approve", "pct": 39.0},
                    {"choice": "Disapprove", "pct": 57.0}],
        "url": "https://poll.example/q",
    },
    {
        "id": "b2", "poll_type": "approval", "pollster": "Marquette",
        "subject": "Trump", "sample_size": 1005, "population": "a",
        "start_date": "2026-09-24", "end_date": "2026-09-27",
        "created_at": "2026-09-28T10:00:00Z",
        "answers": [{"choice": "Approve", "pct": 43.0},
                    {"choice": "Disapprove", "pct": 56.0}],
        "url": "https://poll.example/m",
    },
]


@pytest.fixture
def api(monkeypatch):
    """Capture query params; serve canned VoteHub responses."""
    state = {"calls": [], "response": list(POLLS)}

    def fake_fetch(params):
        state["calls"].append(dict(params))
        return state["response"]
    monkeypatch.setattr(votehub, "_fetch", fake_fetch)
    return state


def test_polls_prints_one_line_per_poll_newest_first(api, capsys):
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    out = capsys.readouterr().out.splitlines()
    data = [line for line in out if not line.startswith("#")]
    assert len(data) == 2
    assert data[0].startswith("2026-09-27  Marquette")
    assert data[1].startswith("2026-09-22  Quinnipiac")


def test_poll_lines_carry_answers_sample_and_population(api, capsys):
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    (line, _) = [l for l in capsys.readouterr().out.splitlines()
                 if not l.startswith("#")]
    assert "Approve 43" in line and "Disapprove 56" in line
    assert "n=1005" in line and "a" in line


def test_summary_names_newest_end_date_and_unweighted_means(api, capsys):
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    summary = [l for l in capsys.readouterr().out.splitlines()
               if l.startswith("#")]
    assert any("newest end_date: 2026-09-27" in l for l in summary)
    # (39+43)/2 and (57+56)/2 — unweighted, labeled as such, judgment
    # decides what they are worth (settlement reads VoteHub's own
    # aggregate for KXGENERICBALLOTVOTEHUB, RCP for KXTRUMPAPPROVE)
    assert any("Approve 41.0" in l and "Disapprove 56.5" in l
               for l in summary)


def test_query_passes_poll_type_and_subject(api, capsys):
    votehub.main(["polls", "approval", "--subject", "Trump",
                  "--since", "2026-09-01"])
    (params,) = api["calls"]
    assert params["poll_type"] == "approval"
    assert params["subject"] == "Trump"


def test_subject_omitted_from_query_when_not_given(api, capsys):
    votehub.main(["polls", "generic-ballot", "--since", "2026-09-01"])
    (params,) = api["calls"]
    assert params["poll_type"] == "generic-ballot"
    assert "subject" not in params


def test_since_filters_on_end_date_client_side(api, capsys):
    votehub.main(["polls", "approval", "--since", "2026-09-25"])
    out = capsys.readouterr().out
    assert "Marquette" in out and "Quinnipiac" not in out


def test_empty_result_is_an_answer_not_an_error(api, capsys):
    api["response"] = []
    votehub.main(["polls", "approval", "--since", "2026-09-01"])  # exit 0
    assert "# no polls" in capsys.readouterr().out


def test_wrapped_polls_body_also_parses(api, capsys):
    api["response"] = {"polls": list(POLLS)}
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    data = [l for l in capsys.readouterr().out.splitlines()
            if not l.startswith("#")]
    assert len(data) == 2


def test_unexpected_body_shape_fails_loudly(api, capsys):
    api["response"] = {"error": "nope"}
    with pytest.raises(SystemExit) as e:
        votehub.main(["polls", "approval", "--since", "2026-09-01"])
    assert e.value.code != 0
    assert "unexpected response shape" in capsys.readouterr().err


def test_missing_sample_and_population_tolerated(api, capsys):
    poll = dict(POLLS[1])
    poll.pop("sample_size")
    poll.pop("population")
    api["response"] = [poll]
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    (line,) = [l for l in capsys.readouterr().out.splitlines()
               if not l.startswith("#")]
    assert "Approve 43" in line


def test_end_date_with_time_part_still_yields_the_day(api, capsys):
    poll = dict(POLLS[1])
    poll["end_date"] = "2026-09-27T00:00:00Z"
    api["response"] = [poll]
    votehub.main(["polls", "approval", "--since", "2026-09-01"])
    (line,) = [l for l in capsys.readouterr().out.splitlines()
               if not l.startswith("#")]
    assert line.startswith("2026-09-27  ")


def test_fetch_targets_the_documented_polls_endpoint(monkeypatch):
    seen = {}

    class FakeResponse:
        def read(self):
            return json.dumps([]).encode()

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=30):
        seen["url"] = req.full_url
        return FakeResponse()
    monkeypatch.setattr(votehub.urllib.request, "urlopen", fake_urlopen)
    votehub.main(["polls", "approval"])
    assert seen["url"].startswith("https://api.votehub.com/polls?")
    assert "poll_type=approval" in seen["url"]


def test_usage_on_bad_args():
    with pytest.raises(SystemExit):
        votehub.main([])
    with pytest.raises(SystemExit):
        votehub.main(["nonsense"])
    with pytest.raises(SystemExit):
        votehub.main(["polls"])  # poll type is required
