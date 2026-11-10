"""The judgment prompt points at the board-centre tool lines.

#119-#121 made the board's centre and its miss tool lines (fuelfreeze
`centre:` / `centre miss`, econfreeze `# board median:` / `board median
miss`), but the prompt never named them, and the 11/9 brief kept centring
by eye: gas "~4.012, missed -0.27c" where `fuelfreeze.py score` reads
BOARD 4.0103 -0.10, and diesel "~6.175, -0.27c" where it reads 6.1728 -0.05.
"""

import pathlib

PROMPT = (pathlib.Path(__file__).parents[2] / "bin" / "daily-prompt.md")


def test_prompt_names_the_fuel_centre_lines():
    prompt = PROMPT.read_text()
    assert "centre miss" in prompt
    assert "# centre miss" in prompt
    assert "`EVENT centre:`" in prompt


def test_prompt_names_the_econ_median_lines():
    prompt = PROMPT.read_text()
    assert "# board median:" in prompt
    assert "board median miss" in prompt
