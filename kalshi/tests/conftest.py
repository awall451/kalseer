import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).parents[1]))
import shadow


@pytest.fixture(autouse=True)
def _no_shadow_network(monkeypatch):
    # paper.cmd_open/close record a shadow order, which reads the live order
    # book. Tests that exercise it opt back in (test_shadow.py's fixture).
    monkeypatch.setattr(shadow, "ENABLED", False)
