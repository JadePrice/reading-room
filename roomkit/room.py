"""The one page template every reading room uses: document page, index, 404,
and (pack features.entities) the entity index and entity pages, (pack
features.collections) the collections page and collection pages.

Both sites' WordPress plugins grew their own templates around the shared
reader engine (site B's and site A's reading-room plugins). This is the
union of the two, taking the better part of each:

- from site A: breadcrumbs, the provenance rail beside the reader, a sensitivity
  notice, entity groups that say what kind of claim each link is, related
  records, a light/dark toggle, an index with counts and filters;
- from site B: jump links, grouped sections an index can be browsed by without
  JavaScript, cards with page-one thumbnails, empty groups said out loud.

The markup lives in Jinja templates (`templates/room/`), the same files the
host application's reading room will render live. Their input is a plain view-model dict (`view.py`), so no
template touches roomkit internals. This module is the environment and a thin
render call:

- autoescape on, StrictUndefined (a key the view model lacks is an error, not
  an empty string), and no filters that format dates or compose labels;
- escaping is `html.escape`, applied in `finalize`. markupsafe would write `"`
  and `'` as `&#34;`/`&#39;` where 0.3.0 wrote `&quot;`/`&#x27;`; keeping the
  stdlib's keeps every page byte-identical to the string template it replaced
  (tests/roomkit/test_golden.py). Markup (macro output) passes through
  unchanged.

A site differs only in its site pack (`packs/<site>/pack.json`, `pack.py`:
colors, fonts, labels, layout, features, chrome) and its content (the manifest's `display`/`index` blocks, made by the
site's own helpers). Nothing here formats a date or composes a label.

The page is the room's whole: it draws its own header, navigation and footer
from the pack's `chrome` (`partials/chrome-*.html`, `chrome.css`, both scoped
under `body.room-plain`). Nothing is captured from WordPress.

Styles (`templates/room/room.css`) are scoped under `#room-content`. That began
as the site B contrast fix of 2026-10-12, when a captured site theme loaded beside
them and its light text took over white panels. It still keeps the content's
rules apart from the chrome's.
"""

from __future__ import annotations

from html import escape
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup

from . import view as V
from .manifest import Document, Manifest

TEMPLATES = Path(__file__).resolve().parent / "templates"
slugify = V.slugify


def _finalize(v: object) -> object:
    if isinstance(v, Markup):
        return v
    if isinstance(v, str):
        return Markup(escape(v, quote=True))
    if isinstance(v, int) and not isinstance(v, bool):
        return str(v)
    raise TypeError(f"the view model put a {type(v).__name__} where text goes: {v!r}")


ENV = Environment(loader=FileSystemLoader(str(TEMPLATES)), autoescape=True, undefined=StrictUndefined,
                  trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True, finalize=_finalize)


def render(template: str, view: dict) -> str:
    return ENV.get_template(template).render(view)


def doc_main(doc: Document, m: Manifest, at: str, pack: dict) -> str:
    """The content element of one document page."""
    return render("room/document.html", V.doc_view(doc, m, at, pack))


def index_main(m: Manifest, at: str, pack: dict) -> str:
    return render("room/index.html", V.index_view(m, at, pack))


def entity_index_main(m: Manifest, at: str, pack: dict) -> str:
    """The entity index. `m` as entities.gate(m, pack) returns it."""
    return render("room/entities.html", V.entity_index_view(m, at, pack))


def entity_main(page: dict, m: Manifest, at: str, pack: dict) -> str:
    """One entity page (an entry of m.entities["pages"])."""
    return render("room/entity.html", V.entity_view(page, m, at, pack))


def collections_index_main(m: Manifest, at: str, pack: dict) -> str:
    """The collections page. `m` as site_collections.gate(m, pack) returns it."""
    return render("room/collections.html", V.collections_index_view(m, at, pack))


def collection_main(page: dict, m: Manifest, at: str, pack: dict) -> str:
    """One collection page (an entry of m.collections["pages"])."""
    return render("room/collection.html", V.collection_view(page, m, at, pack))


def topics_index_main(m: Manifest, at: str, pack: dict) -> str:
    """The topics page. `m` as topics.gate(m, pack) returns it."""
    return render("room/topics.html", V.topics_index_view(m, at, pack))


def topic_main(page: dict, m: Manifest, at: str, pack: dict) -> str:
    """One page of one topic (an entry of m.topics["pages"])."""
    return render("room/topic.html", V.topic_view(page, m, at, pack))


def not_found_main(m: Manifest, at: str, pack: dict) -> str:
    return render("room/404.html", V.not_found_view(m, at, pack))


ROOM_CSS = (TEMPLATES / "room" / "room.css").read_text(encoding="utf-8")

# The room's own header, navigation and footer (templates/room/chrome.css); it
# follows ROOM_CSS in the same stylesheet.
CHROME_CSS = (TEMPLATES / "room" / "chrome.css").read_text(encoding="utf-8")
CHROME_WIDE_CSS = (TEMPLATES / "room" / "chrome-wide.css").read_text(encoding="utf-8")


def chrome_css(pack: dict) -> str:
    """The chrome's styles: chrome.css, then the wide-screen
    rules at the pack's own `chrome.inline_from`. A media query cannot read a custom
    property, so the width is written in when the stylesheet is built. The schema holds
    the value to a plain em length, so it cannot break out of the rule."""
    css = CHROME_CSS
    chrome = pack.get("chrome")
    if chrome:
        w = chrome["inline_from"]
        # The bar keeps the page column's width (chrome.css) at every width, so the brand and the
        # content share an edge; only inline_from decides when the links fold into the Menu.
        css += (f"@supports selector(::details-content){{@media (min-width:{w}){{\n" + CHROME_WIDE_CSS
                + "}}\n")
    return css

# The index finder and the light/dark toggle (templates/room/room.js). Filters
# run on the cards already in the page (title, summary, agency, group, date,
# facets); the query stays in the URL (?q=&group=...) so a filtered view can be
# shared. Full-text search across documents is Pagefind's job (search.py).
ROOM_JS = (TEMPLATES / "room" / "room.js").read_text(encoding="utf-8")

# The site's accessibility toolbar (pack a11y_toolbar; templates/room/room-a11y.js, ported
# from the wp-accessibility plugin). Without the pack key it does not ship.
ROOM_A11Y_JS = (TEMPLATES / "room" / "room-a11y.js").read_text(encoding="utf-8")

# With the pack's corpus-search on, the index's finder is room-search.js instead
# (text search and suggestions from the room's Pagefind index, the same facet
# filters), styled by search.css. Without it neither ships, and room.js keeps
# the finder.
ROOM_SEARCH_JS = (TEMPLATES / "room" / "room-search.js").read_text(encoding="utf-8")
SEARCH_CSS = (TEMPLATES / "room" / "search.css").read_text(encoding="utf-8")

# Entity index and entity pages (pack features.entities), styled by entities.css.
# Without the feature it does not ship.
ENTITIES_CSS = (TEMPLATES / "room" / "entities.css").read_text(encoding="utf-8")
# The collections page, collection pages and the index's collections table (pack
# features.collections), styled by collections.css; room-collections.js runs their
# search, filters and sorts. Without the feature neither ships.
COLLECTIONS_CSS = (TEMPLATES / "room" / "collections.css").read_text(encoding="utf-8")
ROOM_COLLECTIONS_JS = (TEMPLATES / "room" / "room-collections.js").read_text(encoding="utf-8")
# The topics page and topic pages (pack features.topics), styled by topics.css.
TOPICS_CSS = (TEMPLATES / "room" / "topics.css").read_text(encoding="utf-8")
# The RoomTools seam (tools.py): a "Reading tools" menu, status line and preferences store the
# optional tools share. Ships only when a tool that registers with it is on.
ROOM_TOOLS_JS = (TEMPLATES / "room" / "room-tools.js").read_text(encoding="utf-8")
ROOM_TOOLS_CSS = (TEMPLATES / "room" / "room-tools.css").read_text(encoding="utf-8")
# The read-aloud panel (pack features.read-aloud), drawn from the room's tokens.
READ_ALOUD_CSS = (TEMPLATES / "room" / "read-aloud.css").read_text(encoding="utf-8")
# The record's text page (pack features.page-text; page_text.py).
PAGE_TEXT_CSS = (TEMPLATES / "room" / "text.css").read_text(encoding="utf-8")
# The index's List / Gallery switch (pack layout.gallery): gallery.css is added to
# room.css and room-gallery.js loads on the index. Without the switch neither ships.
GALLERY_CSS = (TEMPLATES / "room" / "gallery.css").read_text(encoding="utf-8")
ROOM_GALLERY_JS = (TEMPLATES / "room" / "room-gallery.js").read_text(encoding="utf-8")
# Pages of records on the index and the facet pages (pack layout.page_size): pager.css
# is added to room.css and room-pager.js loads there, with the size written in.
PAGER_CSS = (TEMPLATES / "room" / "pager.css").read_text(encoding="utf-8")
ROOM_PAGER_JS = (TEMPLATES / "room" / "room-pager.js").read_text(encoding="utf-8")


def pager_js(size: int) -> str:
    return ROOM_PAGER_JS.replace("__PAGE_SIZE__", str(int(size)))


# The index's browse block and the facet pages (pack features.facet-pages; browse.py).
BROWSE_CSS = (TEMPLATES / "room" / "browse.css").read_text(encoding="utf-8")
