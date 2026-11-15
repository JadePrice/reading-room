"""roomkit machine text (pack features.machine-text): site A's /library/documents.txt as the
exporter writes it (roomkit/machine_text.py), and parity.machine_text."""

from __future__ import annotations

from pathlib import Path

from roomkit import machine_text as MT

HERE = Path(__file__).resolve().parent
ROOM = "https://example.test/library/"

# The live template's shape (the site plugin's documents.txt template), for the golden manifest's records.
TEXT = (
    "Example Archive — Records Reading Room\n"
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
