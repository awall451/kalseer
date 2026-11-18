"""futures.py margin: retail AAA print minus the wholesale front month.

Since 10/27 the judgment step has worked the retail-wholesale margin out by
hand nearly every run (watchlist aaa-gas-tracking-nov, 11/17: "gas margin
3.7818-2.5379 = 1.24, diesel 5.9848-4.0818 = 1.90 (wider than 11/14's 1.78)
-> more retail fall in the pipe"), and leans on it for the direction of the
next prints. Each day's figure was a subtraction against whichever settle it
remembered, and the trend ("wider than 11/14's") a recollection. `margin`
reads both journals offline: each print against the newest settled close of
the then-front contract month dated before the print, so a roll shows as a
contract change instead of a 15c jump.
"""

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures

PROMPT = pathlib.Path(__file__).parents[2] / "bin" / "daily-prompt.md"


def write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows))


def aaa(day, regular, diesel):
    return {"date": day, "prices": {"current": {
        "regular": f"${regular}", "diesel": f"${diesel}"}}}


@pytest.fixture
def data(tmp_path, monkeypatch):
    monkeypatch.setattr(futures, "DATA", tmp_path)
    write(tmp_path / "aaa" / "prints.jsonl", [
        aaa("2026-11-14", "3.8242", "6.0198"),
        aaa("2026-11-16", "3.8118", "5.9989"),
        aaa("2026-11-17", "3.7818", "5.9848"),
    ])
    write(tmp_path / "futures" / "rbob-Z26.jsonl", [
        {"date": "2026-11-12", "close": 2.6708},
        {"date": "2026-11-13", "close": 2.6214},
        {"date": "2026-11-16", "close": 2.5379},
    ])
    write(tmp_path / "futures" / "ulsd-Z26.jsonl", [
        {"date": "2026-11-12", "close": 4.2865},
        {"date": "2026-11-13", "close": 4.2585},
        {"date": "2026-11-16", "close": 4.0818},
    ])
    return tmp_path


def run(capsys, *args):
    futures.main(["margin", *args])
    return capsys.readouterr().out.splitlines()


def test_each_print_is_against_the_settle_before_it(data, capsys):
    out = run(capsys)
    assert out[0].startswith("2026-11-17  ")
    assert "gas 3.7818 - RBZ26 2.5379 (11-16) = 1.2439" in out[0]
    assert "diesel 5.9848 - HOZ26 4.0818 (11-16) = 1.9030" in out[0]
    # a Monday print is against Friday's settle, not a weekend bar
    assert "gas 3.8118 - RBZ26 2.6214 (11-13) = 1.1904" in out[1]
    assert "diesel 6.0198 - HOZ26 4.2585 (11-13) = 1.7613" in out[2]


def test_rows_carry_the_margin_change(data, capsys):
    out = run(capsys)
    assert "1.2439 (+0.0535)" in out[0]
    assert "1.9030 (+0.1626)" in out[0]
    assert "1.1904 (-0.0124)" in out[1]
    assert "(+" not in out[2] and "(-" not in out[2]  # oldest row: no prior


def test_footer_summarises_each_fuel(data, capsys):
    out = run(capsys)
    gas = [l for l in out if l.startswith("# gas margin")]
    diesel = [l for l in out if l.startswith("# diesel margin")]
    assert gas == ["# gas margin (regular - RB front month): latest 1.2439 "
                   "on 2026-11-17; n=3 mean 1.2124 min 1.1904 (2026-11-16) "
                   "max 1.2439 (2026-11-17)"]
    assert diesel[0].startswith("# diesel margin (diesel - HO front month): "
                                "latest 1.9030 on 2026-11-17; n=3")


def test_days_limits_the_rows(data, capsys):
    out = run(capsys, "--days", "2")
    rows = [l for l in out if not l.startswith("#")]
    assert [r[:10] for r in rows] == ["2026-11-17", "2026-11-16"]
    assert "n=2" in [l for l in out if l.startswith("# gas")][0]


def test_a_roll_is_a_contract_change_not_a_move(data, capsys):
    # 12/1: Z26 expired 11/30, so the front month is F27
    write(data / "aaa" / "prints.jsonl", [
        aaa("2026-11-30", "3.6000", "5.8000"),
        aaa("2026-12-01", "3.5900", "5.7900"),
    ])
    write(data / "futures" / "rbob-Z26.jsonl",
          [{"date": "2026-11-27", "close": 2.5000}])
    write(data / "futures" / "rbob-F27.jsonl",
          [{"date": "2026-11-30", "close": 2.4000}])
    write(data / "futures" / "ulsd-Z26.jsonl",
          [{"date": "2026-11-27", "close": 4.0000}])
    write(data / "futures" / "ulsd-F27.jsonl",
          [{"date": "2026-11-30", "close": 3.9000}])
    out = run(capsys)
    assert "gas 3.5900 - RBF27 2.4000 (11-30) = 1.1900 (roll)" in out[0]
    assert "gas 3.6000 - RBZ26 2.5000 (11-27) = 1.1000" in out[1]


def test_a_revised_close_uses_the_latest(data, capsys):
    path = data / "futures" / "rbob-Z26.jsonl"
    with path.open("a") as f:
        f.write(json.dumps({"date": "2026-11-16", "close": 2.5400,
                            "revised_from": 2.5379}) + "\n")
    assert "RBZ26 2.5400 (11-16) = 1.2418" in run(capsys)[0]


def test_no_month_journal_falls_back_to_the_continuous_one(data, capsys):
    (data / "futures" / "ulsd-Z26.jsonl").unlink()
    write(data / "futures" / "ulsd.jsonl",
          [{"date": "2026-11-16", "close": 4.0800}])
    out = run(capsys)
    assert "diesel 5.9848 - HO=F 4.0800 (11-16) = 1.9048" in out[0]
    assert "diesel 5.9989 - HO=F -" in out[1]  # nothing settled before it


def test_missing_print_journal_says_so(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(futures, "DATA", tmp_path)
    assert run(capsys) == [f"# no AAA prints at "
                           f"{tmp_path / 'aaa' / 'prints.jsonl'}"]


def test_prompt_names_the_margin_line():
    prompt = PROMPT.read_text()
    assert "futures.py margin" in prompt
    assert "# gas margin" in prompt
