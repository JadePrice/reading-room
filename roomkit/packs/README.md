# Site packs

A site pack is the one place a site customizes the shared reading room. Anything a site can change is in its pack; anything not in a pack is the same for every site. In Civica, a pack becomes the tenant's theme, validated against the same schema.

```
packs/
  pack.schema.json        the structure (JSON Schema 2020-12), shared with Civica
  default/pack.json       the plain room, light and dark from the system setting
  deflockdane/pack.json   dd's dark civic look, cards, empty groups shown
  glassgovernment/pack.json  GG's archival look, rows, light/dark toggle (ggrr-theme)
  hrtarchive/pack.json    a demo pack (plan Task 6): the trans-flag archive palette, cards
```

## What a pack holds

| Key | What it is |
|---|---|
| `identity` | `site` (matches a manifest's `site.template`), `name`, `base_url`, optional `logo`/`favicon` (files in the pack), and `backdrop`: the color behind a transparent `page-bg`. The contrast check measures against it, and the page paints its body with it |
| `tokens`, `tokens_dark` | the `--room-*` values (`room.TOKENS`); every color token is required, light and (if present) dark |
| `reader`, `reader_dark` | optional `--rr-*` overrides for the reader engine |
| `fonts` | self-hosted font files in the pack. No CDN |
| `chrome` | what the room draws around itself: its header, navigation and footer. Required: `home` (the site's name and link), `skip_text`, `nav_label` (the nav's accessible name), `menu_label` (the narrow-screen menu's summary), `inline_from` (an em width from which the links sit in one row; measured per site). Optional: `tagline`, `nav` (links, or `{label, links}` groups), `notice` (a line under the header), `footer` (link columns, heading optional), `footer_text` (paragraphs, verbatim), `source` (where it was taken from: `url`, `date`; not rendered). Links back to the live site are absolute ([../README.md](../README.md), "The room's own chrome") |
| `labels` | required: `group` (the group as a label, e.g. "Category"; the only source of the group noun), `jump` (the jump list's label; the nav's accessible name is this minus trailing punctuation) and the count nouns `group_singular`, `groups_plural`, `record_singular`, `record_plural`. The room picks the singular for a count of 1 and never builds a plural (no `+"s"`). Optional: room, other group, jump text, search placeholder, "Released", and `stats_singular`/`stats_plural` for the index header's count when the site names it apart from the result count (GG: "455 documents" over "455 records") |
| `layout` | `style` (`cards`/`rows`), `show_empty_groups`, `toggle` (a localStorage key shared with the site, or empty) |
| `features` | one switch per surface (`pack.schema.json` lists each with what it builds). The template renders a surface only when the pack turns it on and the manifest supports it. On as of 2026-10-21: GG has collections, entities, facet-pages, machine-text, server-search, sitemaps and topics; dd has corpus-search, entities, facet-pages, server-search and sitemaps; default and hrtarchive have none |
| `extra_css` | an escape hatch, scoped under `#room-content` |

## What is refused

`pack.py` runs the schema, then the checks a schema cannot state. Every problem is listed, and a refused pack is refused whole (`roomkit build --site-pack` exits 2 and writes nothing).

- **Structure** (the schema): an unknown key anywhere, a token name the room does not have, a value that could break out of CSS (`;`, `{`, `}`, `<`, `>`, in a token or the backdrop), a chrome entry missing a required field or a nav item that is both a link and a group, a nav or footer URL that is not `https://` or a same-host path, a pack file path that leaves the pack.
- **A missing color token**, light or dark.
- **Contrast below 4.5:1 for text or 3:1 for focus rings and button fills**, for every pair the template paints (`pack.PAIRS`), light and dark. Colors are hex or `oklch()`, alpha included (`color.py`). Anything else (`var()`, named colors) cannot be measured and is refused. A `transparent` page needs `identity.backdrop`. This would have caught dd's 1.29:1 white panels of 2026-10-12 at build time.
- **`extra_css` outside the room**: a rule not under `#room-content` (or the plain page's own `body.room-plain`).
- **A feature the parity matrix drops**: on, while every matrix row behind it is `dropped`.
- **A logo, favicon or font that is not a file in the pack.**

## Tokens come from the site's design tokens

A pack does not copy hex values by hand. `tokens.map.json` beside it maps each room token to a variable in the site's `design-tokens/<site>.tokens.css`, and `roomkit pack import` writes the pack's `tokens` from it:

```bash
$PY -m roomkit.cli pack import --map roomkit/packs/deflockdane/tokens.map.json          # what would change
$PY -m roomkit.cli pack import --map roomkit/packs/deflockdane/tokens.map.json --write  # write it
```

- The map is complete: the pack's tokens become exactly the mapped and `literal` entries.
- A value that does not come from the file is a `literal` and must say `why`; a mapped value may too. Every `why` lands in the pack's `token_notes`, so each value that is not simply the site's is explained in the pack.
- **Refused:** a variable the file does not define, defines twice at the top level, or cannot resolve (`tokens_css.py`); a map key the room does not have; a token both mapped and literal; a literal without a why; and any pack `pack.py` would refuse (contrast included).
- `@media` variants (`prefers-contrast: more`) are listed, not imported.
- `tests/roomkit/test_pack_import.py` re-derives every shipped pack from its map: a hand edit to a pack's tokens fails it.

Where the packs stand (decided 2026-10-13):

| Pack | Source | Values |
|---|---|---|
| `deflockdane` | `design-tokens/deflockdane.tokens.css` | the site's own (`--dl-*`). Changed from the hand-written theme: muted text #a3b1c4 -> #7a8799, links #7cb8fb -> #60a5fa, accent/focus #fbbf24 (the high-contrast variant) -> #f59e0b, radius 10px -> 6px, fonts resolved stacks. Literal: `page-bg` (the room sits on dd's page), `on-accent` (no on-amber color in the file) |
| `glassgovernment` | `design-tokens/glassgovernment.tokens.css` | all literal: the gg-reading-room plugin palette, which the site theme file does not hold. Kept for parity with the WordPress room; revisit at the Task 5 design review |
| `hrtarchive` | `design-tokens/hrtarchive.tokens.css` | the site's own, all mapped (archive surface: `--bg-main`, `--trans-blue`, `--trans-pink` focus, translucent `rgba()` panels). A demo pack: hrtarchive's own serving does not change |
| `default` | none | roomkit's own plain room |

## The room is generic

hrtarchive is the site the template was never shaped around, and the test of "customizable to fit" (plan Task 6). Its pack builds `tests/roomkit/fixtures/hrtarchive-mini.json` (five synthetic public records) with no change to the templates or `room.css`. The only code it needed was generic: `color.py` learned CSS `rgb()`/`rgba()`, which hrtarchive's translucent panels use.

`tests/roomkit/test_generic.py` holds the rule for all four packs, pair by pair: give one pack another's `layout`, `labels`, `features` and `chrome`, and every page is byte-identical to the other's, whatever its identity, tokens, `extra_css` or notes. Tokens reach only the stylesheet, after the shared `room.css`. A template that branched on which site it renders would fail it.

## Using one

```bash
$PY -m roomkit.cli build --manifest M.json --out DIR --site-pack roomkit/packs/deflockdane/
```

Without `--site-pack`, a build uses the manifest's site's pack (`site.template`), else `packs/default/`. A manifest that names its `site.template` refuses a pack for another site.

The three packs carry the values of the themes they replaced (`themes/*.py`, removed) unchanged; the build is byte-identical (`tests/roomkit/test_golden.py`, `test_pack.py`).
