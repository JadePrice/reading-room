"""The exporters fail loudly when the manifest can't be JSON-encoded.

A plain json_encode returns false on invalid UTF-8 (an OCR'd Latin-1 byte in a
title), and the exporter used to print a bare newline and exit 0. The final
encode must throw, and the catch must write one line to stderr and exit 1, so
nothing partial or empty ever reaches the manifest file.

This reads the PHP as text: the gate has no php binary (tests that run PHP, like
tests/powermapkit, skip without one). The behaviour itself was run under PHP 8.3
with WordPress stubs: /srv/tmp/wt-room-entities-checkpoints.md, E8.
"""
import re
from pathlib import Path

import pytest

EXPORTERS = Path(__file__).resolve().parents[2] / "roomkit" / "exporters"


@pytest.mark.parametrize("name", ["glassgovernment.php", "deflockdane.php"])
def test_the_manifest_encode_throws_and_the_catch_exits_1_on_stderr(name):
    src = (EXPORTERS / name).read_text(encoding="utf-8")
    # The manifest is the one encode whose result is held, not written inline.
    held = re.findall(r"\$json = json_encode\(\[(.*?)\]\s*\+[^;]*?,\s*([A-Z_| ]+)\);", src, re.DOTALL)
    assert len(held) == 1, f"{name}: expected one held manifest encode, found {len(held)}"
    assert "JSON_THROW_ON_ERROR" in held[0][1], f"{name}: the manifest encode does not throw"
    tail = src[src.index("$json = json_encode(["):]
    catch = re.search(r"\}\s*catch \(JsonException \$e\) \{(.*?)\n\}", tail, re.DOTALL)
    assert catch, f"{name}: no catch (JsonException ...) after the manifest encode"
    body = catch.group(1)
    assert "fwrite(STDERR" in body and "$e->getMessage()" in body, f"{name}: the catch must name the error on stderr"
    assert "exit(1)" in body, f"{name}: the catch must exit 1"
    assert "STDOUT" not in body, f"{name}: the catch must not write to stdout"
    after = tail[catch.end():]
    assert after.lstrip().startswith('fwrite(STDOUT, $json . "\\n");'), f"{name}: stdout must be written only after a successful encode"
    # Nothing else writes the manifest inline any more.
    assert "fwrite(STDOUT, json_encode([\n    'site'" not in src


def test_the_gg_exporter_sends_a_record_with_text_and_no_file_as_text_only():
    src = (EXPORTERS / "glassgovernment.php").read_text(encoding="utf-8")
    assert "$text_only = !$attached && trim((string) ($doc['full_text']" in src
    assert "'no_file' => $text_only ? 'No file is attached to this record yet.' : ''" in src
    assert "'Pending local file hash'" in src
    # An attached file that is unreadable or altered is still a problem, not a text-only page.
    # "Attached" is read from the row: has_servable_file() is false for a managed_path whose
    # file is gone from disk, which must not pass as "no file attached".
    attached = src[src.index("$attached = "):src.index("$text_only = ")]
    for field in ("managed_path", "attachment_id", "ia_id"):
        assert f"$doc['{field}']" in attached, field
    assert "has_servable_file" not in attached
    assert "'no servable file'" in src and "'file bytes do not hash to file_sha256'" in src


def test_the_gg_exporter_writes_collections_with_the_live_templates_formulas():
    # The three templates build their words inline; each formula is repeated in the
    # exporter (run under PHP 8 with WordPress stubs on 2026-10-20: the output parses
    # and builds; tests/roomkit/test_collections.py checks what the room does with it).
    src = (EXPORTERS / "glassgovernment.php").read_text(encoding="utf-8")
    block = src[src.index("// --- collections:"):src.index("// --- passages:")]
    for formula in (
        "($n === 1 ? 'file' : 'files') . ', in order'",                        # the page's count
        "$m['category'] === 'historical' ? 'Federal File' : 'Public Records'",  # its stamp
        "if ($n > 8)",                                                            # the search only past 8
        "str_pad((string) (int) $num, 2, '0', STR_PAD_LEFT)",                    # the row number
        "preg_match('/\\bfinal\\b/', $t)",                                        # "Final"
        "strtoupper(substr(str_replace('_', '-', $slug), 0, 10))",               # the card code
        "(int) $row['count'] . ' files'",                                        # the card count
        "strtolower($title . ' ' . $group . ' ' . ($m['blurb'] ?? ''))",          # the card's search text
        "'modern' => 'Recent'",                                                   # the index table's era word
        "(count($srcs) > 1 ? 'Sources: ' : 'Source: ')",                         # the narrow sources line
        "(string) ($m['title'] ?? $group)",                                      # a table row's title
    ):
        assert formula in block, formula
    # First slice only, and in the manifest beside entities.
    assert "($slice === null || $slice['offset'] === 0)" in block
    assert "+ ($collections ? ['collections' => $collections] : [])" in src
