"""Passage citations (site A): the switch, the block's refusals, what the
room ships, parity.passages, and the reader's cite panel in a browser.

Only the key and slicing rules are here; the tests that build a room with passages
run on a site's pack and fixture, in tests/roomkit/sites/test_passages_sites.py.
"""

from __future__ import annotations

from pathlib import Path

from roomkit import passages as PS

HERE = Path(__file__).resolve().parent


def test_stable_key_and_slices_are_the_plugins():
    # The site plugin's stable_key, checked against a live answer (2026-10-15).
    assert PS.stable_key(505, 2, 72, 152) == "e8e78fcf23f030f850ebfe52560d74b314ac7940df95006ff235fcb650fdbed7"
    assert PS.stable_key(7, None, 0, 3) == __import__("hashlib").sha256(b"7||0|3").hexdigest()
    assert PS.slice_text("\U0001F693 café flock", 2, 6) == "café"   # code points, as mb_substr
