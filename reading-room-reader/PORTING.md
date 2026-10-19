# PORTING — glassgovernment.org (upstream) → deflockdane.org (downstream)

Both reading rooms are the **same plugin, forked once** and evolved per site.
They already share the PDF reader engine (this repo, vendored via `sync.sh`).
For everything else, treat **`gg-reading-room` as upstream** and
**`deflock-reading-room` as a downstream branch**: land a feature on GG first,
then port it here. This file is the map that makes that port mechanical instead
of archaeological.

## Where the code lives

| | glassgovernment.org (upstream) | deflockdane.org (downstream) |
|---|---|---|
| Plugin dir | `gg-reading-room` | `deflock-reading-room` |
| Host | gg-core, `/srv/wp-prod` atomic release | gg-shared (Hostinger), `~/domains/deflockdane.org/public_html` |
| Parity repo | `gg-core:~/glassgovernment-site` | `gg-core:~/deflockdane-site` |
| Deploy | `bash deploy-homepage-and-reader.sh` (atomic + smoke) | sync parity → gg-shared plugin dir, then `wp rewrite flush` + cache flush |
| SEO stack | Yoast | Yoast (same hooks apply) |

## Symbol / route map

| Concept | GG (`ggrr_`) | dd (`deflock_rr_`) |
|---|---|---|
| Version const | `GGRR_Plugin::VERSION` | `DEFLOCK_RR_VERSION` + header |
| Storage class | `GGRR_Storage` | `Deflock_Reading_Room_Storage` |
| Docs table | `{prefix}ggrr_documents` | `{prefix}deflock_reading_room_docs` |
| Template class | `GGRR_Template` | `Deflock_Reading_Room_Template` |
| Entities class | `GGRR_Entities` | `Deflock_Reading_Room_Entities` |
| Plugin class | `GGRR_Plugin` | `Deflock_Reading_Room_Plugin` (hooks in `init()`) |
| Doc route | `/library/<slug>/` | `/reading-room/<slug>/` |
| Entity route | `/library/entity/<type>/<slug>/` | `/reading-room/entity/<type>/<slug>/` |
| List page | virtual `pagename=library` | real WP page `/reading-room/` |
| Site name in copy | `Glass Government` | `Deflock Dane` |

## What is shared vs per-fork

- **Shared (edit here, `./sync.sh <plugin>/assets`, never edit the vendored copy):**
  `rr-reader.js`, `rr-reader-pdf.js`, `rr-cite.js`. Site-agnostic behavior only.
  Consumers emit the neutral mount/attrs (`.rr-reader[data-file-url]`,
  `[data-rr-cite-copy][data-cite]`) and localize their own config.
- **Per-fork (port by pattern, not copy):** the Yoast SEO filters, the sitemap
  providers, JSON-LD, and any template markup. These bind to per-plugin storage
  classes, routes, and site name, so they cannot be verbatim-shared — mirror the
  pattern and swap symbols per the table above.

## Yoast-hook checklist (what a reading-room fork must register)

Registered in the plugin class (GG: `hooks()`; dd: `Deflock_Reading_Room_Plugin::init()`):

- `wpseo_title` — per-doc `<title>` **only if Yoast overrides the core title**.
  GG needs it (virtual `pagename=library` makes Yoast serve the shared page
  title); **dd does NOT** (core `document_title_parts` already wins there —
  verify live before adding).
- `wpseo_canonical` + `wpseo_opengraph_url` → `filter_yoast_canonical`
  (self-referential per route; without it the virtual routes de-index).
- `wpseo_metadesc` + `wpseo_opengraph_desc` → `filter_yoast_metadesc`
  (curated summary; guard scanned-doc OCR with `looks_like_ocr()`).
- `wpseo_opengraph_title` → `filter_yoast_og_title`.
- `wpseo_sitemaps_providers` → register a **document** provider and an
  **entity** provider (`implements WPSEO_Sitemap_Provider`). Lazy-require the
  provider files inside the filter. Gate on `is_private_mode_enabled()` if the
  fork has a private mode.

## Porting checklist (per feature)

1. Land + verify the feature on GG (upstream).
2. Map symbols/routes via the table above.
3. Skip anything the downstream already satisfies — **verify live, don't
   assume.** (dd already has: server-side URL-param filtering, full-text on all
   docs, a real WP list page, per-doc title, complete file hashes.)
4. For SEO: register the same Yoast hooks; adjust site name + route bases + no
   em dashes in any public copy string.
5. For shared JS: `./sync.sh <plugin>/assets`, enqueue the module, emit neutral
   attrs.
6. Bump the plugin version, deploy to the downstream host, re-probe live
   (canonical, metadesc, sitemap `<loc>`, JSON-LD, the interactive control).

## Live-verify probes (downstream)

```
curl -s https://deflockdane.org/sitemap_index.xml            # lists doc + entity sitemaps
curl -s https://deflockdane.org/reading-room/<slug>/ | grep -i 'canonical\|description\|ld+json'
```
Drive the reader + a filtered list in a browser — the deploy smoke gate only
checks page-200, never JS behavior.
