"""The room's output, pinned byte for byte, one golden file per case.

A golden file is the whole rendered tree, every file under an `=== path ===` header, lock
included. The engine is a stand-in (`golden/engine/`), so an engine release does not move
these files; only the template, the shipped packs and the build do.

A difference here is a change to every page a site serves. Never regenerate a golden file
to make this pass; when a change is meant to alter the output, say which and why in the
commit that replaces it, and add a line here.

    plain           packs/default, more than 12 groups (the jump list folds)
    example         packs/example: cards, empty groups shown, the light/dark toggle
    example-folded  packs/example with more than 12 groups, under another mount, noindex

plain.txt was pinned on roomkit 0.3.0's string template before the Jinja port and has
moved on purpose since.
example.txt and example-folded.txt were pinned on 2026-11-13.
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


def _example():
    m = _base()
    m["site"]["template"] = "example"
    return parse(m), {}


def _example_folded():
    m = _base()
    filler = m["documents"][1]
    m["documents"] += [dict(copy.deepcopy(filler), slug=f"filler-{i}", title=f"Filler {i}",
                            index={"group": f"Group {i}", "facets": {"year": str(2010 + i)}}) for i in range(10)]
    m["site"]["template"] = "example"
    return parse(m), {"mount": "/records/", "noindex": True}


CASES = {"plain": _plain, "example": _example, "example-folded": _example_folded}
CORE_CASES = tuple(CASES)


def golden_file(case: str) -> Path:
    return GOLDEN / f"{case}.txt"


def golden_bytes(files: dict[str, bytes]) -> bytes:
    """A rendered tree as a golden file: every file under an `=== path ===` header. A mapped
    theme's fonts and images are pinned by hash and size, not as bytes in a text file."""
    return b"".join(f"=== {p} ===\n".encode()
                    + (f"sha256 {B.sha256(files[p])} {len(files[p])}".encode() if p.startswith(B.THEME_DIR) else files[p])
                    + b"\n" for p in sorted(files))


def render_golden(case: str, cases: dict | None = None) -> bytes:
    m, kw = (cases or CASES)[case]()
    assert not m.refusals, m.refusals
    return golden_bytes(B.render(m, engine=ENGINE, indexer=S.stand_in, **kw))


@pytest.mark.parametrize("case", CORE_CASES)
def test_output_is_byte_identical_to_the_golden_file(case):
    want = golden_file(case).read_bytes()
    got = render_golden(case)
    if got != want:
        at = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        pytest.fail(f"{case}: output differs from {golden_file(case).relative_to(GOLDEN.parent)} at byte {at}: "
                    f"got {got[max(0, at - 60):at + 60]!r}, want {want[max(0, at - 60):at + 60]!r}")


def test_the_core_golden_cases_cover_both_layouts_the_toggle_and_the_folded_jump_list():
    plain, ex, folded = (render_golden(c).decode() for c in CORE_CASES)
    assert "room__groups--rows" in plain and "<details><summary>Jump to group (14)" in plain
    assert "room__groups--cards" in ex and "room__groups--cards" in folded
    assert 'data-room-theme-key="riverbend-scheme"' in ex and "data-room-theme-key=" not in plain
    assert "room__toggle\" data-room-toggle" in ex and "room__toggle\" data-room-toggle" not in plain
    assert "<details><summary>Go to a department" not in ex and "<details><summary>Go to a department (14)" in folded
    assert "No records have been released for this agency yet." in ex  # the pack shows empty groups
    assert 'name="robots" content="noindex, nofollow"' in folded and '"/records/' in folded
    for out in (plain, ex, folded):
        assert '<header class="room-chrome room-chrome--head">' in out and "=== assets/theme/" not in out
        assert "room__download" in out and "data-poster=" in out and 'data-ext="txt"' in out
    assert 'class="room-chrome__group"' in ex  # the pack's nav group
