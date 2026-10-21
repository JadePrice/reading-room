"""Site packs (plan Task 3): the one place a site customizes the shared room.

The schema (packs/pack.schema.json) is the structure, shared with Civica;
pack.py adds contrast, CSS scoping, the parity matrix and the pack's files.
Every refusal names what is wrong; nothing is guessed.
"""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import color as C
from roomkit import css as CSS
from roomkit import pack as K
from roomkit import room as R
from roomkit import search as S
from roomkit.manifest import parse
from tests.roomkit import test_golden as G

SITES = ("default", "deflockdane", "glassgovernment", "hrtarchive")


def _pack(site="default"):
    return copy.deepcopy(K.for_site(site))


def _problems(pack, **kw):
    return K.validate(pack, **kw)


def test_the_schema_is_valid_json_schema():
    jsonschema.Draft202012Validator.check_schema(json.loads(K.SCHEMA.read_text()))


@pytest.mark.parametrize("site", SITES)
def test_the_shipped_packs_pass_every_check(site):
    from roomkit import parity as P
    assert _problems(_pack(site), root=K.PACKS / site, matrix=P.load_matrix(cli.MATRIX)) == []


@pytest.mark.parametrize("case, site", [("plain", "default"), ("deflockdane", "deflockdane"),
                                        ("glassgovernment", "glassgovernment"), ("hrtarchive", "hrtarchive")])
def test_an_explicit_pack_builds_the_same_bytes_as_the_golden_file(case, site):
    m, kw = G.CASES[case]()
    files = B.render(m, engine=G.ENGINE, pack=K.for_site(site), indexer=S.stand_in, **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    assert got == (G.GOLDEN / f"{case}.txt").read_bytes()


@pytest.mark.parametrize("mutate, why", [
    (lambda p: p.update(colour="red"), "Additional properties are not allowed ('colour'"),
    (lambda p: p["identity"].update(owner="x"), "identity: Additional properties are not allowed ('owner'"),
    (lambda p: p["layout"].update(style="grid"), "layout/style: 'grid' is not one of"),
    (lambda p: p["tokens"].update({"text-colour": "#000"}), "tokens: 'text-colour' is not one of"),
    (lambda p: p["tokens"].update(ink="#000;}body{x:y"), "tokens/ink: '#000;}body{x:y' does not match"),
    (lambda p: p.update(features={"hover-cards": True}), "features: Additional properties are not allowed"),
    (lambda p: p.update(chrome={"nav": [{"label": "Home", "url": "http://x.example/"}]}), "chrome/nav/0/url"),
    (lambda p: p.update(chrome={"nav": [{"label": "Home", "url": "//evil.example/"}]}), "chrome/nav/0/url"),
    (lambda p: p.update(chrome={"nav": [{"label": "Home", "url": "javascript:alert(1)"}]}), "chrome/nav/0/url"),
    (lambda p: p.update(fonts=[{"family": "X", "src": "../../etc/passwd"}]), "fonts/0/src"),
    (lambda p: p["identity"].update(base_url="https://x.example/"), "identity/base_url"),
])
def test_the_schema_refuses_what_a_pack_may_not_say(mutate, why):
    p = _pack()
    mutate(p)
    assert any(why in x for x in _problems(p)), _problems(p)


def test_a_missing_color_token_is_refused_light_and_dark():
    p = _pack()
    del p["tokens"]["ink"]
    del p["tokens_dark"]["focus"]
    assert _problems(p) == ["tokens: missing 'ink'", "tokens_dark: missing 'focus'"]


def test_contrast_would_have_stopped_the_dd_white_panels():
    # 2026-10-12: white plugin panels under dd's light text, 1.29:1.
    p = _pack("deflockdane")
    p["tokens"].update(surface="#ffffff")
    probs = _problems(p)
    assert "tokens: ink on surface is 1.29:1, needs 4.5:1 (panel text)" in probs
    assert all("surface" in x for x in probs)


def test_contrast_is_checked_in_dark_too_and_for_focus_rings():
    p = _pack("glassgovernment")
    p["tokens_dark"]["focus"] = p["tokens_dark"]["page-bg"]
    assert "dark: focus on page-bg is 1.00:1, needs 3.0:1 (focus ring on the page)" in _problems(p)


def test_a_transparent_page_needs_the_color_behind_it():
    p = _pack("deflockdane")
    del p["identity"]["backdrop"]
    assert _problems(p) == ["tokens: page-bg is transparent, so identity.backdrop must name the color behind it"]


def test_a_color_that_cannot_be_measured_is_refused():
    p = _pack()
    p["tokens"]["link"] = "var(--site-link)"
    assert "light: link 'var(--site-link)' is not a hex or oklch() color" in _problems(p)


def test_colors_parse_from_hex_and_oklch():
    assert C.parse("#fff") == ((1.0, 1.0, 1.0), 1.0)
    white, black = C.parse("oklch(100% 0 0)"), C.parse("oklch(0 0 0)")
    assert all(abs(v - 1) < 1e-6 for v in white[0]) and all(abs(v) < 1e-6 for v in black[0])
    assert C.parse("oklch(25% 0.02 60 / 0.32)")[1] == pytest.approx(0.32)
    assert C.parse("var(--x)") is None and C.parse("red") is None
    assert C.contrast((0, 0, 0), (1, 1, 1)) == pytest.approx(21.0)
    assert C.over(((0, 0, 0), 0.5), (1, 1, 1)) == (0.5, 0.5, 0.5)

def test_extra_css_stays_inside_the_room():
    p = _pack()
    p["extra_css"] += ".entry-content p{color:#fff} #room-content a{color:red}"
    assert _problems(p) == [("extra_css: rule '.entry-content p' is not scoped under "
                             "#room-content or .room__skip or body.room-plain")]
    # The room.css rule and this check are the same function.
    assert all(sel.startswith(K.SCOPES) for sel in CSS.css_selectors(R.ROOM_CSS))


def test_a_feature_the_matrix_drops_is_refused():
    rows = [{"id": i, "disposition": "dropped"} for i in K.FEATURE_ROWS["topics"]]
    rows += [{"id": "collections-index", "disposition": "dropped"}]  # one of three: not all dropped
    p = _pack()
    p["features"] = {"topics": True, "collections": True, "entities": False}
    assert _problems(p, matrix=rows) == ["features.topics: on, but the parity matrix drops topics"]


def test_pack_files_must_exist_in_the_pack(tmp_path):
    p = _pack()
    p["fonts"] = [{"family": "Spectral", "src": "fonts/spectral.woff2"}]
    p["identity"]["logo"] = {"src": "logo.svg", "alt": "Site"}
    assert _problems(p, root=tmp_path) == ["fonts/spectral.woff2: not a file in the pack",
                                           "logo.svg: not a file in the pack"]


def test_every_feature_switch_names_real_matrix_rows():
    from roomkit import parity as P
    ids = {r["id"] for r in P.load_matrix(cli.MATRIX)}
    schema = json.loads(K.SCHEMA.read_text())
    assert set(K.FEATURE_ROWS) == set(schema["properties"]["features"]["properties"])
    assert {r for rows in K.FEATURE_ROWS.values() for r in rows} <= ids


def test_build_refuses_a_bad_site_pack_and_writes_nothing(tmp_path, capsys):
    from tests.roomkit.test_roomkit import _manifest, _write
    bad = tmp_path / "pack"
    bad.mkdir()
    p = _pack()
    p["tokens"]["ink"] = p["tokens"]["surface"]
    (bad / "pack.json").write_text(json.dumps(p))
    out = tmp_path / "out"
    assert cli.main(["build", "--manifest", str(_write(tmp_path, _manifest())), "--out", str(out),
                     "--site-pack", str(bad)]) == 2
    assert "ink on surface is 1.00:1" in capsys.readouterr().err and not out.exists()


def test_a_pack_for_another_site_is_refused():
    from tests.roomkit.test_roomkit import _manifest
    data = _manifest()
    data["site"]["template"] = "glassgovernment"
    with pytest.raises(ValueError, match="pack is for 'deflockdane', manifest template is 'glassgovernment'"):
        B.render(parse(data), pack=K.for_site("deflockdane"))
