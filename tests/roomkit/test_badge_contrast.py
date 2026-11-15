"""The hate-warning badge meets 4.5:1 (WCAG 1.4.3) in every theme.

It was #b33a3a with no background, 3.16:1 on a site's dark page. The badge now
carries its own black background and a trans-flag-palette text color, so its contrast
does not depend on the page's light or dark mode, or on which pack's tokens are
loaded. Measured here per built theme from the css each room actually ships, and
against the page background of each pack in both modes as a second reading.
"""

from __future__ import annotations

import re

import pytest

from roomkit import build as B
from roomkit import color as C
from tests.roomkit import test_golden as G

FLAG = {"#5bcefa", "#f5a9b8", "#ffffff", "#000000"}
RULE = re.compile(r"\.room__badge--hate-warning\{([^}]*)\}")


def _hex(value: str):
    parsed = C.parse(value.strip())
    assert parsed is not None, value
    return parsed[0]


def _decls(rule: str) -> dict[str, str]:
    return dict(d.split(":", 1) for d in rule.split(";") if ":" in d)


@pytest.mark.parametrize("case", sorted(G.CASES))
def test_hate_warning_badge_meets_4_5_to_1_in_every_theme(case):
    m, kw = G.CASES[case]()
    files = B.render(m, engine=G.ENGINE, indexer=G.S.stand_in, **kw)
    sheets = [v.decode() for k, v in files.items() if re.fullmatch(r"assets/room\.[0-9a-f]+\.css", k)]
    assert sheets, case
    rules = [r for s in sheets for r in RULE.findall(s)]
    assert len(rules) == 1, (case, rules)  # no pack or mode redefines it
    d = _decls(rules[0])
    fg, bg = d["color"].strip().lower(), d.get("background", "").strip().lower()
    assert bg, "the badge must carry its own background so no theme can change its contrast"
    assert fg in FLAG and bg in FLAG, (fg, bg)  # trans flag palette only
    ratio = C.contrast(_hex(fg), _hex(bg))
    print(f"{case}: {fg} on {bg} = {ratio:.2f}:1")
    assert ratio >= 4.5, (case, ratio)
