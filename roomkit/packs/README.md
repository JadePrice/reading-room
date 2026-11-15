# Site packs

A site pack is the one place a site customizes the shared reading room. Anything a site can change is in its pack; anything not in a pack is the same for every site. In the host application, a pack becomes the tenant's theme, validated against the same schema.

```
packs/
  pack.schema.json        the structure (JSON Schema 2020-12), shared with the host application
  default/pack.json       the plain room, rows, light and dark from the system setting
  example/pack.json       an invented site (Riverbend Records Office): cards, empty groups
                          shown, a light/dark toggle, a nav group, footer columns, and
                          facet pages, sitemaps and corpus search on
```

A site's own packs live with the rest of that site's code. In the source repository that is the sites
layer, `sites/packs/` ([sites/packs/README.md](../sites/packs/README.md)); the build looks
there after `packs/` (`build.PACK_DIRS`).

## What a pack holds

| Key | What it is |
|---|---|
| `identity` | `site` (matches a manifest's `site.template`), `name`, `base_url`, optional `logo`/`favicon` (files in the pack), and `backdrop`: the color behind a transparent `page-bg`. The contrast check measures against it, and the page paints its body with it |
| `tokens`, `tokens_dark` | the `--room-*` values (`room.TOKENS`); every color token is required, light and (if present) dark |
| `reader`, `reader_dark` | optional `--rr-*` overrides for the reader engine |
| `fonts` | self-hosted font files in the pack. No CDN |
| `chrome` | what the room draws around itself: its header, navigation and footer. Required: `home` (the site's name and link), `skip_text`, `nav_label` (the nav's accessible name), `menu_label` (the narrow-screen menu's summary), `inline_from` (an em width from which the links sit in one row; measured per site). Optional: `tagline`, `nav` (links, or `{label, links}` groups), `notice` (a line under the header), `footer` (link columns, heading optional), `footer_text` (paragraphs, verbatim), `source` (where it was taken from: `url`, `date`; not rendered). Links back to the live site are absolute ([../README.md](../README.md), "The room's own chrome") |
| `labels` | required: `group` (the group as a label, e.g. "Category"; the only source of the group noun), `jump` (the jump list's label; the nav's accessible name is this minus trailing punctuation) and the count nouns `group_singular`, `groups_plural`, `record_singular`, `record_plural`. The room picks the singular for a count of 1 and never builds a plural (no `+"s"`). Optional: room, other group, jump text, search placeholder, "Released", and `stats_singular`/`stats_plural` for the index header's count when the site names it apart from the result count ("455 documents" over "455 records") |
| `layout` | `style` (`cards`/`rows`), `show_empty_groups`, `toggle` (a localStorage key shared with the site, or empty) |
| `host` | where the room is served, when that changes the server config the build writes: `cloudflare-pages` writes `_headers.room`, the fragment the publish script splices into the site's one root `_headers` (Pages joins a header set twice with a comma, so the assets rule detaches `Cache-Control` before setting its own). Unset: the room writes no host-specific file |
| `features` | one switch per surface (`pack.schema.json` lists each with what it builds). The template renders a surface only when the pack turns it on and the manifest supports it. `default` turns none on; `example` turns on corpus-search, facet-pages and sitemaps |
| `extra_css` | an escape hatch, scoped under `#room-content` |

## What is refused

`pack.py` runs the schema, then the checks a schema cannot state. Every problem is listed, and a refused pack is refused whole (`roomkit build --site-pack` exits 2 and writes nothing).

- **Structure** (the schema): an unknown key anywhere, a token name the room does not have, a value that could break out of CSS (`;`, `{`, `}`, `<`, `>`, in a token or the backdrop), a chrome entry missing a required field or a nav item that is both a link and a group, a nav or footer URL that is not `https://` or a same-host path, a pack file path that leaves the pack.
- **A missing color token**, light or dark.
- **Contrast below 4.5:1 for text or 3:1 for focus rings and button fills**, for every pair the template paints (`pack.PAIRS`), light and dark. Colors are hex or `oklch()`, alpha included (`color.py`). Anything else (`var()`, named colors) cannot be measured and is refused. A `transparent` page needs `identity.backdrop`.
- **`extra_css` outside the room**: a rule not under `#room-content` (or the plain page's own `body.room-plain`).
- **A feature the parity matrix drops**: on, while every matrix row behind it is `dropped`. Only where the sites layer and its matrix are present (`roomkit build`; `cli._load_pack`).
- **A logo, favicon or font that is not a file in the pack.**

## Tokens come from the site's design tokens

A pack does not copy hex values by hand. `tokens.map.json` beside it maps each room token to a variable in the site's `design-tokens/<site>.tokens.css`, and `roomkit pack import` writes the pack's `tokens` from it:

```bash
$PY -m roomkit.cli pack import --map PACK/tokens.map.json          # what would change
$PY -m roomkit.cli pack import --map PACK/tokens.map.json --write  # write it
```

- The map is complete: the pack's tokens become exactly the mapped and `literal` entries.
- A value that does not come from the file is a `literal` and must say `why`; a mapped value may too. Every `why` lands in the pack's `token_notes`, so each value that is not simply the site's is explained in the pack.
- **Refused:** a variable the file does not define, defines twice at the top level, or cannot resolve (`tokens_css.py`); a map key the room does not have; a token both mapped and literal; a literal without a why; and any pack `pack.py` would refuse (contrast included).
- `@media` variants (`prefers-contrast: more`) are listed, not imported.
- `tests/roomkit/test_pack_import.py` re-derives every pack that has a map from it: a hand edit to such a pack's tokens fails it. `default` and `example` are written by hand and have none.

## The room is generic

`tests/roomkit/test_generic.py` holds the rule for every shipped pack, pair by pair: give one pack another's `layout`, `labels`, `features` and `chrome`, and every page is byte-identical to the other's, whatever its identity, tokens, `extra_css` or notes. Tokens reach only the stylesheet, after the shared `room.css`. A template that branched on which site it renders would fail it.

## Using one

```bash
$PY -m roomkit.cli build --manifest M.json --out DIR --site-pack roomkit/packs/example/
```

Without `--site-pack`, a build uses the manifest's site's pack (`site.template`, looked up in `packs/`, then `sites/packs/`), else `packs/default/`. A manifest that names its `site.template` refuses a pack for another site.

`tests/roomkit/test_golden.py` pins both shipped packs byte for byte: `plain` (default: rows, the folded jump list), `example` (cards, the toggle, empty groups) and `example-folded` (cards with the folded jump list, under another mount, noindex).
