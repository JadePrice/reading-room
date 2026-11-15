# rr-read-aloud.js — browser-only read-aloud pilot (TTS slice 1)

**Summary:** Site-side read-aloud panel for reading rooms. Follows `rr-reader:pagechange`, speaks the current page with the browser's own voices. No audio files, no network synthesis, no engine change.

## Why this shape

The 2026-10-08 translation decision binds TTS: no document text to any cloud API (no ElevenLabs/Google/Polly). `window.speechSynthesis` synthesizes on-device with client voices — zero egress, zero infra, zero storage. It is also the only synthesis with no model-license questions (contrast NLLB's CC-BY-NC-4.0). If client voices prove inadequate, slice 2 (local batch synthesis on a worker host, per-page audio on R2) gets its own decision; nothing here assumes it.

## What it is / isn't

- **Is:** one ES5 file, no build step (repo convention), opt-in per mount via `data-read-aloud`, panel rendered *outside* the reader mount (modules replace mount contents; the panel must survive re-renders).
- **Isn't:** not vendored (`sync.sh` copies only `src/` — this dir is invisible to it, to `MANIFEST.sha256`, and to a drift check `engines:`), not an engine module, no `data-features` token, no roomkit manifest change, no WP route, no table.

## Control contract

- Mounts only where the site opts in: `.rr-reader[data-file-url][data-read-aloud]`. No attribute, no panel, no behavior change.
- One panel per mount, inserted after the mount: Play/Pause toggle (current page), Stop, Read selection, Show page text, voice `<select>`, rate `<select>` (0.75/1/1.25/1.5), status line `role="status"`, then the page-text region and two notes.
- Speaks the pages in the latest `rr-reader:pagechange` detail (`pages` = shown pages, 1–2 in spread). Page change cancels speech and resets the label — never reads a stale page.
- **No autoplay, ever.** Speech starts only on Play (which is also the user gesture some browsers require). `pages.json` is fetched lazily on first Play or Show page text, once per document, `credentials: same-origin`.
- Reads to the end of the shown page(s), then stops with "Finished page N." Pause/Resume mid-page. Stop cancels everything.
- **Read selection** (2026-11-11): reads only the words the listener selected, in the reader's text layer (born-digital pages; engine 0.12.0 makes a drag select reliably) or in the page-text region below. The selection is taken as the button is pressed (pointer, touch or mouse down), since some phones clear it before the click. Nothing selected, or a selection outside the document (the page title, say), gets "Select some of the page text first, then press Read selection." and no speech. Status: "Reading your selection." then "Finished your selection." A voice or speed change restarts the selection, not the page.
- **Show page text** (2026-11-11): a toggle (`aria-expanded`, `aria-controls`) that reveals a labeled, focusable, scrollable region with the shown page(s)' text from the same `pages.json` (text nodes only, one paragraph per blank-line block, hyphenated line ends rejoined). It is how a scan's words become selectable: a scanned PDF has no text layer. It opens with "Text read from the document by machine. It may have errors. The record is the document file." It follows page turns while open, never speaks, and works even where `speechSynthesis` is missing.
- Mounts without `speechSynthesis` get a plain "Read-aloud isn't available in this browser." note and no controls — the reader and fallback links are untouched.

## Text sources (in order)

1. **Static mode:** the mount's `data-pages-url` (`{pages:[{n, text}]}` — the same feed the engine searches). Zero new endpoints.
2. **Provider override:** `RRReadAloud.setTextProvider(fn)` — `fn(container, [n…])` returns `Promise<string|{text,isMachine}|null>`. This is the seam a WP site uses later; `{text, isMachine}` is the translation-cache shape, announced as "Reading machine translation, page N".
3. **REST mode today:** unsupported on purpose. There is no public full-page-text route, and minting one is the same source-exposure decision as flipping `GET translate-page` public. The panel in REST mode says which page it *would* read and why it can't — honest, never fabricated.

## Voice policy

- Client voices only: `speechSynthesis.getVoices()` (+ `voiceschanged`). No voice is downloaded, fetched, or bundled.
- Default pick: mount `data-lang` (default `en`) matched against voice `lang` prefixes; ES-translated page text gets an ES voice when one exists, else the same voice reads ES text (voices vary by device — stated in the panel footnote).
- Rate and voice are per-listener choices, persisted nowhere (no cookies, no storage — nothing to clear).
- Panel footnote, always visible: "Machine-read aloud in your browser. Voices vary by device. The record is the document file, not this audio."

## Accessibility (must hold per release)

- Real `<button>`s and labeled `<select>`s; Play toggles `aria-pressed`; state changes announced via the `role="status"` line ("Reading page 3 of 12", "Paused", "Stopped", "Finished page 3", "There's no readable text for this page").
- Every control ≥ 44×44; borders/text reuse `--rr-*` tokens with light fallbacks so both bridges pass contrast; focus ring on `--rr-focus`.
- `prefers-reduced-motion`: nothing animates, so nothing to disable — the rule is that future highlight-follows-speech work must also be motion-safe.
- Keyboard: Tab to panel, Enter/Space operate, speech never steals focus. Speech canceled on `pagehide` (no ghost audio after navigation).
- No-JS: panel never renders; fallback links and citation work exactly as before.

## CSP / network

- `script-src 'self'` clean: `addEventListener` only, no inline handlers, no `eval`, ES5.
- Network: one same-origin `fetch` of `pages.json` per document, only after the listener presses Play. No third-party `connect-src`, no telemetry, no logging of text.

## Known limitations (stated, not hidden)

- Mitigated 2026-10-09: OCR line-end hyphenation (`-`/`¬` + newline) is rejoined in `cleanText` before chunking (IA BookReader parity); Chrome's ~15s remote-voice cutoff (chromium #679437) is re-armed by a pause/resume watchdog every 14s while speaking, cleared on every stop path. Both covered by `test_read_aloud.py`.
- Remaining: running heads/tables are still read literally; Firefox/Android may not fire `pause` (mid-utterance resume restarts the chunk — no `boundary` tracking yet); Safari/iOS voice lists are thin. Browser matrix in Verification.
- Single-view (image/text) mounts emit no `pagechange`; the panel reads page 1 on Play. Full support there follows real use.

## How translation AI feeds read-aloud

**On hold (owner, 2026-11-10): no machine translation is published until a named person has reviewed it.** No Spanish reviewer is available, so the translation offer is the visitor's own browser translating the page. The design below stays the plan for when a reviewer exists; nothing ships it today.

Machine translation and read-aloud are separate derivations of the same page text, combined only at listen time:

1. **Translation stays server-side and cached.** The OPUS-MT pilot on a worker host fills `wp_site_a_page_translations` keyed `(document_id, page_number, page_sha256, language)` with `is_machine=1`; the browser never calls a model and no page text ever leaves the device for synthesis. The no-cloud rule binds both halves.
2. **The provider seam carries translated text.** A WP site serves the cached ES translation through `RRReadAloud.setTextProvider(fn)` — the same seam as source text, no new contract. (Mirrors IA BookReader reading from its `.BRtranslateLayer` when translation is active.)
3. **Voice follows language.** `pickVoice` matches the mount `data-lang` (or the provider's language) against voice `lang` prefixes, so cached ES text gets an ES voice when one exists, else the same voice reads ES text (stated in the footnote). Voice preference is unit-tested (`test_es_voice_pick_prefers_spanish`).
4. **Spoken translation is labeled twice.** The panel footnote already says machine-read; when the provider serves `is_machine` text the status line announces "Reading machine translation, page N" — spoken output is never citable, matching the translation policy (MT never authoritative, source excerpt alongside).
5. **No whole-document TTS+MT playlists in slice 1.** Per-page, user-gated, cancellable — a mistranslated page costs one Play press, never an unattended reading session.

## Patron-facing help copy (for reading-room help pages)

> **Listen to this document.** Press *Play this page* to hear the shown page read aloud in your browser — no account, no download. Voices depend on your device and browser; Chrome, Edge, Firefox, and Safari all include free voices, and Edge's built-in Read aloud (`Ctrl+Shift+U`) works on any page including PDFs. Machine-read audio is a convenience copy: the record is always the document file, and translated audio is machine translation, not a citable source. For longer reading sessions, the free [Voice Reader](https://github.com/romkakn/voice-reader) browser extension reads any page offline with higher-quality voices.

## Verification (prototype exit bar)

- `node --check` clean; engine contract suite still green (`tests/reading_room_reader/test_engine_contract.py`).
- Manual matrix, one site B doc with `data-pages-url`: Chromium + Firefox + Safari — Play reads the shown page; page turn cancels; pause/resume; voice + rate change apply; keyboard-only operable; axe 0 new violations with panel open; DevTools shows no request beyond page + `pages.json`; page-1 load bytes unchanged.
- WP parity (site A + site B REST mounts) after the text-provider seam is exercised against a real route decision.
- **Live check, 2026-11-10, site A** (`/library/aclu-automated-police-reports-draft-one-policy/`, Playwright Chromium on macOS, real `speechSynthesis` with `speak` wrapped to log): at 375 and 1280 the panel renders after the reader; Play is 48px tall, the selects 46px; the default voice is `en-US`; Play sets `aria-pressed="true"` and announces "Reading page 1 of 6."; the first utterance is page 1's text from `pages.json`; `speechSynthesis.speaking` is true; Pause announces "Paused." and pauses; Stop announces "Stopped. Page 1 of 6 ready."; no horizontal scroll; no errors from the room (the one failed request is Cloudflare's injected analytics beacon). **Nobody has listened yet**, and Firefox, Safari and phones are unchecked.
- Fixed in engine 0.12.1 (2026-11-11): two shown pages read "Pages 1 and 2", in the engine's status and here.
- The voice list shows every voice the device has (about 170 on macOS, novelty voices included). Showing the page language's voices first is a candidate follow-up.

## Rollout

1. This prototype, static site B doc with `data-read-aloud` (local or `/rr-staging/` when it exists).
2. **roomkit ships it (2026-11-10).** With the pack's `features.read-aloud` on (site A and site B; site C and the default pack stay off), `build.py` copies `rr-read-aloud.js` from this directory into the room as `assets/rr-read-aloud.<hash>.js` (listed in `room.lock.json`), adds its `<script>` to record pages that have page texts, puts `data-read-aloud` on the reader mount (which already carries `data-pages-url`), and adds `templates/room/read-aloud.css` to room.css. The CSS restyles the panel from the room's tokens (the player's injected style is only a light-theme fallback). Gated records (`display.gate`) and snapshot records get no panel. With the switch off the output is byte-identical to before. Checked by `tests/roomkit/test_read_aloud_room.py`.
   Live on site-a.example/library/ since the 2026-11-10 republish (lock verified, 2333/2333 files). site B: built and tested, not republished yet.
3. Re-verify on staging; sync the file beside (not inside) the vendored engine on each WordPress plugin.
4. WP REST text decision, then provider implementation, then a parity release with viewing copies if convenient.
