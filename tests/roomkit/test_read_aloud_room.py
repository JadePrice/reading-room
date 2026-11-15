"""Read-aloud in the static room (pack `read-aloud`; reading-room-reader/read-aloud).

The switch off ships nothing; on, a record with page texts gets the player script
(fingerprinted, in the lock), `data-read-aloud` on the reader mount beside its
`data-pages-url`, and the panel's CSS. The browser tests drive the panel in headless
Chromium with a stubbed `speechSynthesis` (so they prove wiring and requests, never that
audio was heard).
"""

from __future__ import annotations

from roomkit import build as B


def test_no_em_dash_in_what_the_listener_sees():
    js = B.READ_ALOUD_JS.read_text(encoding="utf-8")
    code = [ln for ln in js.splitlines() if not ln.lstrip().startswith("//")]
    assert not [ln for ln in code if "—" in ln]
    readme = (B.READ_ALOUD_JS.parent / "README.md").read_text(encoding="utf-8")
    assert "Machine-read aloud in your browser. Voices vary by device." in readme
