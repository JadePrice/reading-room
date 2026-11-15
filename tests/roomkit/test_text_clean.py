"""One hyphen rule for machine-read page text, in three places.

roomkit/text_clean.py (the text view), its JS twin templates/room/text-clean.js, and the
read-aloud player's own `cleanText` (reading-room-reader/read-aloud/rr-read-aloud.js, left
untouched so its tested behavior cannot move) must give the same answer on every fixture. The JS
runs in Node; the player is loaded in a vm with a stub `window` and `document`.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from roomkit import text_clean as TC
from roomkit.build import READ_ALOUD_JS

TWIN = Path(TC.__file__).parent / "templates" / "room" / "text-clean.js"

FIXTURES = [
    "", "plain text", "hear-\ning", "hear¬\ning", "co-\n   operate", "co- \n operate",
    "well-known\nterm", "line one\nline two\n\nnew paragraph", "a - \n b", "dash---\nfoo",
    "ends with a hyphen-\n\nnext paragraph", "crlf-\r\nmerge", "cr only\rline", "tab\tseparated",
    "\u00a0padded\u00a0nbsp\u00a0", "nel\x85char", "unit\x1fseparator", "bom\ufeffinside", "em\u2003space",
    "para one\n  \npara two\n\n\n\npara three", "  lead\n  and trail  ", "Ünïcode-\nword ¬\nbreak",
    "<script>alert(1)</script>-\nx",
]

node = shutil.which("node")
pytestmark = pytest.mark.skipif(node is None, reason="node is not installed")

DRIVER = r"""
const fs = require('fs'), vm = require('vm');
const fixtures = JSON.parse(fs.readFileSync(0, 'utf8'));
const twin = require(process.argv[1]);
const ctx = {window: {}, document: {readyState: 'complete', querySelectorAll: () => [], addEventListener() {}}};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync(process.argv[2], 'utf8'), ctx);
const player = ctx.window.RRReadAloud;
process.stdout.write(JSON.stringify(fixtures.map(t => ({
  join: twin.joinHyphenated(t), clean: twin.cleanText(t), paras: twin.paragraphs(t), player: player._cleanText(t)}))));
"""


@pytest.fixture(scope="module")
def js():
    out = subprocess.run([node, "-e", DRIVER, str(TWIN), str(READ_ALOUD_JS)], input=json.dumps(FIXTURES),
                         capture_output=True, text=True, check=True, timeout=60)
    return json.loads(out.stdout)


@pytest.mark.parametrize("i", range(len(FIXTURES)))
def test_python_twin_and_player_agree(i, js):
    text, got = FIXTURES[i], js[i]
    assert TC.clean_text(text) == got["clean"] == got["player"], repr(text)
    assert TC.join_hyphenated(text) == got["join"], repr(text)
    assert TC.paragraphs(text) == got["paras"], repr(text)


def test_the_rule_itself():
    assert TC.clean_text("hear-\ning") == "hearing"
    assert TC.clean_text("hear¬\n  ing") == "hearing"
    assert TC.clean_text("well-known\nterm") == "well-known term"  # only a hyphen at the line end joins
    assert TC.paragraphs("a-\nb c\nd\n\ne") == [["ab c", "d"], ["e"]]
    assert TC.paragraphs("") == [] and TC.paragraphs(None) == [] and TC.paragraphs(" \n \n ") == []


def test_the_player_still_has_its_own_copy_unchanged():
    """The player is not touched by this chunk: its rule is the one the twins mirror."""
    js = READ_ALOUD_JS.read_text(encoding="utf-8")
    assert r".replace(/[-\u00AC]\s*\n\s*/g, '')" in js and "_cleanText: cleanText" in js
