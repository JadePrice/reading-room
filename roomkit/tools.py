"""The room's optional tools: which pack switches are JS tools, and the RoomTools seam they share.

A tool is one pack feature switch, its own asset files and one parity-matrix row. The seam
(templates/room/room-tools.js and room-tools.css, Chunk A0) is the one thing they may share: a
"Reading tools" menu after the reader, one status line, one preferences store.

Budget rules (tests/roomkit/sites/test_tools_budget.py enforces them):
- every switch off: the output is byte-identical, so no goldens move;
- a tool on adds at most TOOL_BUDGET bytes of gzipped JS plus CSS to a record page's first load
  and no request before the visitor presses something;
- the seam ships only when at least one tool that registers with it is on.

`JS_TOOLS` lists every switch that ships JS to a record page (the budget test measures each).
`SEAM_TOOLS` is the subset that registers with the seam. read-aloud is a JS tool but is not in
`SEAM_TOOLS` yet: its player draws its own panel, and registering it is plan A2 Step 2. Until a
tool registers, the seam ships nowhere, so no room carries bytes for an empty menu.
"""

from __future__ import annotations

TOOL_BUDGET = 4096  # gzipped bytes of added JS plus CSS per tool, on a record page's first load
SEAM_BUDGET = 1536  # the seam's own JS, gzipped (it is shared, so it is held tighter)

JS_TOOLS = ("read-aloud",)
SEAM_TOOLS: frozenset[str] = frozenset()


def seam_on(pack: dict) -> bool:
    """Whether this pack turns on at least one tool that registers with the seam."""
    features = pack.get("features", {})
    return any(features.get(t) for t in SEAM_TOOLS)
