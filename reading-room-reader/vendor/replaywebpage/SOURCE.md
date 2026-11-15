# ReplayWeb.page, vendored

- Package: `replaywebpage` 2.5.3 (npm, published 2026-09-03), by Webrecorder.
- Source: https://github.com/webrecorder/replayweb.page/tree/v2.5.3
- License: AGPL-3.0-or-later (`LICENSE`). Vendored **unmodified**; the reader links visitors to the source above.
- Files: `ui.js` (the `<replay-web-page>` element) and `sw.js` (its service worker). The `ruffle/` and `adblock/` extras are left out on purpose: the reader turns both off, and adblock would fetch filter lists.
- `SHA256SUMS` pins the bytes; `tests/reading_room_reader/test_reader_archive.py` checks them.

To update: `npm pack replaywebpage@<version>` (a release at least two weeks old), copy `ui.js`, `sw.js`, `LICENSE`, re-run `shasum -a 256 ui.js sw.js LICENSE > SHA256SUMS`, update this file, and run the archive tests.
