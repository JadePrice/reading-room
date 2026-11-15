"""Cleaning machine-read page text: the one rule read-aloud and the text view share.

OCR keeps the scan's line breaks, so a word split across two lines arrives as "hear-\\ning" (or with
the "¬" continuation mark). The rule is the one the read-aloud player (reading-room-reader/
read-aloud/rr-read-aloud.js `cleanText`, after Internet Archive BookReader's
_removeDanglingHyphens) has always used: a hyphen or "¬" at a line end, with the whitespace around
that break, is removed, and the two halves join.

    join_hyphenated(text)   the rule alone (line breaks that are not hyphenated stay)
    clean_text(text)        the rule, then every whitespace run to one space: exactly `cleanText`
    paragraphs(text)        the text view's shape: blank lines split paragraphs, a paragraph is a
                            list of lines (line breaks are kept inside it), hyphens rejoined

JS twin: templates/room/text-clean.js (not shipped; the twin for any room script that needs the
rule). tests/roomkit/test_text_clean.py runs the Python, the twin and the player on one set of
fixtures and requires the same answers.

Whitespace is JavaScript's `\\s`, written out, so Python and JS agree on every character (Python's
own `\\s` also matches \\x1c-\\x1f and \\x85, which JS does not).
"""

from __future__ import annotations

import re

# JavaScript's \s: space, tab, VT, FF, CR, LF, NBSP, the Zs spaces, LS, PS, BOM.
WS = r"[ \t\n\r\f\v\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff]"
_BREAK = re.compile(rf"[-\u00ac]{WS}*\n{WS}*")
_RUN = re.compile(f"{WS}+")
_BLANK = re.compile(rf"\n{WS}*\n")
_STRIP = re.compile(f"^{WS}+|{WS}+$")


def join_hyphenated(text: object) -> str:
    """The text with each hyphen (or "¬") line end joined to the next line."""
    return _BREAK.sub("", "" if text is None else str(text))


def clean_text(text: object) -> str:
    """One line of speakable text: hyphen line ends joined, whitespace collapsed, trimmed."""
    return _STRIP.sub("", _RUN.sub(" ", join_hyphenated(text)))


def paragraphs(text: object) -> list[list[str]]:
    """Paragraphs of lines, for display: hyphen line ends joined, blank lines split paragraphs,
    line breaks inside a paragraph kept, each line trimmed, empty lines and paragraphs dropped."""
    joined = join_hyphenated(str(text or "").replace("\r\n", "\n").replace("\r", "\n"))
    out = []
    for block in _BLANK.split(joined):
        lines = [_STRIP.sub("", ln) for ln in block.split("\n")]
        lines = [_RUN.sub(" ", ln) for ln in lines if ln]
        if lines:
            out.append(lines)
    return out
