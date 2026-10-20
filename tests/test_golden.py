"""The room's output, pinned byte for byte, one golden file per theme.

Pins static build output against verified golden files.
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
    m["documents"] += [
        dict(
            copy.deepcopy(filler),
            slug=f"filler-{i}",
            title=f"Filler {i}",
            index={"group": f"Group {i}", "facets": {"year": str(2010 + i)}},
        )
        for i in range(10)
    ]
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


CASES = {
    "plain": _plain,
    "deflockdane": _deflockdane,
    "glassgovernment": _glassgovernment,
    "hrtarchive": _hrtarchive,
}


def render_golden(case: str) -> bytes:
    m, kw = CASES[case]()
    assert not m.refusals, m.refusals
    files = B.render(m, engine=ENGINE, indexer=S.stand_in, **kw)
    return b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))


@pytest.mark.parametrize("case", sorted(CASES))
def test_output_is_byte_identical_to_the_golden_file(case: str) -> None:
    want = (GOLDEN / f"{case}.txt").read_bytes()
    got = render_golden(case)
    if got != want:
        at = next((i for i, (a, b) in enumerate(zip(got, want)) if a != b), min(len(got), len(want)))
        pytest.fail(
            f"{case}: output differs from golden/{case}.txt at byte {at}: "
            f"got {got[max(0, at - 60):at + 60]!r}, want {want[max(0, at - 60):at + 60]!r}"
        )


def test_the_golden_cases_cover_both_layouts_the_toggle_and_the_folded_jump_list() -> None:
    plain, dd, gg = (render_golden(c).decode() for c in ("plain", "deflockdane", "glassgovernment"))
    assert "<details><summary>" in plain and "room__groups--rows" in plain
    assert "room__groups--cards" in dd and "No records have been released for this agency yet." in dd
    assert 'name="robots" content="noindex, nofollow"' in dd and '"/rr-staging/' in dd
    assert "data-room-toggle" in gg and 'data-room-theme-key="ggrr-theme"' in gg
    for out in (plain, dd, gg):
        assert "room__download" in out and "data-poster=" in out and 'data-ext="txt"' in out
    for case in CASES:
        out = render_golden(case).decode()
        assert '<header class="room-chrome room-chrome--head">' in out and "=== assets/theme/" not in out, case
        assert '"pack": "' in out and '"shell"' not in out, case
    assert 'class="room-chrome__group"' in dd
