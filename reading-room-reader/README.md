# reading-room-reader

Canonical, vendored document reader engine (PDF, image, text) shared by glassgovernment.org (`gg-reading-room`) and deflockdane.org (`deflock-reading-room`). Single source of truth for the reader; each site keeps its own data layer, collections, branding, and REST.

Design spec: [`../docs/superpowers/specs/2026-06-25-unified-reading-room-reader-design.md`](../docs/superpowers/specs/2026-06-25-unified-reading-room-reader-design.md).

Porting features between the two consumers (GG = upstream, dd = downstream): [`PORTING.md`](PORTING.md) — symbol/route map, Yoast-hook checklist, and the shared-vs-per-fork split.

## Layout

```
src/rr-reader.js                 registry/loader — window.RRReader; mounts .rr-reader[data-file-url]; fallback restore, copy helper, events
src/modules/rr-reader-pdf.js     pdf viewer — single + two-page spread, page-aware search, text layer, cite panel, lightbox/fullscreen
src/modules/rr-reader-image.js   image viewer — jpg/png/gif/webp/svg, alt from data-title, fullscreen button
src/modules/rr-reader-table.js   table viewer — csv/tsv interactive grid with column sorting, filtering, pagination, and cell/row citation
src/modules/rr-reader-text.js    text viewer — txt/md/json/xml/html shown verbatim (never rendered), 1 MB cap
src/modules/rr-cite.js           copy-citation control — self-wires [data-rr-cite-copy] (and legacy [data-ggrr-cite-copy]) buttons
vendor/pdfjs/                    pinned pdf.js 3.11.174 (pdf.min.js + worker); sync.sh ships it
sync.sh                          copy src/ + pdf.js into a plugin's assets/vendor/, write MANIFEST.sha256
VERSION                          semver, bump on change (must match VERSION in rr-reader.js; tested)
PORTING.md                       GG ↔ dd feature-port map
contract/*.schema.json           doc-search and passage (site REST responses), pages (roomkit's pages.json); tests/reading_room_reader/test_contract.py
```

Tests: `tests/reading_room_reader/` at the repo root. `test_engine_contract.py` runs anywhere; `test_reader_browser.py` drives the engine in Playwright Chromium against a generated local site (skips if Chromium is not installed).

No build step: hand-written ES5, served raw (both sites run `js_min` off).

## How a site consumes it

1. `./sync.sh /path/to/<plugin>/assets` → writes `assets/vendor/rr-reader/` (loader, every module, `VERSION`, `MANIFEST.sha256`) and `assets/vendor/pdfjs/`.
2. Enqueue the loader, then the modules the site needs (each depends on the loader handle; the pdf module also on pdf.js); cache-bust with `?ver=filemtime`.
3. Localize site-wide config onto the loader handle as `window.rrReaderConfig`:
   `{ pdfJsUrl, pdfWorkerUrl, docSearchUrl, passageUrl, slowLoadMs, messages:{loading,rendering,loadFailed,unsupported,slowLoad,textTooLarge,openFile} }`.
   `docSearchUrl` turns on in-document search; `passageUrl` turns on citations (Cite page, per-hit Cite, Copy quote). Leave either empty if the site has no such route.
4. Emit one mount container per document, with the fallback block inside it:
   ```html
   <div class="rr-reader" data-file-url="…" data-ext="pdf" data-mime="application/pdf"
        data-slug="…" data-title="…" data-features="spread,search"
        data-poster="…/page-1.jpg">                  <!-- optional: server-rendered page 1 -->
     <p class="rr-reader__status" data-reader-status role="status" aria-live="polite">Loading the reader.</p>
     <div data-reader-fallback>
       <a href="…/file/">Open the PDF (38 MB, 212 pages)</a>
       <a href="…/text/">Read the text</a>          <!-- where the site has a text view -->
       <a href="…/file/?download=1">Download</a>
       <noscript>
         <object data="…/file/#page=1" type="application/pdf" width="100%" height="800">
           <p>This browser cannot show the PDF here. Use the links above.</p>
         </object>
       </noscript>
     </div>
   </div>
   ```
5. Map the site palette onto the engine tokens with a `.rr-reader{ … }` bridge. The engine self-injects its full stylesheet with light (GG) fallbacks, so it works unbridged — but a dark-themed consumer **must** bridge or the chrome renders light. Nine tokens: `--rr-paper` (reader/lightbox bg), `--rr-paper-raised` (stage + inputs), `--rr-ink` (button bg + input text), `--rr-ink-soft` (status/pageinfo — keep ≥ 4.5:1 on `--rr-paper`), `--rr-ink-faint` (decorative), `--rr-rule` (borders), `--rr-accent` (button hover / pressed), `--rr-focus` (focus ring — keep ≥ 3:1), `--rr-mono`. Optional: `--rr-mark` / `--rr-mark-ink` (search-hit highlight, opaque yellow with dark ink by default; keep the pair ≥ 4.5:1). See `deflock-reading-room.css` for a worked dark bridge.

The engine's input rules are scoped `.rr-reader input.rr-reader__*` (specificity 0,0,2,1) specifically to win over host-theme input resets such as Astra's `input[type="search"|"text"]{background:…}` (0,0,1,1). If a consumer theme still overrides reader chrome, raise the bridge selector's specificity rather than reaching for `!important`.

## Static mode (no search route)

A site without a search route, such as a static reading room built by `scripts/roomkit`, puts `data-pages-url` on the container. It points to the document's page texts, `{"pages": [{"n": 1, "text": "..."}, ...]}`. The engine fetches that file once, on the first search, and searches it in the browser with `RRReader.searchPages(pages, query, limit)`. It returns the same `[{page_number, snippet}]` the routes return, so the search UI is unchanged.

- **Precedence:** `data-pages-url` wins over `docSearchUrl`, because it is set per document.
- **Matching** is deflockdane's `doc-search` route:
  - every query word of 3+ characters (at most 8) must start a word on the page;
  - if no page has them all, the whole query is matched as plain text;
  - results come in page order, at most 50.
- **Snippet:** whitespace collapsed, 90 characters either side of the first word found.
- **Verified 2026-10-08** against the live route on 70 real dd cases (10 documents, 7 queries): page lists and snippets identical, 70/70.
- **Span:** each hit also carries `offset_start`/`offset_end` in the page's own text, as GG's route gives them (`GGRR_Search::locate`): the earliest case-insensitive occurrence of any lowercase `[a-z0-9]` term of 3+ characters, as long as that term, counted in code points as PHP's `mb_*` functions count; `null` when no term occurs. Per-hit "Cite" sends that span to the passage route.
- **Citations** need `passageUrl`; without it there is no Cite button and the page's own citation text is what readers cite. With it (0.7.0+), a page entry may carry `cite`, the site's page-scoped citation `{reference, provenance_level, ocr_confidence}` (what the passage route answers for that page):
  - "Cite page" shows it at once, with no request;
  - per-hit "Cite" still asks the route (an 8 s timeout). When that fails for any reason (offline, blocked origin, an error status, `found: false`, the timeout), the panel shows that page's `cite` with the note "The exact passage could not be resolved here; this cites the page.", and no quote or key. Without a `cite`, the old "could not be resolved" message stands.

## Large files

pdf.js 3.x already loads PDFs by byte range when the server answers `Range` (both sites do). What it cannot skip: before page 1 it reads every page's entry in the file, and in an ordinary PDF those entries sit beside each page's content. On deflockdane.org's 36-page, 1.8 MB contract that is 26 of 28 64 KB chunks, so most of the file arrives before anything draws, whatever options the reader passes (measured 2026-10-07; turning off streaming and auto-fetch changed nothing, and was not kept).

So the engine offers a **poster**: `data-poster` names an image of page 1 that the site already renders (deflockdane.org uses WordPress's PDF preview, `…/thumb/?size=large`). It shows at once, with alt text naming the document, and gives way to the real page when that has drawn. Not used for a `#page-N` deep link. A poster that fails to load is dropped silently. Serve file URLs that name their bytes (`?v=<sha256 prefix>`) with a long private cache, so the reader's range requests are paid once per reader.

## Fallback contract

The reader is progressive enhancement over a page that already works. The rule: **the reader may only add to the page; every failure ends in a status line plus working links, never a blank box.**

- **No JS, or the script never arrives:** people get the `[data-reader-fallback]` block as rendered. So it must be real links, not a "Preparing…" line. The `<object>` embed sits in `<noscript>` so JS users never download a large PDF twice; its inner content is what browsers that cannot show PDFs inline (Android Chrome, some iOS) display. Do not use a bare `<iframe>`: it shows a blank box on those browsers and gives screen readers nothing.
- **JS on, reader fails after mounting** (pdf.js missing, corrupt or unreachable file, broken image, text over 1 MB): the loader kept a copy of the fallback block at mount and `RRReader.fail()` puts it back under the status message. A site with no fallback block gets a plain "Open the file" link instead.
- **Slow load:** after 20 s without a parsed PDF the fallback links appear while loading continues; if the PDF arrives, the reader takes over.
- Everything outside the mount (metadata, citation text, open/download buttons) is the site's and is never touched.

## Features and events

`data-features` is a token list (`spread`, `search`, `lightbox`, `fullscreen`, `no-cite`). Search needs `docSearchUrl` or the container's `data-pages-url`. Absent means `spread` + `search` on, `lightbox` + `fullscreen` off. Citations follow `passageUrl`, not the list (templates predating the token keep them); `no-cite` opts out.

The loader dispatches bubbling DOM events on the mount: `rr-reader:ready` (`{total}`) and `rr-reader:pagechange` (`{pages, total, slug}`). Site code can follow the reader without touching the engine; this is the hook for per-page panels (machine translation, read-aloud).

## pdf.js pin

pdf.js is pinned at **3.11.174** in `vendor/pdfjs/`. The text layer uses `pdfjsLib.renderTextLayer`, which pdf.js 4 removed; under a different major the pages still render but the mount gets `data-text-layer="unavailable"` (selection and in-page highlight are gone, server search still works). Upgrading pdf.js is an engine change with its own test run, never a drop-in.

The vendored files are upstream's, byte for byte: `pdfjs-dist@3.11.174` `build/`, compared with the jsDelivr copy on 2026-10-21. `tests/reading_room_reader/test_engine_contract.py` fails if either changes without this table changing with it.

| File | sha256 |
|---|---|
| `pdf.min.js` | `5b5799e6f8c680663207ac5b42ee14eed2a406fa7af48f50c154f0c0b1566946` |
| `pdf.worker.min.js` | `feabdf309770ed24bba31a5467836cdc8cf639c705af27d52b585b041bb8527b` |

## Back-compat

The loader also matches `.ggrr-reader[data-file-url]`, reads `window.ggrrReaderConfig` as a fallback, and aliases `window.GGRRReader = RRReader`; `rr-cite.js` also wires `[data-ggrr-cite-copy]`. So glassgovernment.org's current template works against the vendored engine unchanged. Aliases are removed once both sites emit `.rr-reader`.

## Features

Single + two-page book spread (cover-alone parity, shared-height leaves, opt-in toggle, mobile-forced-single < 760px), page-aware in-document search + `#page-N` deep-link + selectable/highlighted text layer, zoom, keyboard nav, plus opt-in lightbox + fullscreen. Each capability is gated by the container's `data-features` attribute (`spread`, `search`, `lightbox`, `fullscreen`); `spread` and `search` default on, `lightbox` and `fullscreen` default off.

## Accessibility

Verified WCAG 2.2 AA on both consumers (light GG + dark dd), desktop and 375px mobile:

- **Contrast** — toolbar text/icons, status line, page total and page/search inputs clear 4.5:1 against their own surface in both palettes (text uses `--rr-ink-soft`, never the faint token). Control borders (page input, search input, Cite buttons) use `--rr-control-border`, defaulting to `--rr-ink-soft`, so they clear the 3:1 non-text minimum (the 2026-09-27 audit measured the old `--rr-rule` borders at 1.49:1). A dark bridge must keep `--rr-ink-soft` light enough to pass.
- **Touch targets** — every button and input is ≥ 44×44 (base button has `min-width:44px` so single-glyph match-nav buttons qualify).
- **Keyboard** — stage is focusable (`role="document"`); Arrow/PageUp/PageDown page, `+`/`-` zoom, Enter in search jumps to next match, Esc closes the lightbox.
- **Lightbox** — opens as `role="dialog"` `aria-modal="true"`, moves focus into the stage, traps Tab / Shift+Tab within the reader's controls while open, and returns focus to the trigger on close.
- **Reduced motion / reflow** — button transitions, the image module's zoom and box transitions and its transcript scroll drop under `prefers-reduced-motion` (`test_engine_contract.py` holds every module that moves to it); toolbar wraps and spread forces single below 760px with no horizontal scroll.

**Re-verify per release:** `tests/reading_room_reader/test_reader_browser.py` runs axe (WCAG 2.0–2.2 A/AA) over the mounted reader with search results and the cite panel open, checks every visible control is ≥ 44×44, and drives keyboard paging and the lightbox focus trap. The claims above hold for the engine's own palette; each site's bridge still needs a live audit.

## Releasing the engine

1. Change `src/`, then bump `VERSION` and `var VERSION` in `src/rr-reader.js` together (`test_engine_contract.py` checks they match).
2. Run `PYTHONPATH=. pytest tests/reading_room_reader tests/roomkit -q` from the repo root (browser tests need Playwright Chromium).
3. Re-vendor into each site with `./sync.sh <plugin>/assets`, which writes `MANIFEST.sha256`; driftkit then reports the site copy against this engine. Deploying the plugin is the site's own release.
4. Re-vendoring pdf.js: replace both files in `vendor/pdfjs/` with the upstream `pdfjs-dist` build, compare them with the published package, update the table under "pdf.js pin", and run the tests. A different major needs the text-layer work described there.

The roomkit room ships `src/` and `vendor/pdfjs/` as they are in this repo, under fingerprinted names; a rebuild picks up a change with no sync step.

## Provenance

Lifted verbatim (behavior-identical) from gg-reading-room's `ggrr-reader.js` + `ggrr-reader-pdf.js`, neutral-namespaced (engine v0.1.0). v0.2.0 folds in the dd reader's lightbox + fullscreen behind `data-features` flags. v0.2.1–0.2.2 add the a11y/mobile polish above (tokenized search input, AA status contrast, 44px targets, lightbox dialog semantics, input specificity over theme resets). v0.2.3 traps focus inside the open lightbox. v0.3.0 adds `rr-cite.js`.

v0.4.0 (2026-10-07) reunifies the engine after glassgovernment.org forked it on 2026-06-28 (an in-place edit of the vendored copy on gg-core; GG has since run its own `assets/js/ggrr-reader*.js`). It takes from the GG fork the image and text modules and the passage-backed citation panel (Cite page, per-hit Cite, Copy quote), and keeps the dd lineage's lightbox, fullscreen and 44px inputs. Also: the fallback contract and restore-on-fail, search snippets highlighted as text nodes (0.3.0 escaped then highlighted, so a query of "amp" broke `&amp;`), copy with an execCommand fallback that announces failure, 3:1 control borders, the pinned pdf.js shipped by `sync.sh`, `MANIFEST.sha256`, lifecycle events, and the first tests.

Do not edit the vendored copies in a plugin; edit here and re-sync. The 06-28 fork is what happens otherwise; driftkit compares each site repo's vendored copy with this engine (`engines:` in `scripts/driftkit/surfaces.yaml`; `engine-behind` / `engine-forked`), and its files check holds the served copy to the site repo. A document-page probe on each site checks the no-JS contract.

v0.4.1 (2026-10-07), from the first live check of 0.4.0 on deflockdane.org: search-hit marks are opaque with their own ink (the translucent 0.4.0 mark inherited dd's light text and failed contrast; the axe test now runs a dark bridge too), and when a slow PDF arrives after the fallback links were restored, the reader removes them and clears `data-reader-failed`. `slowLoadMs` (default 20000) sets when those links appear.

v0.5.0 (2026-10-07): `data-poster`, a server-rendered page-1 image shown while pdf.js loads (see Large files).

v0.7.0 (2026-10-15): static search hits carry the hit's span (GG `locate` semantics) so per-hit Cite works in static mode; a page's `cite` in pages.json serves "Cite page" with no request and is the fallback when the passage route fails or times out (8 s). Sites on 0.6.0 lose nothing: without `cite` and without static mode the panel behaves as before. For roomkit's passage citations (plan Task 12).

v0.8.0 (2026-10-21): the image module shows multi-page scans with page images and OCR boxes from pages.json (a transcript pane beside the image, box and token linked); `rr-reader-table.js` shows CSV/TSV as a sortable, filterable, paged grid with row and cell citations and a 5 MB cap; pdf.js opens with `isEvalSupported: false` (CVE-2024-4367); the image module's motion stops under `prefers-reduced-motion`; a table that fails to load removes its controls before the fallback links; the text module stops reading at its 1 MB cap as the file streams in (from the standalone repo), so a response with no content-length is capped too. Sites on 0.7.0 lose nothing by staying; re-sync to get the security fix.

v0.6.0 (2026-10-08): static mode. `data-pages-url` and `RRReader.searchPages` give in-document search without a route (see Static mode). A slow search answer can no longer overwrite a newer one. Sites on 0.5.0 lose nothing by staying there; no re-sync is needed unless a site wants static search.

2026-10-07: glassgovernment.org runs the engine again (GGRR 0.8.0, release 20261007_221512), vendored by `sync.sh` into `gg-reading-room/assets/vendor/rr-reader/`. GG keeps its own look by scoping its button and stage rules under `.ggrr-rr`, because the engine's stylesheet loads last and wins a tie between single classes. Both sites now vendor the same engine, and driftkit reports no drift for either. The fork's `assets/js/ggrr-reader*.js` stays for one release, unreferenced, for pages the edge still holds.
