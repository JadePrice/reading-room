# roomkit

A reading room as static files, built from a site's manifest of its public documents.

roomkit renders a document archive into plain files: an index, one page per record with the shared reader mounted on it and a no-JS fallback, the site's own citation text, the original's sha256, and a `pages.json` of page texts. It reads a manifest and writes only its output directory. It has no publish step of its own: publishing is a separate, human decision.

This is the public part of roomkit. The sites roomkit publishes for in the source repository (their exporters, parity checks against their live WordPress rooms, publish, cutover and rollback scripts, and their packs) are the sites layer, `sites/` ([sites/README.md](sites/README.md)), which the public mirror leaves out.

## Commands

```bash
PY=python3   # with Jinja2, jsonschema and PyYAML installed
$PY -m roomkit.exporters.folder DIR > M.json                     # a folder of PDFs + documents.json -> a manifest
$PY -m roomkit.cli build  --manifest M.json --out DIR [--json]   # validate, then write the room
$PY -m roomkit.cli check  --manifest M.json --out DIR [--json]   # rebuild in memory, compare; changes nothing
$PY -m roomkit.cli status --manifest M.json --out DIR --json     # unbuilt | stale | current | refused, and the next command
$PY -m roomkit.cli diff --old OLD/room.lock.json --new NEW/room.lock.json [--json]  # purge + remove lists
$PY -m roomkit.cli gate --out DIR [--max-bytes N] [--json]       # links into the mount land on a file; no file over 25 MiB
$PY -m roomkit.cli pack import --map PACK/tokens.map.json [--write]  # pack tokens from a design-tokens file
$PY -m roomkit.cli vendor write --to /path/to/app/room     # copy the core into the host application, pinned
$PY -m roomkit.cli vendor check --to /path/to/app/room [--json]  # its drift; changes nothing
```

`build`, `check` and `status` take `--site-pack DIR` (the site pack, below). Without it, the manifest's site's pack (`site.template`), else `packs/default/`. `build` also takes `--mount /staging-path/ --noindex` for a staging copy served at another path, whose canonicals stay on the live URLs.

Exit codes: 0 ok; 1 refused rows (build) or a difference (check, gate); 2 the manifest cannot be read at all.

`roomkit --help` lists every subcommand present. With the sites layer in place it also has `parity`, `pack theme` and `status --matrix`, which the public copy does not.

## A folder of PDFs, start to finish

`exporters/folder.py` is the exporter that needs no particular website. Put the PDFs in a folder with a `documents.json` beside them (the shape is in the module's docstring: a `site` block, then one row per PDF with `file`, `title` and `sha256`, and optionally `date`, `group`, `source_url` and `summary`):

```bash
$PY -m roomkit.exporters.folder ~/records > manifest.json
$PY -m roomkit.cli build --manifest manifest.json --out room --site-pack roomkit/packs/example
$PY -m roomkit.cli gate --out room
```

It runs pdftotext and pdfinfo (poppler) for the page texts, and refuses a PDF whose bytes do not hash to its `sha256`, a page-count disagreement between the two tools, a file outside the folder, a `source_url` that is not `https://`, and two files that make the same slug. The room links to each PDF at the site's `files_path` (default `/files/`) and never copies one.

## The site pack

Every room uses one page template (`templates/room/`). Anything a site can change is in its **pack** (`pack.json`: identity, tokens light and dark, labels, layout, features, chrome); anything not in a pack is the same for every site. roomkit ships two: `packs/default` (the plain room, rows) and `packs/example` (an invented site with cards, a light/dark toggle, a nav group and footer columns). What a pack may hold and every check it must pass: [packs/README.md](packs/README.md).

A pack's tokens must pass WCAG contrast, light and dark, at build time. `extra_css` must be scoped under `#room-content`. A template that branched on which site it renders would fail `tests/roomkit/test_generic.py`: give one pack another's layout, labels, features and chrome, and every page is byte-identical to the other's.

Features a pack can turn on are listed under `features` in `packs/pack.schema.json`, all off unless the pack says so: among them `corpus-search` (a Pagefind index, `search.py`), `facet-pages` and `sitemaps` (`browse.py`), `entities`, `collections`, `topics`, `passage-cite` and `read-aloud`. A feature that needs data reads its own optional manifest block, documented in the module that owns it.

## What a build writes

```
index.html                   the list of documents
404.html                     what a missing path gets
<slug>/index.html            one page per document
<facet>/<value>/index.html   one page per facet value (features.facet-pages)
sitemap.xml                  every served page by its live URL (features.sitemaps)
<slug>/pages.<hash>.json     page texts, when the manifest carries them
assets/room.<hash>.css       the shared template's styles, the room's chrome, the pack's tokens
assets/room.<hash>.js        the index finder and the light/dark toggle
assets/room-search.<hash>.js the corpus-search finder and suggestions (features.corpus-search)
pagefind/                    the Pagefind index (features.corpus-search)
assets/vendor/rr-reader/     the reader engine (reading-room-reader/src), verbatim
assets/vendor/pdfjs/         pdf.js as the engine pins it
.htaccess                    cache headers and the 404 page (Apache/LiteSpeed)
room.lock.json               sha256 of every served file, logical -> published names, versions, the pack's hash
```

The tree is written into a sibling copy (`.<out>.new`) and swapped in with two renames, so a build that fails part-way leaves the previous room whole. Files no longer in the room stay and are listed (`not in room`); removing them is the publish step's job.

## Caching

- **Assets and page texts carry a content hash in their names** and are served `Cache-Control: public, max-age=31536000, immutable`.
- **HTML is the only thing that changes in place.** It is served `public, max-age=0, s-maxage=3600, must-revalidate`.
- **`roomkit diff`** compares the served lock with the new one and says what a publish must do: `purge` (changed or removed HTML), `remove_now` (pages and page texts of records that left the room, so a retraction is not left behind at a hashed URL) and `remove_later` (old assets, kept one more generation).

## The manifest

A JSON object with `site` (`name`, `title`, `base_url` with no trailing slash, `room_path` like `/reading-room/`) and `documents`. The full shape is in the `manifest.py` docstring. Each document needs:

- `slug`, `title`, `visibility: "public"`;
- `citation`, exported verbatim from the site's own formatter. roomkit never composes a citation;
- `file.url`, `file.download_url`, `file.sha256`, `file.ext`, `file.mime`.

Optional per record: `agency`, `date`, `summary`, `archive_url`, `file.bytes`, `pages` (`[{n, text, provenance}]`), `search_text`, `lang`, source-backed `provenance`, and in-room `relations`. A text-only record has `"file": null` and must carry `search_text` or `pages`.

## What it refuses to guess at

Any refused row fails the whole build, and nothing is written. A reading room quietly missing a record is the failure this kit exists to prevent. Refused:

- a row that is not `visibility: public`;
- a slug that is not lowercase letters, digits and single hyphens, and duplicate slugs;
- a missing title or citation;
- a `sha256` that is not 64 hex characters;
- a file URL that is not `https://` or a same-host path;
- an extension that is neither a reader type nor a known download-only type, or an empty mime;
- a date that is not `YYYY`, `YYYY-MM` or `YYYY-MM-DD`;
- page numbers that are not 1..N in order.

Everything from the manifest is HTML-escaped.

## The core, vendored

The part that renders the room is a **core** with nothing roomkit-only in it: `manifest.py`, `entities.py`, `site_collections.py`, `machine_text.py`, `topics.py`, `passages.py`, `head_meta.py`, `page_text.py`, `text_clean.py`, `redirects.py`, `view.py`, `room.py`, `css.py`, `color.py`, `pack.py`, `search.py`, `browse.py`, plus `templates/room/` and `packs/pack.schema.json` (`vendor.CORE_MODULES`). The core imports only itself, the standard library, Jinja and jsonschema. Around it are the roomkit-only parts: `build.py`, `cli.py`, `gate.py`, `pages_headers.py`, `vendor.py`, the pack importer (`tokens_css.py`, `pack_import.py`) and `exporters/folder.py`.

**The host application carries a verbatim copy, pinned.** `vendor write` copies the core into a package directory and records `VENDORED.json` (source commit, sha256 per file); it refuses while a core file has uncommitted changes. `vendor check` is read-only and names files `modified` in the copy (fix upstream, never in the copy), `missing`, or `behind` the source; exit 1 on any. The host application must render through the copy's own `room.ENV`, so its pages match roomkit's byte for byte (`tests/roomkit/test_vendor.py`). On the host application's `/admin/kits`, roomkit is listed under "no standing census": it builds from a manifest per run and keeps no state between builds.

## Tests

```bash
PYTHONPATH=. pytest tests/roomkit --ignore=tests/roomkit/sites
```

- `test_golden.py`: the whole rendered tree for each shipped pack (`plain` on default; `example` and `example-folded` on example), byte for byte against `golden/*.txt`;
- `test_generic.py`: every pair of shipped packs differs only through layout, labels, features and chrome;
- `test_pack.py`, `test_pack_import.py`: the pack schema and every refusal, contrast light and dark;
- `test_chrome.py`: the room's own header, nav and footer on every page of every pack;
- `test_exporter_folder.py`: the folder exporter, on PDFs written by the test, built with each shipped pack;
- `test_vendor.py`: the vendored core pinned, its drift named, a copy rendering roomkit's bytes;
- `test_core_is_site_free.py`: nothing outside the sites layer names a site or imports it.

Tests that open a browser need Playwright and Chromium; Pagefind is pinned in `requirements-dev.txt`.
