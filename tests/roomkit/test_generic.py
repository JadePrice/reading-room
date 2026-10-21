"""The room is generic: sites differ only through their packs (plan Task 6).

hrtarchive is the pack for a site the template was never shaped around. It
builds a synthetic fixture with no template change, and across all four packs
the pages differ only where a pack says they should:

- HTML depends on a pack's layout, labels, features and chrome, and on nothing
  else in it (the header's site name and links are chrome, not identity). Swap those knobs between two packs and every page is
  byte-identical, whatever the identity, tokens, dark tokens, extra_css or
  notes. So no template branches on which site it is rendering.
- tokens and extra_css reach only the stylesheet, after the shared room.css
  and the room's chrome.css.
"""

from __future__ import annotations

import copy
import itertools
import json
import re
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit.manifest import load, parse

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "hrtarchive-mini.json"
PACKS = ("default", "deflockdane", "glassgovernment", "hrtarchive")
KNOBS = ("layout", "labels", "features", "chrome")
CSS_NAME = re.compile(rb"assets/room\.[0-9a-f]{12}\.css")


def _manifest():
    data = json.loads(FIXTURE.read_text())
    data["site"].pop("template")  # any pack may render it
    return parse(data)


def _pages(pack: dict) -> dict[str, bytes]:
    files = B.render(_manifest(), pack=pack, indexer=S.stand_in)
    return {p: CSS_NAME.sub(b"assets/room.CSS.css", b) for p, b in files.items()
            if not CSS_NAME.search(p.encode()) and p != B.LOCK}


def test_hrtarchive_builds_its_fixture_with_no_template_change():
    m = load(FIXTURE)
    assert not m.refusals and len(m.documents) == 5
    files = B.render(m, pack=K.for_site("hrtarchive"))
    index = files["index.html"].decode()
    assert "room__groups--cards" in index and "<title>Preserved public pages</title>" in index
    assert "data-room-toggle" not in index  # one dark scheme, no toggle
    css = files[B.published(files, "assets/room.css")].decode()
    assert "--room-surface:rgba(25, 15, 40, 0.9);" in css and "--room-focus:#F5A9B8;" in css


@pytest.mark.parametrize("a, b", list(itertools.permutations(PACKS, 2)))
def test_pages_differ_only_where_the_pack_says(a, b):
    pa, pb = K.for_site(a), copy.deepcopy(K.for_site(b))
    for knob in KNOBS:
        pb.pop(knob, None)
        if knob in pa:
            pb[knob] = copy.deepcopy(pa[knob])
    assert _pages(pb) == _pages(pa)


@pytest.mark.parametrize("site", PACKS)
def test_tokens_reach_only_the_stylesheet_after_the_shared_rules(site):
    # The shared rules are room.css and the room's own chrome.css.
    files = B.render(_manifest(), pack=K.for_site(site), indexer=S.stand_in)
    css = files[B.published(files, "assets/room.css")].decode()
    shared = R.ROOM_CSS + R.chrome_css(K.for_site(site)) + (R.SEARCH_CSS if S.enabled(K.for_site(site)) else "")
    assert css.startswith(shared)
    tail = css[len(shared):]
    assert tail.startswith("#room-content,body.room-plain{--room-") and "room__card{" not in tail.split("\n")[0]


def test_every_pack_with_a_site_tokens_file_derives_from_it():
    maps = sorted(p.parent.name for p in K.PACKS.glob("*/tokens.map.json"))
    assert maps == ["deflockdane", "glassgovernment", "hrtarchive"]
