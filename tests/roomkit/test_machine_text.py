"""roomkit machine text (pack features.machine-text): GG's /library/documents.txt as the
exporter writes it (roomkit/machine_text.py), and parity.machine_text."""

from __future__ import annotations

import copy
import json
import re
from pathlib import Path

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import machine_text as MT
from roomkit import pack as K
from roomkit import search as S
from roomkit.manifest import parse

HERE = Path(__file__).resolve().parent
GOLDEN = HERE / "golden"
ENGINE = GOLDEN / "engine"
ROOM = "https://example.test/library/"
EXPORTERS = HERE.parents[1] / "roomkit" / "exporters"

# The live template's shape (txt-ggrr-documents.php), for the golden manifest's records.
TEXT = (
    "Glass Government — Records Reading Room\n"
    "========================================\n"
    "Total documents: 2\n"
    f"URL: {ROOM}\n"
    "Generated: 2026-10-20 21:23:46 GMT\n"
    "\n"
    f"- [Camera Contract]({ROOM}camera-contract/) — Camera Contract | Test Agency | contracts | 2026-01-02"
    " (sha256:aaaa)\n"
    f"- [Memo]({ROOM}memo-text/) — Memo | Second Agency [third-party] [IA]\n"
    "\n---\n"
    "End of index. 2 documents listed.\n")


def _raw(text: str | None = TEXT, url: str = ROOM + "documents.txt") -> dict:
    m = json.loads((GOLDEN / "manifest.json").read_text(encoding="utf-8"))
    m["site"]["template"] = "glassgovernment"
    m["site"]["room_path"] = "/library/"
    if text is not None:
        m["machine_text"] = {"files": [{"url": url, "text": text}],
                             "source": {"templates/txt-ggrr-documents.php": "0" * 64}}
    return m


def _pack(on: bool = True) -> dict:
    p = copy.deepcopy(K.for_site("glassgovernment"))
    p["features"] = {**p.get("features", {}), "machine-text": on}
    return p


def _render(on: bool = True, raw: dict | None = None, **kw) -> dict[str, bytes]:
    m = parse(raw if raw is not None else _raw())
    assert not m.refusals, m.refusals
    return B.render(m, engine=ENGINE, indexer=S.stand_in, pack=_pack(on), **kw)


def _refusals(raw: dict) -> list[str]:
    return [why for where, why in parse(raw).refusals if where == "machine_text"]


# --- the switch ------------------------------------------------------------------------

def test_switch_off_builds_exactly_the_room_without_machine_text():
    assert _render(False) == _render(False, _raw(None))


def test_switch_off_keeps_the_golden_bytes():
    from tests.roomkit import test_golden as TG
    _, kw = TG.CASES["glassgovernment"]()
    files = B.render(parse(_raw()), engine=ENGINE, indexer=S.stand_in, pack=_pack(False), **kw)
    got = b"".join(f"=== {p} ===\n".encode() + files[p] + b"\n" for p in sorted(files))
    pack_line = re.compile(rb'\n "pack": "[0-9a-f]{64}",\n')
    assert pack_line.sub(b"\n", got) == pack_line.sub(b"\n", (GOLDEN / "glassgovernment.txt").read_bytes())


def test_only_gg_turns_machine_text_on():
    # GG turned it on 2026-10-21, after parity.machine_text passed 463/463 against a fresh export.
    assert MT.enabled(K.for_site("glassgovernment"))
    for site in ("default", "deflockdane", "hrtarchive"):
        assert not MT.enabled(K.for_site(site)), site


def test_switch_on_serves_the_exported_bytes_in_utf8_with_the_page_cache_policy():
    files = _render()
    assert files["documents.txt"] == TEXT.encode("utf-8")
    ht = files[".htaccess"].decode()
    assert "AddCharset UTF-8 .txt" in ht and '<FilesMatch "\\.(html|txt)$">' in ht
    lock = json.loads(files["room.lock.json"])
    assert lock["files"]["documents.txt"] == B.sha256(TEXT.encode("utf-8"))
    off = _render(raw=_raw(None))[".htaccess"].decode()
    assert "AddCharset" not in off and '<FilesMatch "\\.html$">' in off


def test_switch_on_without_a_block_ships_nothing():
    assert "documents.txt" not in _render(raw=_raw(None))


def test_the_mount_does_not_touch_the_text():
    # The file names the live URLs, as live does; a staging mount changes no byte of it.
    assert _render(mount="/rr-staging/", noindex=True)["documents.txt"] == TEXT.encode("utf-8")


# --- what the manifest refuses ---------------------------------------------------------

@pytest.mark.parametrize("raw, why", [
    (_raw(TEXT + f"- [Gone]({ROOM}not-here/)\n"), f"links {ROOM}not-here/, not a record in this room"),
    (_raw(TEXT + f"- [Odd]({ROOM}camera-contract)\n"), "not a record in this room"),
    (_raw(TEXT, url=ROOM + "sub/documents.txt"), "is not a <name>.txt directly under"),
    (_raw(TEXT, url="https://example.test/llms-full.txt"), "is not a <name>.txt directly under"),
    (_raw(TEXT, url=ROOM + "documents.html"), "is not a <name>.txt directly under"),
    (_raw("  \n"), "text is empty or not text"),
])
def test_a_bad_block_is_refused_and_named(raw, why):
    got = _refusals(raw)
    assert any(why in g for g in got), got


def test_the_same_path_twice_and_an_unknown_key_are_refused():
    raw = _raw()
    raw["machine_text"]["files"].append(dict(raw["machine_text"]["files"][0]))
    assert any("documents.txt twice" in g for g in _refusals(raw))
    raw = _raw()
    raw["machine_text"]["extra"] = 1
    assert _refusals(raw) == ["machine_text is not {files: [...], source?}"]


def test_links_outside_the_room_are_left_alone():
    assert not _refusals(_raw(TEXT + "- <https://glassgovernment.org/> — home\n"))


# --- parity.machine_text ---------------------------------------------------------------

def test_equal_but_for_the_generated_time_passes():
    later = TEXT.replace("2026-10-20 21:23:46 GMT", "2026-10-21 08:00:00 GMT")
    rep = MT.compare(later, TEXT)
    assert rep == {"ok": True, "live_lines": 10, "room_lines": 10}


def test_a_changed_line_fails_and_says_which():
    rep = MT.compare(TEXT.replace("[IA]", ""), TEXT)
    assert not rep["ok"] and rep["first_difference"]["live_line"] == rep["first_difference"]["room_line"] == 8
    assert rep["first_difference"]["room"].endswith("[IA]")


def test_a_missing_line_fails():
    rep = MT.compare(TEXT, TEXT.replace(f"- [Memo]({ROOM}memo-text/) — Memo | Second Agency [third-party] [IA]\n", ""))
    assert not rep["ok"] and rep["live_lines"] == 10 and rep["room_lines"] == 9


def test_the_cli_compares_a_saved_live_file_with_the_room(tmp_path, capsys):
    B.write(_render(), tmp_path / "room")
    (tmp_path / "live.txt").write_text(TEXT.replace("21:23:46", "22:00:00"), encoding="utf-8")
    assert cli.main(["parity", "--machine-text", str(tmp_path / "live.txt"), "--out", str(tmp_path / "room")]) == 0
    assert "PASSES: documents.txt 10 live lines, 10 in the room" in capsys.readouterr().out
    (tmp_path / "live.txt").write_text(TEXT.replace("Memo", "Memorandum"), encoding="utf-8")
    assert cli.main(["parity", "--machine-text", str(tmp_path / "live.txt"), "--out", str(tmp_path / "room")]) == 1


# --- the exporter (read as text: the gate has no php) ------------------------------------

def test_the_gg_exporter_writes_documents_txt_with_the_live_templates_formula():
    src = (EXPORTERS / "glassgovernment.php").read_text(encoding="utf-8")
    block = src[src.index("// --- machine_text:"):src.index("// --- passages:")]
    for formula in (
        "GGRR_Storage::get_documents(['visibility' => 'public', 'limit' => 999])",  # the same call, the same cap
        '"Glass Government — Records Reading Room\\n"',
        "\"Generated: \" . gmdate('Y-m-d H:i:s T')",
        "implode(' | ', array_filter([$_title, (string) ($d['agency'] ?? ''), (string) ($d['collection'] ?? ''),",
        '" [third-party]"', '" [IA]"', "($d['ia_status'] ?? '') === 'confirmed'",
        '"End of index. " . count($mt_docs) . " documents listed.\\n"',
    ):
        assert formula in block, formula
    assert "($slice === null || $slice['offset'] === 0)" in block
    assert "+ ($machine_text ? ['machine_text' => $machine_text] : [])" in src
