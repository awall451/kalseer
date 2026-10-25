"""futures.py: name the contract month behind each continuous-series bar.

Brief 10/24: "Yahoo's 10/23 HO/RB bars (4.9842 / 3.2116) disagree with last
trade (4.7870 / 3.1284). Possibly the Nov-contract roll. I treated them as
unverified." The journal shows the same shape on earlier days: ULSD 10/21
4.7633 between 4.925 and 4.9321, and the 10/16 bar first 4.7232 then 4.8991.
HO=F/RB=F are Yahoo's continuous front month, so near the roll a bar can come
from either Nov (X26) or Dec (Z26), and a gap between those two contracts
looks like a 16-20c move. The explicit months (HOX26.NYM, HOZ26.NYM) are
contract-consistent, so `closes` tags each bar with the month it matches and
`archive` journals the front and next months beside the continuous series.
"""

import datetime
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import futures
from test_futures import body, ts


def d(s):
    return datetime.date.fromisoformat(s)


def test_front_month_is_next_month_until_the_last_business_day():
    # NYMEX RB/HO terminate on the last business day of the month before
    # delivery: Nov 2026 trades through Fri 10/30
    assert futures.front_month(d("2026-10-23")) == (2026, 11)
    assert futures.front_month(d("2026-10-30")) == (2026, 11)
    assert futures.front_month(d("2026-10-31")) == (2026, 12)
    assert futures.front_month(d("2026-11-02")) == (2026, 12)


def test_last_business_day_skips_a_weekend_month_end():
    # Jan 2027 ends on a Sunday -> the Feb contract expires Fri 1/29
    assert futures.front_month(d("2027-01-29")) == (2027, 2)
    assert futures.front_month(d("2027-01-30")) == (2027, 3)


def test_december_rolls_into_the_next_year():
    assert futures.front_month(d("2026-12-15")) == (2027, 1)
    assert futures.contract("ulsd", 2027, 1) == "HOF27.NYM"
    assert futures.contract("rbob", 2026, 11) == "RBX26.NYM"
    assert futures.contract("ho", 2026, 12) == "HOZ26.NYM"


# Oct 2026 NYMEX ULSD: the continuous series serves Nov on most days and Dec
# on 10/21; the last trade (Fri 10/23) is the Dec contract's.
NOV = [4.9201, 4.9250, 4.9010, 4.9321, 4.9842]
DEC = [4.7650, 4.7710, 4.7633, 4.7790, 4.7870]
DAYS = [19, 20, 21, 22, 23]


@pytest.fixture
def roll(monkeypatch):
    state = {"calls": [], "fail": set(), "bodies": {
        "HO=F": body("HO=F", [ts(x) for x in DAYS],
                     [4.9201, 4.9250, 4.7633, 4.9321, 4.9842],
                     last=(4.7870, ts(23, 16))),
        "HOX26.NYM": body("HOX26.NYM", [ts(x) for x in DAYS], NOV,
                          last=(4.9842, ts(23, 16))),
        "HOZ26.NYM": body("HOZ26.NYM", [ts(x) for x in DAYS], DEC,
                          last=(4.7870, ts(23, 16))),
    }}

    def fake_fetch(symbol):
        state["calls"].append(symbol)
        if symbol in state["fail"] or symbol not in state["bodies"]:
            raise OSError(f"no {symbol}")
        return state["bodies"][symbol]
    monkeypatch.setattr(futures, "_fetch", fake_fetch)
    return state


def lines(capsys):
    return capsys.readouterr().out.splitlines()


def test_closes_tags_each_bar_with_the_contract_month_it_matches(roll, capsys):
    futures.main(["closes", "ulsd"])
    out = lines(capsys)
    assert roll["calls"] == ["HO=F", "HOX26.NYM", "HOZ26.NYM"]
    rows = {l[:10]: l for l in out if not l.startswith("#")}
    assert "month X26" in rows["2026-10-23"]
    assert "month Z26" in rows["2026-10-21"]
    assert "month X26" in rows["2026-10-19"]


def test_closes_warns_when_the_bars_switch_contract_month(roll, capsys):
    futures.main(["closes", "ulsd"])
    warn = [l for l in lines(capsys) if "switch contract month" in l]
    assert len(warn) == 1
    assert "2026-10-21" in warn[0] and "Z26" in warn[0]
    assert "not a move" in warn[0]


def test_closes_names_the_contract_the_last_trade_belongs_to(roll, capsys):
    futures.main(["closes", "ulsd"])
    out = "\n".join(lines(capsys))
    assert "last trade 4.7870 is the Z26 contract's (HOZ26.NYM)" in out
    assert "HOX26.NYM (expires 2026-10-30): latest 2026-10-23 = 4.9842" in out
    assert "HOZ26.NYM (expires 2026-11-30): latest 2026-10-23 = 4.7870" in out


def test_main_footer_stays_last_before_warnings(roll, capsys):
    futures.main(["closes", "ulsd"])
    out = lines(capsys)
    footer = [l for l in out if l.startswith("# ulsd = HO=F")]
    assert len(footer) == 1
    after = out[out.index(footer[0]) + 1:]
    assert all(l.startswith("# WARNING") for l in after)


def test_a_bar_matching_neither_month_is_tagged_unknown(roll, capsys):
    roll["bodies"]["HO=F"] = body("HO=F", [ts(22), ts(23)], [4.9321, 4.8000])
    futures.main(["closes", "ulsd"])
    rows = [l for l in lines(capsys) if l.startswith("2026-10-23")]
    assert "month ?" in rows[0]


def test_contract_fetch_failure_leaves_closes_untagged(roll, capsys):
    roll["fail"].update({"HOX26.NYM", "HOZ26.NYM"})
    futures.main(["closes", "ulsd"])
    out = lines(capsys)
    assert out[0].startswith("2026-10-23  4.9842")
    assert not any("month" in l for l in out if not l.startswith("#"))
    assert any("contract months unavailable" in l for l in out)


def test_crude_and_raw_symbols_are_not_tagged(roll, capsys):
    roll["bodies"]["CL=F"] = body("CL=F", [ts(23)], [61.2])
    futures.main(["closes", "wti"])
    assert roll["calls"] == ["CL=F"]


def test_window_across_an_expiry_also_fetches_the_expired_month(roll, capsys):
    # newest bar Mon 11/2 (Dec front); 10/30 was still Nov's last day
    roll["bodies"]["HO=F"] = body("HO=F", [ts(30), ts(33)], [4.95, 4.80])
    futures.main(["closes", "ulsd"])
    assert roll["calls"] == ["HO=F", "HOX26.NYM", "HOZ26.NYM", "HOF27.NYM"]


@pytest.fixture
def archive(roll, tmp_path, monkeypatch):
    roll["bodies"]["RB=F"] = body("RB=F", [ts(22), ts(23)], [3.1765, 3.2116])
    roll["bodies"]["RBX26.NYM"] = body("RBX26.NYM", [ts(22), ts(23)],
                                       [3.1765, 3.2116])
    roll["bodies"]["RBZ26.NYM"] = body("RBZ26.NYM", [ts(22), ts(23)],
                                       [3.0990, 3.1284])
    monkeypatch.setattr(futures, "_now", lambda: ts(24, 8))
    monkeypatch.setattr(futures, "DATA", tmp_path)
    return roll


def journal(name):
    path = futures.DATA / "futures" / f"{name}.jsonl"
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


def test_archive_journals_the_front_and_next_contract_months(archive, capsys):
    futures.main(["archive"])
    assert [(r["date"], r["close"]) for r in journal("ulsd-Z26")][-2:] == [
        ("2026-10-22", 4.779), ("2026-10-23", 4.787)]
    assert journal("ulsd-X26")[-1]["close"] == 4.9842
    assert journal("rbob-Z26")[-1]["close"] == 3.1284
    out = capsys.readouterr().out
    assert "futures archive: ulsd-X26 (HOX26.NYM): 5 new days, 0 revised" in out
    assert "futures archive: ulsd: 5 new days, 0 revised" in out


def test_archive_contract_failure_does_not_fail_the_step(archive, capsys):
    archive["fail"].update({"HOX26.NYM", "HOZ26.NYM", "RBX26.NYM",
                            "RBZ26.NYM"})
    futures.main(["archive"])
    assert len(journal("ulsd")) == 5
    assert "ulsd-X26 (HOX26.NYM): failed" in capsys.readouterr().out


def test_first_reads_a_contract_journal(archive, capsys):
    futures.main(["archive"])
    capsys.readouterr()
    futures.main(["first", "ulsd-Z26"])
    out = lines(capsys)
    assert out[0].startswith("2026-10-23  first 4.7870  latest 4.7870")
    assert out[-1].startswith("# 0 of 5 days revised")
    assert "ulsd-Z26 = HOZ26.NYM" in out[-1]


def test_first_rejects_an_unknown_journal_name(archive):
    with pytest.raises(SystemExit):
        futures.main(["first", "wti-Z26"])
