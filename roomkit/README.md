# roomkit

A reading room as static files, built from a site's manifest of its public documents.

A document page today is a PHP template in front of the database, cached at the edge for 3 hours and purged by hand. roomkit renders the same page from a manifest into plain files: the shared reader mount, its no-JS fallback, the site's own citation text, the original's sha256, and a `pages.json` of page texts. The plan it serves, with the order of work and the open decisions: `conductor/plans/2026-10-08-static-reading-room.md`.

**WordPress stays the system of record.** roomkit reads a manifest exported from it and writes only its output directory. It has no publish step: publishing is a separate, human decision.

## Commands

```bash
PY=python3
$PY -m roomkit.cli build  --manifest M.json --out DIR [--json]   # validate, then write the room
$PY -m roomkit.cli check  --manifest M.json --out DIR [--json]   # rebuild in memory, compare; changes nothing
$PY -m roomkit.cli status --manifest M.json --out DIR --json     # unbuilt | stale | current | refused, and the next command
```

```bash
$PY -m roomkit.cli parity --manifest M.json [--pages PAGES.tsv]   # live pages vs the manifest; read-only
$PY -m roomkit.cli parity --matrix roomkit/parity-matrix.yaml [--site S] [--json]  # the gap to cutover
$PY -m roomkit.cli status --matrix roomkit/parity-matrix.yaml --json                # the next row that blocks
$PY -m roomkit.cli parity --entities LIVE.json --out ROOM [--json]       # parity.entities (below, "Entities")
$PY -m roomkit.cli parity --entities-from PAGES.tsv --site S > LIVE.json  # the live file, from fetched pages
$PY -m roomkit.cli parity --passages-fetch --out ROOM --sample 10 [--keys KEYS.txt] > LIVE.json  # paced GETs (GG)
$PY -m roomkit.cli parity --passages LIVE.json --out ROOM [--json]       # parity.passages (below, "Passage citations")
$PY -m roomkit.cli parity --facets-from INDEX.html --site deflockdane > LIVE.json  # live facets, from the live index
$PY -m roomkit.cli parity --facet-pages LIVE.json --out ROOM [--json]    # parity.facet_pages (below, "Facet pages and the sitemap")
$PY -m roomkit.cli parity --sitemaps PROVIDER.xml... --out ROOM [--json] # parity.sitemaps
$PY -m roomkit.cli parity --thumbs LIVE.tsv --out ROOM [--json]          # parity.thumbnails (below, "Card thumbnails")
$PY -m roomkit.cli parity --search LIVE.json --out ROOM [--top N] [--json]  # parity.search (below, "Corpus search")
$PY -m roomkit.cli diff --old OLD/room.lock.json --new NEW/room.lock.json [--json]  # purge + remove lists
$PY -m roomkit.cli vendor write --to path/to/civica/app/room       # copy the core into Civica, pinned
$PY -m roomkit.cli pack import --map roomkit/packs/<site>/tokens.map.json [--write]  # pack tokens from design-tokens
$PY -m roomkit.cli vendor check --to path/to/civica/app/room [--json]  # its drift; changes nothing
```

`build`, `check` and `status` take `--site-pack packs/<site>/` (the site pack, below). Without it, the manifest's site's pack (`site.template`), else `packs/default/`.

Exit codes: 0 ok, 1 refused rows (build), a difference (check, parity) or a blocking matrix row (parity --matrix), 2 the manifest cannot be read at all or the matrix is refused.

## The parity matrix

`parity-matrix.yaml` is the written definition of "ready to replace the WordPress room" (`wiki/reading-room-parity.md`). `parity --matrix` reads it and prints every row grouped by status (done, partial, missing) per site, with the rows that block cutover starred. A row blocks a site when its disposition is `static` or `dynamic-api`, its need there is `required`, and it is not `done`. `--site` restricts the report and the exit code to one site. `status --matrix` (with or without `--manifest`/`--out`) names the next blocking row in matrix order and the command to see the rest; with a manifest it sits under `parity` beside the room's own state.

**Refused (exit 2), every problem listed:** an unknown key at the top or in a row or site entry, a missing field, an unknown surface, disposition, site, need or status, a row without an entry for each site, a `check` that is neither `browser` nor `parity.<name>`, a duplicate id, and a `signoff` on a row that is not `dropped`.

**Sign-off on `dropped` rows.** `signoff: null`, or no `signoff` at all, means the row is awaiting the user. It is reported as "awaiting sign-off" and blocks every site until it is signed. `signoff: ""` (or any non-text value) is refused as malformed: an empty sign-off is not a decision. A signed `dropped` row does not block.

## The core, and Civica

The reading room is meant to become the Civica reading room, so the part that renders it is a **core** with nothing roomkit-only in it. Each module has one job, and the core imports only itself (relatively), the standard library, Jinja and jsonschema:

| Module | Job | Depends on |
|---|---|---|
| `manifest.py` | the manifest's shape and its refusals | entities, passages |
| `entities.py` | the manifest's `entities` block, its refusals and paths; the pack switch (`gate`) | (leaf) |
| `passages.py` | GG's `passages` block, page citations and curated citations, their refusals; the pack switch (`gate`) | (leaf) |
| `color.py` | parse hex/oklch(), composite, WCAG contrast | (leaf) |
| `css.py` | the site pack's tokens as CSS; the `#room-content` scoping rule | (leaf) |
| `view.py` | manifest + pack -> the plain view-model dicts | manifest |
| `room.py` | the Jinja environment and a thin render call | view, manifest |
| `pack.py` | load and check a site pack, one function per check | color, css |
| `search.py` | corpus search: what Pagefind indexes, the pinned indexer, the pack switch | manifest |
| `browse.py` | facet pages and the sitemap: which pages, their records, the pack switches | entities, view |
| `templates/room/`, `packs/pack.schema.json` | the markup; the pack's structure | |

Around it, the roomkit-only parts: `build.py` (the static tree, fingerprints, lock), `cli.py`, `parity.py`, `search_parity.py`, `entity_parity.py`, `passage_parity.py`, `browse_parity.py`, `thumb_parity.py`, `vendor.py`, and the pack importer: `tokens_css.py` (read a design-tokens file: top-level `:root`, `var()` resolved, duplicates and variants named) and `pack_import.py` (map -> pack tokens, each non-site value with its why).

**Civica carries a verbatim copy, pinned** (decided 2026-10-13: vendored copy plus a drift check). `vendor write` copies the core into a package directory and records `VENDORED.json` (source commit, sha256 per file); it refuses while a core file has uncommitted changes. `vendor check` is read-only and names files `modified` in the copy (fix upstream, never in the copy), `missing`, or `behind` the source; exit 1 on any. Files in the destination outside the core (a tenant's pack) are left alone. A test imports a copy under another package name and holds it to the same bytes as roomkit (`tests/roomkit/test_vendor.py`).

Civica must render the room through the copy's own `room.ENV`, not its `Jinja2Templates`: that environment has no `StrictUndefined`, escapes with markupsafe and adds its own filters, so pages would drift from roomkit's.

The vendored copy lives on Civica branch `room-spike`, not on `main` (as of 2026-10-17). On `/admin/kits`, roomkit is listed under "no standing census": it builds from a manifest exported per run and has no state between builds (`scripts/ops/kitboard.py`).

## Exporters (read-only, run against the site)

One exporter per site, each a `wp eval-file` script on stdin, so nothing is copied to the host. Both write the same manifest schema (`manifest.py` docstring): the site's helpers do the formatting, roomkit formats nothing.

**glassgovernment.org** (`exporters/glassgovernment.php`), through the operator's `wp-prod` wrapper, the route `scripts/wiki/corpus_manifest.py` already uses. `sudo` passes no environment, so flags go in as constants on a one-line PHP block in front of the script:

```bash
{ echo "<?php define('ROOMKIT_ALLOW_EXCLUDED', true); ?>"; cat roomkit/exporters/glassgovernment.php; } \
  | ssh gg-core 'sudo -n /usr/local/bin/wp-prod eval-file -' > gg-manifest.json
```

With `search_text` the full export is slow (84 MB on 2026-10-14). To run it in pieces, add `define('ROOMKIT_SLICE', '0:100');` (then `100:100`, and so on) to the same PHP block. Each piece carries a `slice` key, and `python roomkit/exporters/merge-slices.py gg-manifest.json piece-*.json` joins them. It refuses a gap, an overlap, a short piece or pieces from different exports, and writes nothing when it refuses.

The citation is `GGRR_Citations::format_reference`, the badge and rights line come from `GGRR_Template`, entities from `GGRR_Entities::for_doc` under the template's two headings ("Attributed to", "Named in this document"). On 2026-10-12: 390 documents (295 with page text), 65 excluded as "no servable file". Those are the text-only CFR records, which have full text but no PDF; the static room has no text-only page yet.

**deflockdane.org** (`exporters/deflockdane.php`):

```bash
ssh gg-shared 'ROOMKIT_ALLOW_EXCLUDED=1 ~/bin/wp --path=$HOME/domains/deflockdane.org/public_html eval-file -' \
  < roomkit/exporters/deflockdane.php > dd-manifest.json
```

- **URLs** come from the plugin's own helpers. That includes the verified viewing copy as `file.view_url`, checked the way the plugin checks it but without the transient the plugin writes.
- **The citation** is the template's formula, repeated, because dd builds it inline in `single-reading-room.php`. `parity` is what keeps that safe.
- **Every public file is hashed against `file_sha256`.** A missing or mismatched file makes the exporter refuse. With `ROOMKIT_ALLOW_EXCLUDED=1`, the record goes into the manifest's `excluded` list instead, and every roomkit command names it.
- **Page text is exported** (`ROOMKIT_WITH_PAGES=0` leaves it out). The static pages search it in the browser. dd's plugin keeps OCR text server-side, and shipping it was decided on 2026-10-08 (plan D6).

**Parity on dd goes through the origin.** Cloudflare rate-limits deflockdane.org and answered 429 within a few dozen paced requests. `exporters/deflockdane-fetch-pages.sh` runs on the host and fetches each page from the host's own public address, skipping Cloudflare. It writes nothing on the host and streams the pages back:

```bash
ssh gg-shared bash -s -- $(jq -r '.documents[].slug' dd-manifest.json) \
  < roomkit/exporters/deflockdane-fetch-pages.sh > dd-pages.tsv
$PY -m roomkit.cli parity --manifest dd-manifest.json --pages dd-pages.tsv
```

## What a build writes

```
index.html                   the list of documents
404.html                     what a missing path gets, so a miss never reaches WordPress
entities/index.html          GG's entity index        } pack features.entities and the
entity/<type>/<slug>/index.html  one page per entity  } manifest's `entities` block
<slug>/index.html            one page per document
<facet>/<value>/index.html   one page per facet value } pack features.facet-pages and the
                                                      } manifest's site.index.browse
sitemap.xml                  every served page by its live URL (pack features.sitemaps)
<slug>/pages.<hash>.json     page texts, when the manifest carries them (and each page's citation,
                             with pack features.passage-cite)
citations.json               GG's curated citations by stable_key (features.passage-cite)
assets/room.<hash>.css       the shared template's styles, the room's chrome, the site pack's tokens
assets/room.<hash>.js        the index finder and the light/dark toggle
assets/room-search.<hash>.js the corpus-search finder and suggestions (features.corpus-search)
assets/thumbs/<slug>.<hash>.<ext>  card thumbnails the manifest carries (index.thumb)
pagefind/                    the Pagefind index (features.corpus-search)
assets/rr-config.<hash>.js   window.rrReaderConfig
assets/vendor/rr-reader/     reading-room-reader/src, verbatim (fingerprinted names)
assets/vendor/pdfjs/         pdf.js as the engine pins it (fingerprinted names)
.htaccess                    cache headers and the 404 page (Apache/LiteSpeed)
room.lock.json               sha256 of every served file, logical -> published asset names,
                             roomkit/engine versions, the pack's hash
```

## The site's chrome: superseded capture (D7)

Until 2026-10-14 the room wore each site's own WordPress header, menus, footer and theme CSS, captured from one live page and cut to an allowlist (`roomkit shell make`, plan D7). That is retired: **D7 is superseded, because a standalone room cannot depend on WordPress output.** The room now draws its own chrome from the site pack (below, "The room's own chrome"). It was retired in the Task 5 Steps 3-4 commit, after the design review of 7ee4aed. `shell.py`, its CLI verbs, `--shell`, `exporters/deflockdane-fetch.sh` and the shell-built goldens are gone; git history has them.

## One template, a pack per site

Both sites run the same reading room with different looks and content, so there is **one page template** (`templates/room/`) and a **site pack per site** (`packs/<site>/pack.json`: tokens, labels, layout, features, chrome; [packs/README.md](packs/README.md)). It is the union of the two WordPress plugins' templates, taking the better part of each:

| From GG | From dd |
|---|---|
| breadcrumbs, a provenance rail beside the reader | jump links on the page |
| a sensitivity notice (`display.notice`) | index grouped into sections that work without JavaScript |
| entity lists that say what kind of claim each is (chips with kind and quote) | cards with a page-one thumbnail (`layout: cards`) |
| related records, power maps (`display.groups`) | empty groups said out loud (`show_empty_groups`) |
| light/dark toggle sharing the WordPress room's saved choice (`toggle: "ggrr-theme"`) | |
| an index with counts and facets | |

The finder filters the cards already on the page (title, summary, agency, group, date, facets) and keeps its state in the URL (`?q=&year=`), so a filtered view can be linked. Without JavaScript it stays hidden and the grouped list is the way in. A long jump list (more than 12 groups) folds into a `<details>`.

### Corpus search (Pagefind)

A pack's `features.corpus-search` (off unless the pack turns it on; `labels.fulltext_placeholder` is the box's placeholder) adds a [Pagefind](https://pagefind.app) index and swaps the finder's script for `room-search.js` (`search.py`, `templates/room/room-search.js`, `search.css`).

- **Indexed:** title, summary, citation, agency, group, the public notes the record page shows (`display.notes`) and every page's OCR text from `pages.json`, or, for a record with no usable pages, its `search_text`. That is GG's `full_text` (what the live search reads), exported for a record whose page rows are not a complete 1..N run, most often a large scan OCR'd as one row with no page number. It is indexed and never shown: no `pages.json`, no in-document search, and a hit links to the record, not to a page. The group and each facet are Pagefind filters, the date is a sort; none of them add words. The record pages Pagefind reads are built in memory by `search.record_html` and never served.
- **Shipped:** the index under `pagefind/` (the loader, worker, wasm, shards, fragments, filters; Pagefind's own UI bundles are dropped). No network at page view: the finder loads `pagefind/pagefind.js` from the room's own mount. The room sets no CSP; a site that adds one needs `'wasm-unsafe-eval'` in `script-src` for Pagefind's wasm (QW1).
- **Pinned:** `pagefind[bin]==1.5.2` in `requirements-dev.txt` (the PyPI wrapper with its bundled binary: `uv pip install --python ~/.venvs/llm-wiki/bin/python 'pagefind[bin]==1.5.2'`). A build with the switch on and another version, or none, is refused with that command.
- **Not byte-reproducible.** Pagefind writes each filter's values in a random order, so `filter/*`, `pagefind.*.pf_meta` and the hashes in their names change between runs of the same input (fragments and index shards do not). So `room.lock.json` records `search.input` (a hash of every indexed field) and the version; `check` calls the index current when both match and the shipped `pagefind/` files are the ones the on-disk lock lists. The goldens run a stand-in indexer that writes the HTML Pagefind would read.
- **Finder.** Text goes to the index; the facet selects narrow text results too (and the cards when the box is empty). Results link to the record, and to `#page-N` for PDF records (the reader opens `#page-N`). The query stays in the URL. Pagefind stems words, so `zephy` finds nothing and `zephyr` finds `zephyrine`. Without JavaScript the finder stays hidden and the static list stands.
- **Suggestions.** A WAI-ARIA combobox over a grouped listbox (arrow keys, Enter, Escape; `aria-activedescendant`; the result count is `aria-live`). Without a site panel, the groups are: top matches, one per facet the room holds (agency/category, year, and others the manifest carries), recent documents, recent searches (localStorage).
- **The site's own panel.** When the manifest carries `site.index.suggest` (`manifest.py` documents it), the index embeds it as inert JSON (`<script type="application/json" data-room-suggest>`, every `<` escaped) and `room-search.js` draws that panel instead: the site's labels, its recent documents in its order, then each group's items (`empty` of them on an empty box, the `typing` first that hold the text otherwise), with top matches (`top` of them, from Pagefind) first while typing. A chip fills the box with its query. dd's exporter writes live's panel from the shortcode's archive payload (Try searching, Agencies, Surveillance vendors, Document types, Years, with live's limits). With the block's optional `rank` rows (what dd's `prepareDoc` reads per record, from the same payload), top matches are dd's own `scoreDoc` ported into `room-search.js` (title, agency, type, alias, summary and year matches with live's weights and its recency bonus) rather than Pagefind relevance; 14 probe inputs gave every group, item and top-match order equal to live. Live's "See all results for" row is not drawn.
- **parity.search.** `roomkit parity --search LIVE.json --out ROOM [--top N] [--json]` runs the room's own `pagefind.js` in Chromium and checks that every live hit is in the room's top N (default 100; `--top`). `LIVE.json` is `{"site", "fetched", "source", "notes"?, "queries": {"<query>": ["<slug or record URL>", ...]}}`; a hit's last path segment is its slug. A live hit the room does not hold is reported as `not_in_room`, not a miss. GG's set is `search-queries/glassgovernment-2026-10-14.json`. dd's live results come through the origin: `ssh gg-shared bash -s -- $(jq -r '.queries | keys_unsorted[] | @base64' OLD.json) < roomkit/exporters/deflockdane-fetch-search.sh > LIVE.json` (`search-queries/deflockdane-2026-10-20.json`, 98.5%; the misses are live ignoring words under 3 characters and past the 8th, accepted as explained on 2026-10-20).

### Card thumbnails

A card's thumbnail is either `index.thumb` (`{mime, sha256, data}`, base64 of a JPEG, PNG or WebP up to 256 KiB, checked against its magic bytes and hash) or `index.thumb_url` (a remote image, used as given); a row with both is refused. A `thumb` is written to `assets/thumbs/<slug>.<hash>.<ext>` and cached a year, so the card no longer depends on a route only the site's server answers. dd's exporter emits the plugin's cached preview as `thumb`, and keeps `thumb_url` (the live `/thumb/` route) only for a PDF with no cached preview yet.

**parity.thumbnails** (`thumb_parity.py`). `exporters/deflockdane-fetch-thumbs.sh` reads the live index via the origin and fetches and hashes each card's image (`ssh gg-shared bash -s < roomkit/exporters/deflockdane-fetch-thumbs.sh > thumbs.tsv`); `parity --thumbs thumbs.tsv --out ROOM` passes when every card live shows an image shows the same bytes from the room's own tree. A live `<img>` that 404s is `live-broken`, explained, not a miss.


### Entities

A pack's `features.entities` (off in every committed pack) builds the site's entity index and entity pages from the manifest's `entities` block (`entities.py` documents it), at the live paths: dd `/reading-room/entity/<type>/<slug>/`; GG `/library/entities/` and `/library/entity/<type>/<slug>/`. One template for both (`entities.html`, `entity.html`, `partials/entity-head.html`, `entities.css`); the sites differ only in their export.

- **Every word is the site's.** Headings ("Appears alongside", "Documents linked to this entity", "Vendors"), counts, the eyebrow, the lede, the note, the head title and the JSON-LD come through the export, written by the exporter with the template's own formula, named. The lists come in the plugin's query order (`docs_for_entity`, `co_occurring`, `list_approved`) and its grouping (GG by collection, dd by agency). roomkit sorts, groups and composes nothing; a test changes a string in the export and sees it change on the page. The claim headings on a GG record page ("Attributed to", "Named in this document") already come the same way, through `display.groups`.
- **dd** has no entity index page, and its entity pages carry no claim headings and no JSON-LD (deflock-reading-room 3ab6ca4, read 2026-10-15), so the room shows none. dd's exporter now writes a page for every approved entity of every type (it used to export vendor chips only).
- **Links.** With the switch on, links to a built entity page (record-page chips, crumbs, "appears alongside") follow the mount. A record the room does not hold (GG's 65 text-only CFR records) keeps its live URL. With the switch off, `entities.gate` hides the block from the whole build, so no page, link or stylesheet changes (the goldens are built with a block and the switch off).
- **Refused:** a URL outside the room path or not made of slugs, a page whose URL does not end in its own `<type>/<slug>/`, a path starting with a record's slug or `assets`/`pagefind`, a duplicate, an index or "alongside" entry naming an entity with no page, missing or non-text strings, a non-object JSON-LD.
- **Accessibility.** One h1; the document groups are h3 under the documents heading (visually hidden on GG, as live) or h2 without one, so the outline has no gap; every list is named by its heading (`aria-labelledby`); the lists sit in panels, so only token pairs the pack's contrast gate measures are painted; nothing needs JavaScript. Playwright runs axe (WCAG 2.2 AA) at 375 and 1280 px, light and dark.
- **The exporters record what they copied.** `entities.source` holds the sha256 of each plugin file whose formula they repeat, as read on the host. The copies these were written against (2026-10-07 local checkouts): GG `templates/index-ggrr-entities.php` b785429d…, `templates/entity-ggrr.php` 9ddcdea2…, `includes/class-ggrr-entities.php` 5afc27ea…; dd `templates/entity-reading-room.php` 09d69b99…, `includes/class-deflock-reading-room-entities.php` dcb6d9be…, `includes/class-deflock-reading-room-template.php` d0bcd9a6…. A different hash means the template changed: re-read it before trusting the export (parity.entities will show what moved).

**parity.entities.** The live side is a file, as for `parity.search`, so dd can be read through the origin. `exporters/fetch-entity-pages.sh` GETs the pages (read-only, one a second) and writes `# fetched <time> <how>` and `<path>\t<code>\t<base64 html>` lines; `parity --entities-from` turns them into `LIVE.json` (`entity_parity.py` documents it): the live entity set (GG's index; dd's Yoast entity sitemap), GG's index groups, and per entity its documents and (GG) its "appears alongside" list, in page order. `parity --entities LIVE.json --out ROOM` reads the built room's own pages and passes only when the sets, the index (types, headings, entities, order), every page's documents and every alongside list are equal, every live page answered 200, and no built page went unchecked.

```bash
# GG: export (the new `entities` block rides in the first slice), build with the switch on, fetch, compare
{ echo "<?php define('ROOMKIT_ALLOW_EXCLUDED', true); ?>"; cat roomkit/exporters/glassgovernment.php; } \
  | ssh gg-core 'sudo -n /usr/local/bin/wp-prod eval-file -' > gg-manifest.json
mkdir -p /tmp/gg-pack && cp -R roomkit/packs/glassgovernment/. /tmp/gg-pack/ \
  && jq '.features.entities = true' roomkit/packs/glassgovernment/pack.json > /tmp/gg-pack/pack.json
$PY -m roomkit.cli build --manifest gg-manifest.json --out /tmp/gg-room --site-pack /tmp/gg-pack
jq -r '.entities.index.url, .entities.pages[].url' gg-manifest.json | sed 's#^https://glassgovernment.org/##' > gg-entity-paths.txt
bash roomkit/exporters/fetch-entity-pages.sh glassgovernment.org $(cat gg-entity-paths.txt) > gg-entity-pages.tsv
$PY -m roomkit.cli parity --entities-from gg-entity-pages.tsv --site glassgovernment > gg-entities-live.json
$PY -m roomkit.cli parity --entities gg-entities-live.json --out /tmp/gg-room

# dd: the same, every live read through the origin
ssh gg-shared 'ROOMKIT_ALLOW_EXCLUDED=1 ~/bin/wp --path=$HOME/domains/deflockdane.org/public_html eval-file -' \
  < roomkit/exporters/deflockdane.php > dd-manifest.json
mkdir -p /tmp/dd-pack && cp -R roomkit/packs/deflockdane/. /tmp/dd-pack/ \
  && jq '.features.entities = true' roomkit/packs/deflockdane/pack.json > /tmp/dd-pack/pack.json
$PY -m roomkit.cli build --manifest dd-manifest.json --out /tmp/dd-room --site-pack /tmp/dd-pack
ssh gg-shared bash -s -- --origin deflockdane.org deflock_rr_entity-sitemap.xml \
  $(jq -r '.entities.pages[].url | sub("^https://deflockdane.org/"; "")' dd-manifest.json) \
  < roomkit/exporters/fetch-entity-pages.sh > dd-entity-pages.tsv
$PY -m roomkit.cli parity --entities-from dd-entity-pages.tsv --site deflockdane > dd-entities-live.json
$PY -m roomkit.cli parity --entities dd-entities-live.json --out /tmp/dd-room
```

**The template is Jinja**, the same files the Civica reading room will render live (plan `2026-10-13-unified-reading-room-frontend`, Task 3a):

- `templates/room/`: `base.html` (the page and the room's chrome), `document.html`, `index.html`, `404.html`, `partials/` (macros, head, reader mount, index card, the room's own `chrome-header`/`chrome-footer`), and `room.css` / `chrome.css` / `room.js`;
- `view.py` builds the plain view-model dicts they read (which links follow a staging mount, groups and their order, counts). No template touches roomkit internals, so Civica can build the same dicts from its own rows;
- `room.py` is the environment and a thin render call: autoescape on, `StrictUndefined`, no filters that format dates or compose labels. Escaping is `html.escape` (in `finalize`), not markupsafe's, so quotes stay `&quot;`/`&#x27;` and the port changed no byte (`tests/roomkit/test_golden.py`).

**Every rule in `room.css` is scoped under `#room-content`** (a test holds this). It began as the dd contrast fix of 2026-10-12, when a captured site theme loaded beside the room and white plugin panels inherited its light `.entry-content p` color, 1.29:1. It still keeps the content's rules apart from the chrome's. dd's theme now uses the site's own raised darks for surfaces, written as literal values, because the theme defines some `--dl-*` tokens twice and a later block dims one to 2.46:1.

Without `--site-pack`, a build uses the manifest's site's pack, else `packs/default/` (light and dark from the system setting). `--site-pack DIR` names a pack explicitly; it is validated first (schema, contrast, CSS scoping, the parity matrix) and a refused pack stops the build with exit 2.

Verified 2026-10-12, locally: axe WCAG 2.2 AA clean on both sites' index, a document page and the 404, light and dark, 1280 and 390 wide. All 460 built pages (dd 69, GG 391) fit 390px with no sideways scroll.

**Continuity.** The pack is an input to the build, hashed into the lock. A menu or footer change on the live site reaches the room as an edit to the pack's `chrome`; `check` then reports the pages as stale.

### Facet pages and the sitemap

The no-JS ways in (`browse.py`; matrix rows `index-facet-pages` and `sitemaps`), each behind its own pack switch, off unless the pack asks. dd's pack turns both on (and, since 2026-10-20, `features.entities`).

- **Facet pages** (`features.facet-pages`). The manifest's `site.index.browse` names the facets that get pages (`{heading, facets: [{name, label, title}]}`, `title` holding `{value}`), and each record's `index.browse` the values it is listed under (`{name: [values]}`: a record can name two vendors). One page per value at `<room>/<facet>/<value-slug>/`, the index's cards in manifest order, and a browse block on the index, one folded list per facet, that works without JavaScript. Separate from `index.facets`, the finder's selects, which do not move. Refused at build: a facet named like a record or a path the room serves, a value with no ASCII slug, two values slugging the same, a record naming a facet the site does not browse. dd's exporter takes agency, document type, vendor and year from the shortcode's own `build_archive_search_payload`, fed what `render()` feeds it, so each page holds what live filtering holds.
- **Sitemap** (`features.sitemaps`). `sitemap.xml`: the room, every record, the entity index and pages (with entities on), every facet page, by live canonical URL, no lastmod.
- **parity.facet_pages.** `parity --facets-from INDEX.html --site deflockdane` reads the live index's `archiveSearch` docs into the live file (`browse_parity.py` documents it); `parity --facet-pages LIVE.json --out ROOM` passes when every live facet and value is built, every page's records are equal and the index links every page.
- **parity.sitemaps.** `parity --sitemaps <provider.xml>... --out ROOM`: the live provider files as fetched (dd: Yoast's `deflock_rr_document-sitemap.xml`, `deflock_rr_entity-sitemap.xml`), URLs under the room only, against the room's `sitemap.xml`; the room's index and facet pages are its own and not differences. A sitemap with a DOCTYPE is refused.

Fetch the live inputs through the origin for dd (Cloudflare 429s):

```bash
R=deflockdane.org:443:$ORIGIN_IP   # the host's own public address (exporters/deflockdane-fetch-pages.sh finds it)
curl -sS --resolve $R -o live-index.html https://deflockdane.org/reading-room/
curl -sS --resolve $R -o docs.xml https://deflockdane.org/deflock_rr_document-sitemap.xml
curl -sS --resolve $R -o entities.xml https://deflockdane.org/deflock_rr_entity-sitemap.xml
```

2026-10-20, dd: facet pages 33/33 (agency 17, type 7, vendor 2, year 7); the sitemap equal to the document and entity providers, 84/84, once dd's pack turned `features.entities` on the same day (parity.entities re-run 16/16). axe 0 serious/critical on the index and four facet pages, light, dark and 375 px; the browse block's 33 links present without JavaScript.

### Passage citations (GG)

A pack's `features.passage-cite` (off in every committed pack; plan Task 12, matrix row `passage-citations`, disposition dynamic-api) turns on the reader's citation panel as the WordPress reader has it: **"Cite page"** in the toolbar and **"Cite"** on each in-document search hit. There is no cite-from-selection; live has none (a later, separate step). The hybrid the user approved on 2026-10-15:

- **Cite page is static.** Each page in the export carries `cite` (reference, provenance_level, ocr_confidence), which is what `ggrr/v1/passage?slug=&page=N` answers. The exporter builds it with `GGRR_Citations::format_reference` and the route's own date formula, the permalink plus `#page-N`, and the page row's provenance. roomkit writes it into `pages.json`, and the engine (0.7.0) shows it without a request.
- **A hit's Cite asks the live route.** The engine's static search gives each hit the span GG's route gives (`GGRR_Search::locate`: the earliest case-insensitive occurrence of any query term, as long as the term, in code points). The engine sends `?slug=&page=&start=&end=` to `passages.api` (the site's `rest_url`) and shows the server's reference, quote, provenance and key, as on live.
  - At cutover the room is on the same host as the API. A staging host works too, because WordPress echoes the Origin; the engine sends no cookies to another origin.
  - roomkit emits no CSP. A server that sends one needs `connect-src` for the API's origin.
- **Failure is never a broken panel.** Offline, a blocked origin, an error status, `found: false` or the 8 s timeout each show that page's own citation with "The exact passage could not be resolved here; this cites the page." There's no quote and no key. Without JavaScript, nothing changes: the record's citation text stands.
- **Curated citations** (every wp_ggrr_citations row, as `GGRR_Citations::get_by_stable_key` shapes it) ship as `citations.json`, each key mapped to what `ggrr/v1/citation?key=` answers. No page lists them, and live shows none either; entities and power maps name them by key.
  - A row of a record the exporter excluded is excluded with it and named.
- **Refused** (`passages.py`):
  - an `api` that is not https, or has a query;
  - a citation naming a record the room does not hold, or with another record's `document_id`;
  - a stable_key that is not `sha256("{document_id}|{page}|{start}|{end}")`;
  - a quote that is not the page text between its offsets (code points, as `mb_substr`);
  - a duplicate key, or a page `cite` of the wrong shape.
- **The exporter records what it copied:** `passages.source` holds the sha256 of `includes/class-ggrr-citations.php` and `includes/class-ggrr-rest.php` as read on the host. The local copy it was written against (c81ba37) has 40d959aa… and ba425447….

**parity.passages** (`passage_parity.py`). `parity --passages-fetch --out ROOM --sample N [--keys KEYS.txt]` makes the paced public GETs: read-only, a browser UA, `--pace` seconds apart (2 by default), stopping at the first 429 or 403. It asks for:

- N cited pages, spread evenly over the room, each page-scoped;
- one span on each of those pages;
- each curated key from `--keys` at `ggrr/v1/citation`.

`parity --passages LIVE.json --out ROOM` passes only when all of these hold:

- every page's live reference and provenance equal the room's `cite`;
- every live span quote is the room's page text between its offsets, and its key is the formula's;
- every curated answer's text is a room page's text between its offsets (a document-scope citation, `page_number` null, has no room page and is held to `citations.json` alone);
- where `citations.json` holds the same key, it equals live field by field.

## The room's own chrome

The room draws its own header, navigation and footer from the pack's `chrome` (plan `2026-10-13-unified-reading-room-frontend`, Task 5). Nothing is captured from WordPress: the pack holds link labels, targets and footer text, and the look comes from the tokens.

- **Landmarks:** `header`, one `nav` with an `aria-label` (`chrome.nav_label`), `main#room-content`, `footer`. The breadcrumb and jump navs stay inside `main`.
- **A skip link first.** Its text is `chrome.skip_text` and it targets `#room-content`.
- **A menu that needs no JavaScript.** The nav's links sit in one `<details>`/`<summary>` (`chrome.menu_label`), which is the menu on narrow screens. On screens at least `chrome.inline_from` wide that support `::details-content` (Chromium 131+, Safari 18.4+, Firefox 143+), the summary is `display:none` and the closed details' content is shown, so the links sit in a row. The list is rendered once, so there is no hidden copy to keep out of the accessibility tree or the tab order. Older browsers keep the disclosure at every width, so the links are never unreachable. The rule that hides the summary has to outrank the summary's own `display:flex`. Getting this wrong was the 2026-10-14 review bug, where "Menu" stayed a full-width box. `test_chrome.py` checks the specificity, and checks both widths in Chromium where Playwright is installed.
- **The width where the nav goes inline is pack data.** `chrome.inline_from` (an em length) is the narrowest width at which the site's name, the gap and the whole link row fit on one line, measured in Chromium with a margin for font differences. The values are default 17em, deflockdane 55em, glassgovernment 81em and hrtarchive 47em, re-measured on 2026-10-14 with the site name kept on one line. Before that they were 20, 56, 80 and 48em. The site name never wraps; a tagline may. The header bar has the page column's width (1232px with its 16px padding, a 1200px column) at every width, so the brand starts on the content's left edge and the row never reaches past its right edge; only `inline_from` decides when the links fold into the Menu. (Before 2026-10-14 the bar was `max(1232px, inline_from)` wide, which put GG's brand 32px left of the content at 1440px.) A media query cannot read a custom property (`var()`), so `room.chrome_css(pack)` writes the value into the query, `@supports selector(::details-content){@media (min-width:<inline_from>){…}}`, around `templates/room/chrome-wide.css` when the stylesheet is built. The schema holds the value to a plain em length, so it cannot break out of the rule. Below that width the header shows the Menu button. Re-measured against the 1200px column on 2026-10-14 (every pack with the nav forced inline from 17em, widths 320 to 1400 in steps of 8): the links fit on one row inside the column from about 488px (deflockdane), 984px (glassgovernment) and 472px (hrtarchive), so the values above are unchanged and keep their margins.

  The nav never shrinks, so its links never wrap into an orphan row. The brand may shrink and wrap instead, which lets the Menu button sit beside it on a phone. A Playwright test walks every pack at 320, 375, 768, 900, 1024, 1280 and 1440. At each width it asserts the brand's left edge equals the page column's (within 1px), the header's right edge is inside it, the site name on one line, either the Menu button or one row of links (tops within 2px), and a header at most 100px tall.
- **Groups stay usable.** A group of links (`{"label", "links"}`) is a nested `<details>`: a dropdown on wide screens, an indented list on narrow ones. A dropdown opens from its summary's end toward the start, and its width is capped at the viewport, so it stays inside the header's content box (Playwright checks every group open at 1024 and 1280). Every summary draws a caret that turns when open, because `display:flex` drops the native marker, and group labels look like links. No group needs a URL of its own.
- **Hover from tokens.** A filled button's hover swaps to `surface` with `ink`, and a ghost button's hover fills with `accent` and `on-accent`. This is the same for every pack, and it outranks any pack's `extra_css` hover. pack.py's pairs already hold both labels to 4.5:1 and the fill change to 3:1, and `test_chrome.py` re-measures them per pack and scheme. (dd's old `extra_css` hover, which equalled its accent, went with the shell.)
- **Styles from tokens only.** `templates/room/chrome.css`: every rule is under `body.room-plain`, and every color and the focus ring (`--room-focus`) is a `--room-*` token. A test refuses a color literal. The stylesheet is `room.css` + `chrome.css` (+ `chrome-wide.css` at `inline_from`) + the pack's tokens. The tokens also go on `body.room-plain`, the body follows the light/dark toggle through `:has()`, and `identity.backdrop` (if given) paints the body.
- **Generic.** The site's name in the header is `chrome.home`, not `identity.name`, so two packs with the same chrome draw the same bytes (`test_generic.py`). No template or room module names a site (`test_chrome.py`).

**Count nouns are pack labels.** "5 records" and "4 categories" take `labels.record_singular|record_plural` and `labels.group_singular|groups_plural`, singular for a count of 1. A pack without them is refused; nothing builds a plural with `+"s"`. The finder's live count in `room.js` takes them from `data-room-one`/`data-room-other` on the count.

**One source for the group noun, and a jump nav named by what it shows.** The finder's group label, the jump label and the jump nav's accessible name all come from the pack (`labels.group`, `labels.jump`, both required). The manifest's `group_label` is not shown. The nav's `aria-label` is the visible jump label minus trailing punctuation (WCAG 2.5.3): "Jump to jurisdiction:" names the nav "Jump to jurisdiction". A folded list's toggle uses the same short form before its count, "Jump to jurisdiction (17)". Shown alone, the label stays as written.

A pack with no `chrome` gets only the skip link ("Skip to the content"). So does any caller of `view.page_view` that passes no chrome. (Civica's spike adapter called `page_view(main, view, at, None, head, [])` with a shell slot that no longer exists; it needs `page_view(main, view, at, head, [], chrome)` when it vendors this.) Where each site's chrome came from is recorded in its pack as `chrome.source` (URL and date; not rendered).

## Caching

- **Assets and page texts carry a content hash in their names** and are served `Cache-Control: public, max-age=31536000, immutable`. A new build makes new names, never a stale file.
- **HTML is the only thing that changes in place.** It is served `public, max-age=0, s-maxage=3600, must-revalidate`: browsers revalidate (ETag/304), an edge may hold it for an hour between purges.
- **`roomkit diff`** compares the served lock with the new one and says what the publish must do:
  - `purge`: the changed or removed HTML (assets never need a purge);
  - `remove_now`: pages and page text of records that left the room, so a retraction is not left behind at a hashed URL;
  - `remove_later`: old assets. They stay one more generation, so HTML an edge still holds can load what it names.
- **`404.html`** plus `ErrorDocument` in `.htaccess` keep missing paths off WordPress.

## Publishing (staging)

`publish/deflockdane-staging.sh`, run by a person on the Mac. It exports, builds and checks in the dd site pack, runs parity (pages, then thumbnails), uploads without `--delete`, removes per `roomkit diff`, checks every served file against the lock, and prints the purge list. Everything it reads from the site goes through the origin (Cloudflare 429s).

Rendering is deterministic: no timestamps, sorted keys, documents in manifest order. `check` uses the same in-memory render as `build`, so a check cannot pass a tree the build would not have made.

Every document page keeps the no-JS promise driftkit probes the WordPress pages for: `data-reader-status`, the `data-reader-fallback` block with Open and Download links, and for a PDF a noscript `object.rr-reader__object`. Pages are reachable at the same paths as today (`site.room_path` + slug), with a canonical link to the live URL.

**In-document search** is on wherever the manifest carries page texts. The page gets `data-pages-url` and `search`, and the engine (0.6.0+) searches `pages.json` in the browser, matching dd's route exactly (70/70 real cases, 2026-10-08). Per-passage citations stay off: there is no passage route, and roomkit composes no citation. The page's own citation text stands.

## The manifest

A JSON object with `site` (`name`, `title`, `base_url` with no trailing slash, `room_path` like `/reading-room/`) and `documents`. The full shape is in the `manifest.py` docstring. Each document needs:

- `slug`, `title`, `visibility: "public"`;
- `citation`, exported verbatim from the site's own formatter. roomkit never composes a citation;
- `file.url`, `file.download_url`, `file.sha256`, `file.ext`, `file.mime`.

Optional: `agency`, `date`, `summary`, `archive_url`, `file.bytes`, `pages` (`[{n, text, provenance}]`), `search_text` (a string, only on a record with no `pages`; a row with both is refused).

## What it refuses to guess at

Any refused row fails the whole build, and nothing is written. A reading room quietly missing a record is the failure this kit exists to prevent. Refused:

- a row that is not `visibility: public`. The exporter must not send private rows at all, so one arriving means the exporter is wrong;
- a slug that is not lowercase letters, digits and single hyphens (this also blocks `../` paths), and duplicate slugs;
- a missing title or citation;
- a `sha256` that is not 64 hex characters;
- a file URL that is not `https://` or a same-host path (`javascript:`, `data:`, `http:` and `//host` are refused);
- an extension that is neither a reader type nor a known download-only type (`zip`, `xlsx`, `xls`, `docx`, `doc`, `pptx`; those pages get the links and the citation, no reader), an empty mime;
- a `view_url` on anything but a PDF, or a `view_url`/`poster_url` that is not `https://` or a same-host path;
- a date that is not `YYYY`, `YYYY-MM` or `YYYY-MM-DD`;
- an `archive_url` that is not `https://`;
- page numbers that are not 1..N in order.

Everything from the manifest is HTML-escaped. Files left over from an earlier build (a retracted record's page) are listed as `not_in_room`, never deleted by build: removal belongs to the publish step, together with the purge that has to follow it. `check` reports them as `extra` until they are gone.

## Tests

In this repository, hermetic unit and regression tests are located in `tests/`:
- `tests/test_manifest.py`: manifest parsing, path/mount validation, boolean integer bypass rejection, and parity checks (`check_details`, `check_header_actions`, `check_badges_notice`, `check_link_groups`, `check_notes`);
- `tests/test_golden.py`: byte-for-byte rendered tree regressions against `tests/golden/*.txt`;
- `tests/test_pack.py`: site pack schemas, token mapping, WCAG AAA contrast, and refusal rules;
- `tests/test_ocr.py`: OCR execution, output file existence and non-empty output verification;
- `tests/test_router.py`: URL routing and mount resolution.

In the upstream monorepo (`llm-wiki`), the full extended test suite under `tests/roomkit/` additionally covers:
- the template's invariants: every `room.css` rule scoped under `#room-content`, unknown theme tokens refused, the GG toggle sharing `ggrr-theme`, the long jump list folding;
- malformed `display`/`index` blocks refused (group style, badge kind, notice, facets, meta, unsafe group URLs);
- fingerprinting, cache headers and `diff` (a retraction removed now, old assets later);
- refusals and escaping;
- determinism and the lock;
- the no-JS markers;
- viewing copies, posters, download-only files and exclusions;
- check finding tampering and changing nothing; status;
- parity (agreement, a drifted citation, a wrong reader URL, 429 backoff);
- the parity matrix: the real matrix is well formed; malformed rows, unknown dispositions/sites/needs/statuses and duplicate ids refused; empty sign-off refused, null sign-off awaiting and blocking; which rows block; `--site`; the text grouping; `status --json`;
- `test_golden.py`: the whole rendered tree for every pack (plain/default, dd, GG, hrtarchive), byte for byte against `golden/*.txt`. These were pinned on the string template before the Jinja port, and re-pinned on purpose since; the docstring lists each move. dd and GG became pack-chrome builds when the shell retired;
- `test_chrome.py`: the room's own chrome on every page of every pack (landmarks, one labelled site nav, the skip link first and targeting `#room-content`, the details/summary menu holding every link, escaping); `chrome.css` scoped and painting tokens only, focus rings from `--room-focus`; the body following the toggle and the backdrop; a shell build byte-identical with or without pack chrome; no site named in templates or room modules; the chrome schema's refusals; site chrome absolute and sourced;
- the Jinja environment: autoescape, `StrictUndefined`, no roomkit filters, stdlib escaping, a view model that is plain data;
- `test_vendor.py`: the vendored core: pinned, its drift named (modified, missing, behind), refusal while the core is uncommitted, nothing outside the core imported, a copy rendering roomkit's bytes;
- `test_generic.py`: the hrtarchive demo pack building its synthetic fixture with no template change, and, for every pair of the four packs, pages differing only through layout/labels/features/chrome (identity, tokens and `extra_css` reach only the stylesheet);
- `test_pack_import.py`: reading design-tokens files (duplicates, unresolved names, cycles, `@media` variants), the map's refusals, an import refused when the pack would be, and every shipped pack equal to what its map derives;
- `test_pack.py`: the site packs: the schema; every refusal (unknown keys, missing tokens, unsafe URLs and values, contrast light and dark including the 1.29:1 dd panels, unscoped `extra_css`, dropped features, missing files); explicit packs building the golden bytes; `color.py` agreeing with the wiki gate's contrast math;
- a Playwright run that mounts the reader on a built page, and the same page with JavaScript off;
- `test_browse.py`: facet pages and the sitemap: both switches off change no byte, facet pages on without a browse block build none; one page per value at its path with its records in manifest order, the canonical live and links following the mount; the index linking every page without JavaScript, facets in the site's order and years newest first; each build refusal and each malformed browse block; the sitemap's URLs, escaping and switch; parity.facet_pages from a dd-shaped live index, agreeing with its own room and naming each difference (extra or missing value, members, missing facet, an unlinked page); parity.sitemaps ignoring the room's own pages and URLs outside it, naming missing and extra, refusing a sitemap index, a DOCTYPE and a room without a sitemap; the CLI for both;
- `test_entities.py`: the entity surface on GG- and dd-shaped fixtures: the switch off changes no byte (goldens with a block), only dd's committed pack on; index grouping and entity order as exported; documents in the export's groups and order; links following the mount, a record outside the room kept live, record-page chips rebased only with the switch on; "appears alongside" with kind and count; every heading and label changed in the export changes the page (the record page's claim headings too); no entity word in a template or view; the JSON-LD the exported object (none for dd); each refusal; the same pages for two sites with the same knobs; `entities.css` scoped and token-only; parity.entities reading its own room, agreeing, naming each kind of difference (order, missing, extra, index heading, unchecked, unfetched), refusing a bad live file; live markup (GG index and page, dd page and sitemap) turned into the live file; axe at 375 and 1280, light and dark, no sideways scroll, and without JavaScript one h1, no heading gap, landmarks and named lists.
