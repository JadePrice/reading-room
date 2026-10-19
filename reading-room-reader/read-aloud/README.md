# rr-read-aloud.js — browser-only read-aloud pilot (TTS slice 1)

**Summary:** Site-side read-aloud panel for reading rooms. Follows `rr-reader:pagechange`, speaks the current page with the browser's own voices. No audio files, no network synthesis, no engine change.

## Why this shape

The 2026-10-08 translation decision binds TTS: no document text to any cloud API (no ElevenLabs/Google/Polly). `window.speechSynthesis` synthesizes on-device with client voices — zero egress, zero infra, zero storage. It is also the only synthesis with no model-license questions (contrast NLLB's CC-BY-NC-4.0). If client voices prove inadequate, slice 2 (local batch synthesis on mint, per-page audio on R2) gets its own decision; nothing here assumes it.

## What it is / isn't

- **Is:** one ES5 file, no build step (repo convention), opt-in per mount via `data-read-aloud`, panel rendered *outside* the reader mount (modules replace mount contents; the panel must survive re-renders).
- **Isn't:** not vendored (`sync.sh` copies only `src/` — this dir is invisible to it, to `MANIFEST.sha256`, and to driftkit `engines:`), not an engine module, no `data-features` token, no roomkit manifest change, no WP route, no table.

## Control contract

- Mounts only where the site opts in: `.rr-reader[data-file-url][data-read-aloud]` (back-compat `.ggrr-reader` too). No attribute, no panel, no behavior change.
- One panel per mount, inserted after the mount: Play/Pause toggle (current page), Stop, voice `<select>`, rate `<select>` (0.75/1/1.25/1.5), status line `role="status"`.
- Speaks the pages in the latest `rr-reader:pagechange` detail (`pages` = shown pages, 1–2 in spread). Page change cancels speech and resets the label — never reads a stale page.
- **No autoplay, ever.** Speech starts only on Play (which is also the user gesture some browsers require). `pages.json` is fetched lazily on first Play, once per document, `credentials: same-origin`.
- Reads to the end of the shown page(s), then stops with "Finished page N." Pause/Resume mid-page. Stop cancels everything.
- Mounts without `speechSynthesis` get a plain "Read-aloud isn't available in this browser." note and no controls — the reader and fallback links are untouched.

## Text sources (in order)

1. **Static mode:** the mount's `data-pages-url` (`{pages:[{n, text}]}` — the same feed the engine searches). Zero new endpoints.
2. **Provider override:** `RRReadAloud.setTextProvider(fn)` — `fn(container, [n…])` returns `Promise<string|{text,isMachine}|null>`. This is the seam a WP site uses later; `{text, isMachine}` is the translation-cache shape, announced as "Reading machine translation, page N".
3. **REST mode today:** unsupported on purpose. There is no public full-page-text route, and minting one is the same source-exposure decision as flipping `GET translate-page` public. The panel in REST mode says which page it *would* read and why it can't — honest, never fabricated.

## Voice policy

- Client voices only: `speechSynthesis.getVoices()` (+ `voiceschanged`). No voice is downloaded, fetched, or bundled.
- Default pick: mount `data-lang` (default `en`) matched against voice `lang` prefixes; ES-translated page text gets an ES voice when one exists, else the same voice reads ES text (voices vary by device — stated in the panel footnote).
- Rate and voice are per-listener choices, persisted nowhere (no cookies, no storage — nothing to clear).
- Panel footnote, always visible: "Machine-read aloud in your browser — voices vary by device. The record is the document file, not this audio."

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

Machine translation and read-aloud are separate derivations of the same page text, combined only at listen time:

1. **Translation stays server-side and cached.** The OPUS-MT pilot on mint fills `wp_ggrr_page_translations` keyed `(document_id, page_number, page_sha256, language)` with `is_machine=1`; the browser never calls a model and no page text ever leaves the device for synthesis. The no-cloud rule binds both halves.
2. **The provider seam carries translated text.** A WP site serves the cached ES translation through `RRReadAloud.setTextProvider(fn)` — the same seam as source text, no new contract. (Mirrors IA BookReader reading from its `.BRtranslateLayer` when translation is active.)
3. **Voice follows language.** `pickVoice` matches the mount `data-lang` (or the provider's language) against voice `lang` prefixes, so cached ES text gets an ES voice when one exists, else the same voice reads ES text (stated in the footnote). Voice preference is unit-tested (`test_es_voice_pick_prefers_spanish`).
4. **Spoken translation is labeled twice.** The panel footnote already says machine-read; when the provider serves `is_machine` text the status line announces "Reading machine translation, page N" — spoken output is never citable, matching the translation policy (MT never authoritative, source excerpt alongside).
5. **No whole-document TTS+MT playlists in slice 1.** Per-page, user-gated, cancellable — a mistranslated page costs one Play press, never an unattended reading session.

## Patron-facing help copy (for reading-room help pages)

> **Listen to this document.** Press *Play this page* to hear the shown page read aloud in your browser — no account, no download. Voices depend on your device and browser; Chrome, Edge, Firefox, and Safari all include free voices, and Edge's built-in Read aloud (`Ctrl+Shift+U`) works on any page including PDFs. Machine-read audio is a convenience copy: the record is always the document file, and translated audio is machine translation, not a citable source. For longer reading sessions, the free [Voice Reader](https://github.com/romkakn/voice-reader) browser extension reads any page offline with higher-quality voices.

## Verification (prototype exit bar)

- `node --check` clean; engine contract suite still green (`tests/reading_room_reader/test_engine_contract.py`).
- Manual matrix, one dd doc with `data-pages-url`: Chromium + Firefox + Safari — Play reads the shown page; page turn cancels; pause/resume; voice + rate change apply; keyboard-only operable; axe 0 new violations with panel open; DevTools shows no request beyond page + `pages.json`; page-1 load bytes unchanged.
- WP parity (GG + dd REST mounts) after the text-provider seam is exercised against a real route decision.

## Rollout

1. This prototype, static dd doc with `data-read-aloud` (local or `/rr-staging/` when it exists).
2. Re-verify on staging; sync the file beside (not inside) the vendored engine on each plugin.
3. WP REST text decision → provider implementation → parity release with viewing copies if convenient.
