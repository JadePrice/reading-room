"""The room is generic: sites differ only through their packs.

Across every shipped pack the pages differ only where a pack says they should:

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
from roomkit.manifest import parse
from tests.roomkit.shipped import PACKS

FIXTURE = Path(__file__).resolve().parent / "golden" / "manifest.json"
KNOBS = ("layout", "labels", "features", "chrome", "nginx", "host", "search_ranking",  # nginx: the server config it writes (.nginx.conf); host: the server config for its host (_headers.room); search_ranking: the finder's data-room-ranking
         "fonts", "theme", K.ROOT_KEY,  # a mapped theme (theme_map.py): its fonts, its element styles, and the pack directory its files are read from
         "a11y_toolbar")  # the site's accessibility toolbar: its markup, script and the plugin's files
# The theme's identity fields: the header logo, the site icon, <html lang> and theme-color.
THEME_IDENTITY = ("logo", "favicon", "lang", "theme_color")
CSS_NAME = re.compile(rb"assets/room\.[0-9a-f]{12}\.css")


def _manifest():
    data = json.loads(FIXTURE.read_text())
    data["site"].pop("template", None)  # any pack may render it
    return parse(data)


def _pages(pack: dict) -> dict[str, bytes]:
    files = B.render(_manifest(), pack=pack, indexer=S.stand_in)
    out = {}
    for p, b in files.items():
        if CSS_NAME.search(p.encode()) or p == B.LOCK:
            continue
        if p == B.HEADERS_ROOM:
            # The fragment's first line names the pack that wrote it (identity.site),
            # so the splice can take the name from there. That is who built the file,
            # not what it renders: normalize it before comparing two packs.
            b = re.sub(rb"\A# roomkit \S+ ", b"# roomkit SITE ", b, count=1)
        out[p] = CSS_NAME.sub(b"assets/room.CSS.css", b)
    return out


@pytest.mark.parametrize("a, b", list(itertools.permutations(PACKS, 2)))
def test_pages_differ_only_where_the_pack_says(a, b):
    pa, pb = B.pack_for_site(a), copy.deepcopy(B.pack_for_site(b))
    for knob in KNOBS:
        pb.pop(knob, None)
        if knob in pa:
            pb[knob] = copy.deepcopy(pa[knob])
    for key in THEME_IDENTITY:
        pb["identity"].pop(key, None)
        if key in pa["identity"]:
            pb["identity"][key] = copy.deepcopy(pa["identity"][key])
    assert _pages(pb) == _pages(pa)


@pytest.mark.parametrize("site", PACKS)
def test_tokens_reach_only_the_stylesheet_after_the_shared_rules(site):
    # The shared rules are room.css and the room's own chrome.css.
    files = B.render(_manifest(), pack=B.pack_for_site(site), indexer=S.stand_in)
    css = files[B.published(files, "assets/room.css")].decode()
    css = css[len(re.match(r"(?:@font-face\{[^\n]*\}\n)*", css).group(0)):]  # a mapped theme's fonts come first
    shared = R.ROOM_CSS + R.chrome_css(B.pack_for_site(site)) + (R.SEARCH_CSS if S.enabled(B.pack_for_site(site)) else "")
    assert css.startswith(shared)
    tail = css[len(shared):]
    assert tail.startswith("#room-content,body.room-plain{--room-") and "room__card{" not in tail.split("\n")[0]
