"""Entities: the entity index and entity pages, behind the pack's switch.

The fixtures are hand-made `entities` blocks over the golden manifest's records,
shaped like each site's export (tests/roomkit/sites/fixtures/entities-*.json). Every
word on the pages is the export's: change it there and the page changes.
"""

from __future__ import annotations

import re
from pathlib import Path

from roomkit import room as R

HERE = Path(__file__).resolve().parent


def test_no_template_or_view_composes_entity_words():
    # The words live in the export (here the fixtures), not in the room's code.
    words = ("Appears alongside", "Documents linked", "Vendors", "Agencies", "shared documents",
             "Reading Room", "released record", "Entity ·")
    for f in ("entities.html", "entity.html", "partials/entity-head.html"):
        t = re.sub(r"\{#.*?#\}", "", (R.TEMPLATES / "room" / f).read_text(), flags=re.DOTALL)
        assert not [w for w in words if w in t], f
    for mod in ("view.py", "entities.py", "build.py"):
        src = (R.TEMPLATES.parent / mod).read_text()
        assert not [w for w in words if w != "Reading Room" and f'"{w}' in src], mod  # (doc pages' own default predates this)


def test_entities_css_is_scoped_and_paints_tokens_only():
    rules = [r for r in R.ENTITIES_CSS.split("}") if "{" in r]
    for r in rules:
        sel, body = r.split("{", 1)
        sel = re.sub(r"/\*.*?\*/", "", sel, flags=re.DOTALL).strip()
        assert all(s.strip().startswith("#room-content ") for s in sel.split(",")), sel
        assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgb|oklch", body), body
