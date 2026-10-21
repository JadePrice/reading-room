"""Packs derived from design-tokens/*.tokens.css through a map (plan Task 4).

The packs cite the site's tokens instead of copying hex values by hand; a value
that is not simply the site's says why. A duplicate or unresolvable variable is
a refusal, never a guess.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import pack as K
from roomkit import pack_import as PI
from roomkit import tokens_css as T

SITES_WITH_MAPS = ("deflockdane", "glassgovernment", "hrtarchive")

CSS = """
:root {
  --bg: #ffffff; --panel: #f4f4f4;  /* a comment; with a semicolon */
  --ink: #111111; --soft: #555555; --link: #1f4e8c; --accent: var(--ink);
  --font: var(--missing, Georgia, serif);
}
:root { --tier: var(--accent); }
@media (prefers-contrast: more) { :root { --ink: #000000; } }
"""


def test_tokens_css_reads_top_level_root_and_resolves_references():
    t = T.read(CSS)
    assert t.values["--accent"] == "#111111" and t.values["--tier"] == "#111111"
    assert t.values["--font"] == "Georgia, serif" and t.problems == {}
    assert t.variants == {"--ink": ["@media (prefers-contrast: more): #000000"]}


def test_tokens_css_names_duplicates_unresolved_names_and_cycles():
    t = T.read(":root{--a:#fff;--b:var(--nope);--c:var(--d);--d:var(--c)} :root{--a:#000}")
    assert t.problems["--a"] == ["defined twice at the top level ('#fff', then '#000')"]
    assert t.problems["--b"] == ["refers to --nope, which the file does not define"]
    assert any("refers to itself" in p for p in t.problems["--c"])


def _site(tmp_path: Path, css: str = CSS, **map_over) -> Path:
    (tmp_path / "tokens.css").write_text(css)
    pack_dir = tmp_path / "packs" / "x"
    pack_dir.mkdir(parents=True)
    pack = K.for_site("default")
    del pack["tokens_dark"]
    (pack_dir / "pack.json").write_text(json.dumps(pack))
    mp = {"source": "tokens.css",
          "tokens": {"page-ink": "--ink", "page-ink-soft": "--soft", "page-link": "--link", "surface": "--bg",
                     "surface-sunk": "--panel", "ink": "--ink", "ink-soft": "--soft", "rule": "--soft",
                     "link": "--link", "accent": "--accent", "focus": {"var": "--link", "why": "the link blue"},
                     "font-body": "--font"},
          "literal": {"page-bg": {"value": "#ffffff", "why": "the plain page"},
                      "on-accent": {"value": "#ffffff", "why": "white on the dark accent"}}}
    mp.update(map_over)
    (pack_dir / "tokens.map.json").write_text(json.dumps(mp))
    return pack_dir / "tokens.map.json"


def test_a_map_writes_exactly_its_tokens_and_records_every_why(tmp_path):
    res = PI.derive(_site(tmp_path), tmp_path)
    toks = res["pack"]["tokens"]
    assert toks["accent"] == "#111111" and toks["font-body"] == "Georgia, serif" and "font-display" not in toks
    assert res["pack"]["token_notes"] == {"tokens.focus": "the link blue", "tokens.on-accent": "white on the dark accent",
                                          "tokens.page-bg": "the plain page"}
    assert res["variants"] == {"--ink": ["@media (prefers-contrast: more): #000000"]}
    assert K.validate(res["pack"]) == []


@pytest.mark.parametrize("over, why", [
    ({"tokens": {"page-ink": "--nowhere"}}, "tokens.page-ink <- --nowhere: the file does not define it"),
    ({"tokens": {"text-colour": "--ink"}}, "tokens.text-colour: not a room token"),
    ({"literal": {"page-bg": {"value": "#fff"}}}, "tokens.page-bg: a literal needs a value and a why"),
    ({"literal": {"page-bg": {"value": "#fff", "why": "x"}, "ink": {"value": "#000", "why": "x"}}},
     "tokens.ink: both mapped and literal"),
    ({"colours": {}}, "map: unknown key 'colours'"),
    ({"source": "nope.css"}, "map: source 'nope.css' is not a file in the repo"),
])
def test_a_bad_map_is_refused(tmp_path, over, why):
    with pytest.raises(PI.ImportRefused) as exc:
        PI.derive(_site(tmp_path, **over), tmp_path)
    assert why in exc.value.problems


def test_a_duplicated_or_unresolvable_site_variable_is_refused(tmp_path):
    css = CSS + ":root{--ink:#222222; --soft: var(--gone);}"
    with pytest.raises(PI.ImportRefused) as exc:
        PI.derive(_site(tmp_path, css=css), tmp_path)
    assert "tokens.ink <- --ink: defined twice at the top level ('#111111', then '#222222')" in exc.value.problems
    assert any(p.startswith("tokens.ink-soft <- --soft:") for p in exc.value.problems)


def test_an_import_cannot_write_a_pack_the_build_would_refuse(tmp_path):
    mp = _site(tmp_path)
    data = json.loads(mp.read_text())
    data["tokens"]["ink"] = "--panel"  # panel-colored text on panels
    mp.write_text(json.dumps(data))
    with pytest.raises(PI.ImportRefused) as exc:
        PI.derive(mp, tmp_path)
    assert any("ink on surface is" in p for p in exc.value.problems)


@pytest.mark.parametrize("site", SITES_WITH_MAPS)
def test_the_shipped_packs_are_what_their_maps_derive(site):
    # No hand edits to tokens: change the map (or the site's tokens file), then import.
    res = PI.derive(K.PACKS / site / "tokens.map.json", B.REPO_ROOT)
    assert res["changes"] == []
    assert res["pack"] == json.loads((K.PACKS / site / "pack.json").read_text())


def test_cli_dry_run_writes_nothing_and_write_writes(tmp_path, capsys, monkeypatch):
    mp = _site(tmp_path)
    before = (mp.parent / "pack.json").read_text()
    monkeypatch.setattr(B, "REPO_ROOT", tmp_path)
    assert cli.main(["pack", "import", "--map", str(mp), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["written"] is False and out["changes"] and (mp.parent / "pack.json").read_text() == before
    assert cli.main(["pack", "import", "--map", str(mp), "--write"]) == 0
    assert json.loads((mp.parent / "pack.json").read_text())["token_notes"]["tokens.focus"] == "the link blue"
    (tmp_path / "b").mkdir()
    bad = _site(tmp_path / "b", tokens={"page-ink": "--nowhere"})
    assert cli.main(["pack", "import", "--map", str(bad)]) == 2
