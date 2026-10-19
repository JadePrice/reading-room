"""Site packs: custom styling, tokens, and chrome for reading room instances."""

from __future__ import annotations

import copy
import json

import jsonschema
import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import pack as K
from tests import test_golden as G

SITES = ("default", "deflockdane", "glassgovernment", "hrtarchive")


def _pack(site: str = "default") -> dict:
    return copy.deepcopy(K.for_site(site))


def _problems(pack: dict, **kw) -> list:
    return K.validate(pack, **kw)


def test_the_schema_is_valid_json_schema() -> None:
    jsonschema.Draft202012Validator.check_schema(json.loads(K.SCHEMA.read_text()))


@pytest.mark.parametrize("site", SITES)
def test_the_shipped_packs_pass_every_check(site: str) -> None:
    from roomkit import parity as P

    assert _problems(_pack(site), root=K.PACKS / site, matrix=P.load_matrix(cli.MATRIX)) == []


@pytest.mark.parametrize(
    "case, site",
    [
        ("plain", "default"),
        ("deflockdane", "deflockdane"),
        ("glassgovernment", "glassgovernment"),
        ("hrtarchive", "hrtarchive"),
    ],
)
def test_an_explicit_pack_builds_the_same_bytes_as_the_golden_file(case: str, site: str) -> None:
    m, kw = G.CASES[case]()
    files = B.render(m, engine=G.ENGINE, pack=K.for_site(site), **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    assert got == (G.GOLDEN / f"{case}.txt").read_bytes()


@pytest.mark.parametrize(
    "mutate, why",
    [
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
    ],
)
def test_the_schema_refuses_what_a_pack_may_not_say(mutate, why: str) -> None:
    p = _pack()
    mutate(p)
    probs = _problems(p)
    assert any(why in x for x in probs), f"expected {why!r} in {probs!r}"


def test_a_missing_color_token_is_refused_light_and_dark() -> None:
    p = _pack()
    del p["tokens"]["ink"]
    del p["tokens_dark"]["focus"]
    assert _problems(p) == ["tokens: missing 'ink'", "tokens_dark: missing 'focus'"]


def test_contrast_would_have_stopped_the_dd_white_panels() -> None:
    p = _pack("deflockdane")
    p["tokens"].update(surface="#ffffff")
    probs = _problems(p)
    assert "tokens: ink on surface is 1.29:1, needs 4.5:1 (panel text)" in probs


def test_contrast_is_checked_in_dark_too_and_for_focus_rings() -> None:
    p = _pack("glassgovernment")
    p["tokens_dark"]["focus"] = p["tokens_dark"]["page-bg"]
    assert "dark: focus on page-bg is 1.00:1, needs 3.0:1 (focus ring on the page)" in _problems(p)
