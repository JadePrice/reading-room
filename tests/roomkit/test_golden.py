"""The room's output, pinned byte for byte, one golden file per theme.

Pinned on 152e0e7 (roomkit 0.3.0's string template) before the template moved
to Jinja (plan Task 3a), which must change nothing visible. A golden file is
the whole rendered tree, every file under an `=== path ===` header, lock
included. The engine is a stand-in (`golden/engine/`), so an engine release
does not move these files; only the template, the site packs and the build do.

A difference here is a change to every page a site serves. Never regenerate a
golden file to make this pass; when a change is meant to alter the output, say
which and why in the commit that replaces it.

Replaced on purpose since the pin:
    deflockdane.txt  plan Task 4 (2026-10-13): dd's pack now takes its tokens from
                     design-tokens/deflockdane.tokens.css (user's choice). Only
                     room.css's token line changed, and with it its fingerprinted
                     name in each page and the lock.
    plain.txt        plan Task 5 Step 1 (2026-10-14): a page built without a shell
                     draws its own header, nav and footer from the pack's chrome
                     (packs/default). Each page gained the chrome-header/footer
                     partials; room.css gained chrome.css and puts the tokens on
                     body.room-plain too; with them the fingerprinted names and
                     the lock moved. The two shell-built goldens did not move
                     (tests/roomkit/test_chrome.py checks the shell path).
                     Again for the Task 5 review (2026-10-14): only chrome.css
                     changed (the wide-screen menu rule's specificity, summary
                     carets, button hover from tokens), with the css name and lock.
                     Task 5 polish (2026-10-14): the index stat said "14 agencys"
                     (a built plural); packs now name their count nouns, so it
                     reads "14 groups" (packs/default). chrome.css lost its
                     wide block to chrome-wide.css, emitted at the pack's
                     chrome.inline_from (20em for default), with tighter link
                     gaps and dropdowns anchored to their summary's end.
                     Jump-nav round (2026-10-14): a page the room owns takes the
                     group noun from the pack only (finder label "Group", jump
                     "Jump to group"), names the jump nav by its visible label,
                     and room.js takes the live count's nouns from data-room-one/
                     -other. Shell builds keep their pinned text and room-shell.js.
    deflockdane.txt, glassgovernment.txt
                     plan Task 5 Steps 3-4 (2026-10-14, design review approved
                     on 7ee4aed): the captured WordPress shell is retired (D7
                     superseded: a standalone room cannot depend on WordPress
                     output). The two shell-built goldens and their *-shell.json
                     inputs were deleted and re-pinned as pack-chrome builds:
                     the room's own header, nav and footer, no assets/theme/,
                     the pack's nouns and jump label, dd's extra_css hover gone,
                     and the lock's "shell" hash replaced by the pack's hash.
    hrtarchive.txt   added then, so all four packs are pinned.
    plain.txt        moved with them: the lock names the pack's hash, and the
                     skip link's position moved from room.css to chrome.css.
    all four         header aligns with the page column (2026-10-14): the bar no longer
                     widens to max(1232px, inline_from), so the one rule that did is
                     gone, and with it each css name and the lock.
    glassgovernment.txt
                     2026-10-15, the user's decision (approved): GG's light page, surface and
                     sunk surface are the site's yellowed paper (--paper-0,
                     --paper-1, --catalog-hover-bg), not the reading-room
                     plugin's near-white. Only room.css's token line moved,
                     with its fingerprinted name, the page hashes and the
                     pack hash.
    glassgovernment.txt  2026-10-20: GG's pack turns on features.facet-pages, after a fresh
                     export's facet pages matched the live index (parity.facet_pages
                     133/133). The golden manifest has no browse block, so no facet page;
                     only the lock's pack hash moved.
                     Same day, after doc-text-only (455/455 records, page parity 65/65) removed
                     the last blocker: GG's pack turns on features.sitemaps and
                     features.entities (parity.sitemaps: live document and entity providers
                     equal the room's, 531 URLs). The golden manifest has no entities block,
                     so the tree gained sitemap.xml, and the lock its entry and the new pack
                     hash. No page moved.
    all four       2026-10-20 (GG index selects): room.js gained the multi-valued facet,
                     the year range and the sort (and their URL state), used only when
                     the manifest's site.index carries them, which no golden manifest does.
                     Only room.js's content and fingerprinted name moved: its <script>
                     reference on each page and the lock's hashes. The index markup is
                     unchanged byte for byte.
    deflockdane.txt  2026-10-20, the user's go ("sitemaps and facet pages", for dd
                     staging): dd's pack turns on features.facet-pages and
                     features.sitemaps. The golden manifest has no browse block, so
                     no facet page; the tree gained sitemap.xml, and the lock its
                     entry and the new pack hash. No page moved.
                     Same day, the user's go ("turn on dd entities"): dd's pack
                     turns on features.entities. The golden manifest has no
                     entities block, so only the lock's pack hash moved.
                     Same day, the user's go ("full text search, search suggestions"):
                     dd's pack turns on features.corpus-search. render_golden now passes
                     the stand-in indexer (search.stand_in), as search.py says the
                     goldens do; no other case turns search on, so none of them moved.
                     The tree gained assets/room-search.js and pagefind/input.json
                     (what Pagefind is given); room.css gained search.css (new name);
                     the index's finder is room-search.js's (data-room-search, the
                     combobox and the results list); the lock gained `search` and the
                     new pack hash.
                     Same day, the user's go to port live's top-match ranking: room-search.js
                     gained dd's scoreDoc (used only with site.index.suggest.rank, which the
                     golden manifest does not carry), so only its asset name and the lock
                     moved.
                     Same day, the user's go on the status table ("go ahead and build it"):
                     room-search.js lets a site suggestion set a finder filter (dd's
                     Status and Record kind groups), which the golden manifest does not
                     carry, so again only its asset name and the lock moved.
    glassgovernment.txt  2026-10-21, index-stats parity on a fresh GG export: live's
                     header reads "455 documents" over a result count of "455
                     records", so GG's pack names the header's noun apart
                     (labels.stats_singular/stats_plural). Only the header stat's
                     word, index.html's hash in the lock and the pack hash moved.
                     Same day, after parity on that export (collections 40/40, topics
                     74/74, documents.txt 463/463): GG's pack turns on
                     features.collections, machine-text and topics. The golden
                     manifest carries none of those blocks, so only the pack hash moved.

    plain            packs/default, more than 12 groups (the jump list folds)
    deflockdane      dd pack, cards, empty groups shown, staging mount + noindex, nav groups
    glassgovernment  GG pack, rows, the light/dark toggle, room_path /library/
    hrtarchive       hrtarchive pack on its synthetic fixture (tests/roomkit/fixtures), cards
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import search as S
from roomkit.manifest import parse

GOLDEN = Path(__file__).resolve().parent / "golden"
ENGINE = GOLDEN / "engine"


def _base() -> dict:
    return json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))


def _plain():
    m = _base()
    filler = m["documents"][1]
    m["documents"] += [dict(copy.deepcopy(filler), slug=f"filler-{i}", title=f"Filler {i}",
                            index={"group": f"Group {i}", "facets": {"year": str(2010 + i)}}) for i in range(10)]
    return parse(m), {}


def _deflockdane():
    m = _base()
    m["site"]["template"] = "deflockdane"
    return parse(m), {"mount": "/rr-staging/", "noindex": True}


def _glassgovernment():
    m = _base()
    m["site"].update({"template": "glassgovernment", "room_path": "/library/"})
    return parse(m), {}


def _hrtarchive():
    fixture = GOLDEN.parent / "fixtures" / "hrtarchive-mini.json"
    return parse(json.loads(fixture.read_text(encoding="utf-8"))), {}


CASES = {"plain": _plain, "deflockdane": _deflockdane, "glassgovernment": _glassgovernment,
         "hrtarchive": _hrtarchive}


def render_golden(case: str) -> bytes:
    m, kw = CASES[case]()
    assert not m.refusals, m.refusals
    files = B.render(m, engine=ENGINE, indexer=S.stand_in, **kw)
    return b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))


@pytest.mark.parametrize("case", sorted(CASES))
def test_output_is_byte_identical_to_the_golden_file(case):
    want = (GOLDEN / f"{case}.txt").read_bytes()
    got = render_golden(case)
    if got != want:
        at = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        pytest.fail(f"{case}: output differs from golden/{case}.txt at byte {at}: "
                    f"got {got[max(0, at - 60):at + 60]!r}, want {want[max(0, at - 60):at + 60]!r}")


def test_the_golden_cases_cover_both_layouts_the_toggle_and_the_folded_jump_list():
    plain, dd, gg = (render_golden(c).decode() for c in ("plain", "deflockdane", "glassgovernment"))
    assert "<details><summary>" in plain and "room__groups--rows" in plain
    assert "room__groups--cards" in dd and "No records have been released for this agency yet." in dd
    assert 'name="robots" content="noindex, nofollow"' in dd and '"/rr-staging/' in dd
    assert "data-room-toggle" in gg and 'data-room-theme-key="ggrr-theme"' in gg
    for out in (plain, dd, gg):
        assert "room__download" in out and "data-poster=" in out and 'data-ext="txt"' in out
    # Every case is the room's own chrome; none carries anything captured from WordPress.
    for case in CASES:
        out = render_golden(case).decode()
        assert '<header class="room-chrome room-chrome--head">' in out and "=== assets/theme/" not in out, case
        assert '"pack": "' in out and '"shell"' not in out, case
    assert 'class="room-chrome__group"' in dd  # nav groups (dd's Maps, Open Records)
