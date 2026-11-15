"""Render a static reading room from a manifest, entirely in memory.

`render()` returns every output file as bytes keyed by its path in the tree.
`build` writes that; `check` compares it with what is on disk. One code path,
so a check can never pass a tree the build would not have made.

Output is deterministic: no timestamps, sorted keys, documents in a fixed
order. Same manifest and engine, same bytes.

    index.html                       the list of documents
    404.html                         what a missing path gets, without WordPress
    <slug>/index.html                one page per document (reader + no-JS fallback + citation)
    <slug>/pages.<hash>.json         page texts, when the manifest carries them
    <slug>/text/index.html           the page text as HTML, and <slug>/<slug>.txt as a download (pack features.page-text; page_text.py)
    assets/thumbs/<slug>.<hash>.<ext>  a card's thumbnail, when the manifest carries it (index.thumb)
    assets/room.<hash>.css           the shared styles, the room's chrome, the site pack's tokens (templates/room/)
    assets/room.<hash>.js            index filters and the light/dark toggle
    assets/rr-config.<hash>.js       window.rrReaderConfig for the engine
    assets/vendor/rr-reader/...      the shared engine, verbatim
    assets/vendor/pdfjs/...          pdf.js as the engine pins it
    assets/rr-read-aloud.<hash>.js   the read-aloud player (pack features.read-aloud), on records with page texts
    assets/room-tools.<hash>.js      the RoomTools seam (tools.py), only when a tool that registers with it is on
    assets/room-search.<hash>.js     the finder's text search and suggestions (pack features.corpus-search)
    assets/theme/<name>.<hash>.<ext>  the site theme's fonts, logo and icon, from the pack (pack `fonts`,
                                     identity.logo, identity.favicon; mapped by theme_map.py)
    collections/index.html, collection/<key>/index.html
                                     the site's collections page and collection pages, at their
                                     live paths (pack features.collections, manifest
                                     `collections`; site_collections.py), with the collections
                                     table on the index
    documents.txt                    the site's plain-text record index as exported (pack
                                     features.machine-text, manifest `machine_text`;
                                     machine_text.py)
    topics/index.html, topics/<t>/index.html, topics/<t>/page/<n>/index.html
                                     the site's topics page and every page of every topic
                                     (pack features.topics, manifest `topics`; topics.py)
    entities/index.html, entity/<type>/<slug>/index.html
                                     the site's entity index and pages, at their live paths
                                     (pack features.entities, manifest `entities`; entities.py)
    <facet>/<value>/index.html       one page per facet value, linked from the index's browse block
                                     (pack features.facet-pages, site.index.browse; browse.py)
    sitemap.xml                      every page above by its live URL (pack features.sitemaps)
    pagefind/...                     the Pagefind index over every record (same switch; search.py)
    citations.json                   site A's curated citations by stable_key, and each page's site
                                     citation in pages.json (pack features.passage-cite,
                                     manifest `passages`; passages.py)
    .htaccess                        cache headers and the 404 page (Apache/LiteSpeed hosts)
    .nginx.conf                      the same rules as one nginx location, for a pack with `nginx.root` (site A)
    room.lock.json                   sha256 of every file above, logical -> published asset names, the pack's hash

Caching. Every asset and pages.json carries a content hash in its name, so it
can be cached for a year as immutable: a new build is new names, never a stale
file. HTML is the only thing that changes in place; it revalidates in the
browser and is what a publish purges from the edge (`roomkit diff`).

Every page is the one shared template (Jinja, `roomkit/templates/room/`,
fed a plain view model from `view.py`, rendered by `room.py`). The page is the
room's own: it draws its header, navigation and footer from the site pack's
`chrome` (`packs/<site>/pack.json`), which also gives its tokens, labels and
layout. Nothing is captured from WordPress. The one exception is a
page's <title> and meta tags, which with pack features.head-meta are the ones
the exporter wrote for that page (manifest `head_meta`; head_meta.py). A pack
with a mapped theme (pack `theme`, theme_map.py) carries the theme's fonts, logo
and icon as its own files, read from the parity repo and the site's page when
the pack is imported, never when the room is built.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

from . import browse as B
from . import css as CSS
from . import entities as E
from . import head_meta as HM
from . import machine_text as MT
from . import pack as P
from . import page_text as PT
from . import passages as PS
from . import redirects as RD
from . import room as R
from . import search as S
from . import site_collections as CO
from . import tools as T
from . import topics as TP
from . import view as V
from .manifest import (
    IMAGE,
    PDF,
    READER,
    TABLE,
    TEXT,
    Document,
    Manifest,
    ManifestError,
    thumb_bytes,
    validate_room_path,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
if not (REPO_ROOT / "reading-room-reader").is_dir() and (REPO_ROOT.parent / "reading-room-reader").is_dir():
    REPO_ROOT = REPO_ROOT.parent
ENGINE = REPO_ROOT / "reading-room-reader"
# The browser-only read-aloud player (pack features.read-aloud). It lives beside the
# engine, not in it (reading-room-reader/read-aloud/README.md), so the room reads it from there.
READ_ALOUD_JS = ENGINE / "read-aloud" / "rr-read-aloud.js"
# Where a pack is found by its site's name: the packs shipped with roomkit (packs/),
# then the sites layer's (sites/packs/, private; absent from the public mirror).
PACK_DIRS = (P.PACKS, Path(__file__).resolve().parent / "sites" / "packs")
LOCK = "room.lock.json"
ROOMKIT_VERSION = "0.3.0"
HTACCESS = ".htaccess"
NGINX = ".nginx.conf"
HEADERS_ROOM = "_headers.room"
SERVER_CONFIG = (HTACCESS, NGINX, HEADERS_ROOM)
# Cache policy (see the module docstring). s-maxage lets an edge cache hold HTML
# for an hour between purges; browsers always revalidate it.
CACHE_ASSET = "public, max-age=31536000, immutable"
CACHE_HTML = "public, max-age=0, s-maxage=3600, must-revalidate"
# The policy `features.csp` sends. The room's own scripts are all external files (no
# inline executable script: JSON-LD and the suggest data are data blocks), so script-src
# is 'self' alone; 'wasm-unsafe-eval' is for Pagefind's WebAssembly, not for eval().
# style-src keeps 'unsafe-inline' because the reader modules inject a <style> element.
CSP = "; ".join([  # noqa: FLY002 - one directive per line
    "default-src 'self'",
    "script-src 'self' 'wasm-unsafe-eval'",
    "worker-src 'self' blob:",
    "style-src 'self' 'unsafe-inline'",
    "img-src 'self' data: blob:",
    "font-src 'self'",
    "connect-src 'self'",
    "object-src 'self'",
    "frame-src 'self'",
    "media-src 'self'",
    "base-uri 'self'",
    "form-action 'self'",
    "frame-ancestors 'self'",
])
# `features.csp-strict`: the same policy with no plugins and no <base>. A site whose
# own deploy audit requires both (first needed 2026-11-02) turns it on in its pack. The cost is the no-JS <noscript><object> PDF embed: it shows its fallback
# text instead, beside the Open/Download links that are always on the page.
CSP_STRICT = CSP.replace("object-src 'self'", "object-src 'none'").replace(
    "base-uri 'self'", "base-uri 'none'")


def _policy(csp: bool | str) -> str:
    """A `csp` argument as the header value: True is CSP, a string is itself."""
    return csp if isinstance(csp, str) else (CSP if csp else "")


def _pack_csp(pack: dict) -> str:
    features = pack.get("features", {})
    if features.get("csp-strict"):
        return CSP_STRICT
    return CSP if features.get("csp") else ""


FINGERPRINT = re.compile(r"\.[0-9a-f]{12}\.[a-z0-9]+$")

def _module(ext: str) -> str:
    if ext in PDF:
        return "rr-reader-pdf.js"
    if ext in IMAGE or ext in ("tiff", "tif"):
        return "rr-reader-image.js"
    if ext in TABLE:
        return "rr-reader-table.js"
    if ext in TEXT:
        return "rr-reader-text.js"
    raise ValueError(ext)  # manifest.parse already refused it


def _engine_scripts(doc: Document, at: str) -> list[str]:
    if doc.is_snapshot:
        assets = at + "assets/"
        return [f"{assets}rr-config.js", f"{assets}vendor/rr-reader/rr-reader.js",
                f"{assets}vendor/rr-reader/modules/rr-reader-archive.js"]
    if doc.ext not in READER:
        return []
    assets = at + "assets/"
    scripts = [f"{assets}rr-config.js", f"{assets}vendor/rr-reader/rr-reader.js"]
    if doc.ext in PDF:
        scripts.append(f"{assets}vendor/pdfjs/pdf.min.js")
    scripts.append(f"{assets}vendor/rr-reader/modules/{_module(doc.ext)}")
    return scripts


def _config(at: str, passage_url: str = "", replay: bool = False) -> str:
    vendor = at + "assets/vendor/"
    cfg = {
        "pdfJsUrl": vendor + "pdfjs/pdf.min.js",
        "pdfWorkerUrl": vendor + "pdfjs/pdf.worker.min.js",
        # No search route: search comes from each page's data-pages-url (engine
        # static mode). The passage route is the site's, and only with the pack's
        # passage-cite switch (passages.py); without it citations stay with the
        # page's own citation text.
        "docSearchUrl": "",
        "passageUrl": passage_url,
    }
    if replay:
        cfg["replayBase"] = vendor + "replaywebpage/"
    return "window.rrReaderConfig = " + json.dumps(cfg, sort_keys=True) + ";\n"


def _engine_files(engine: Path) -> dict[str, bytes]:
    out = {"assets/vendor/rr-reader/rr-reader.js": (engine / "src/rr-reader.js").read_bytes(),
           "assets/vendor/rr-reader/VERSION": (engine / "VERSION").read_bytes()}
    for mod in sorted((engine / "src/modules").glob("*.js")):
        out[f"assets/vendor/rr-reader/modules/{mod.name}"] = mod.read_bytes()
    for name in ("pdf.min.js", "pdf.worker.min.js"):
        out[f"assets/vendor/pdfjs/{name}"] = (engine / "vendor/pdfjs" / name).read_bytes()
    return out


# --- pages: the shared templates, in the room's own chrome ---------------------

def pack_dir(site: str) -> Path:
    """The directory of the pack shipped for `site`: packs/<site>/, else sites/packs/<site>/
    (packs/<site>/ when neither exists, so a refusal names the usual place)."""
    return next((d / site for d in PACK_DIRS if (d / site).is_dir()), P.PACKS / site)


def pack_for_site(site: str) -> dict:
    """The pack shipped for `site`, validated (pack.load), wherever it is kept (PACK_DIRS)."""
    return P.load(pack_dir(site))


def _pack(m: Manifest, pack: dict | None) -> dict:
    """The site pack: the one given; else the manifest's site's; else the default."""
    if pack is None:
        return pack_for_site(m.site.template or "default")
    # A manifest that names its site gets that site's pack.
    if m.site.template and pack["identity"]["site"] != m.site.template:
        raise ValueError(f"pack is for {pack['identity']['site']!r}, manifest template is {m.site.template!r}")
    return pack


def _page(main: str, content: dict, at: str, head: dict, scripts: list[str], pack: dict) -> str:
    """One page: the room's content element in the room's own chrome from the pack."""
    return R.render("room/base.html", V.page_view(main, content, at, head, scripts, V.chrome_view(pack, at)))


def _has_mount(doc: Document) -> bool:
    """Whether the record page carries a reader mount (the engine fills it; the tools menu follows it)."""
    return doc.is_snapshot or doc.ext in READER


def _doc_page(doc: Document, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # `at` is where this tree is served (room_path, or a staging mount).
    # Canonical links always name the live room_path URL.
    s = m.site
    canonical = f"{s.base_url}{s.room_path}{doc.slug}/"
    head = HM.head(m.head_meta, f"{doc.slug}/",
                   V.head(f"{doc.title} | {s.title}", noindex, canonical,
                          V.social(doc.title, doc.summary, canonical, doc.poster_url, s.title),
                          V.jsonld(doc.display["jsonld"]) if doc.display.get("jsonld") else ""))
    scripts = [*_engine_scripts(doc, at), f"{at}assets/vendor/rr-reader/modules/rr-cite.js"]
    if T.seam_on(pack) and _has_mount(doc):
        scripts.append(f"{at}assets/room-tools.js")  # before the tools that register with it
    if V.read_aloud_on(doc, pack):
        scripts.append(f"{at}assets/rr-read-aloud.js")
    return _page("room/document.html", V.doc_view(doc, m, at, pack), at, head, scripts, pack)


def _text_page(doc: Document, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    """The record's text page. Its canonical names the live URL, as a record page's does. A pack
    that does not index text pages (page_text.index, D1) sends the lighter `noindex`."""
    s = m.site
    canonical = f"{s.base_url}{s.room_path}{PT.text_path(doc)}"
    head = V.head(f"Text of {doc.title} | {s.title}", noindex, canonical,
                  V.social(f"Text of {doc.title}", PT.LABEL, canonical, "", s.title))
    if not noindex and not PT.indexed(pack):
        head = {**head, "noindex_only": True}
    return _page("room/text.html", V.text_view(doc, m, at, pack), at, head, [], pack)


def _index_page(m: Manifest, at: str, noindex: bool, pack: dict, facet_pages: list[dict]) -> str:
    s = m.site
    canonical = s.base_url + s.room_path
    title = s.index.get("title") or s.title
    head = HM.head(m.head_meta, "",
                   V.head(title, noindex, canonical, V.social(title, s.index.get("lede", ""), canonical, "", s.title)))
    scripts = [f"{at}assets/room-search.js"] if S.enabled(pack) else []
    if m.collections and m.collections.get("grid"):
        scripts.append(f"{at}assets/room-collections.js")
    if V.gallery_on(pack):
        scripts.append(f"{at}assets/room-gallery.js")
    if V.page_size(pack):
        scripts.append(f"{at}assets/room-pager.js")
    return _page("room/index.html", V.index_view(m, at, pack, facet_pages, B.heading(m)), at, head, scripts, pack)


def _facet_page(p: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    s = m.site
    canonical = s.base_url + s.room_path + p["path"]
    head = V.head(f"{p['title']} | {s.title}", noindex, canonical,
                  V.social(p["title"], "", canonical, "", s.title))
    scripts = [f"{at}assets/room-pager.js"] if V.page_size(pack) else []
    return _page("room/facet.html", V.facet_view(p, m, at, pack), at, head, scripts, pack)


def _facet_root_page(f: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    s = m.site
    canonical = s.base_url + s.room_path + f["path"]
    head = V.head(f"{f['label']} | {s.title}", noindex, canonical, V.social(f["label"], "", canonical, "", s.title))
    f = {**f, "values": [{**v, "url": at + f["path"] + v["slug"] + "/"} for v in f["values"]]}
    return _page("room/facet-root.html", V.facet_root_view(f, m, at, pack), at, head, [], pack)


def _entity_index_page(m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    ix = m.entities["index"]
    head = HM.head(m.head_meta, ix["path"],
                   V.head(ix["head_title"], noindex, ix["url"],
                          V.social(ix["title"], ix.get("description", ""), ix["url"], "", m.site.title)))
    return _page("room/entities.html", V.entity_index_view(m, at, pack), at, head, [], pack)


def _entity_page(p: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # The canonical and the JSON-LD name the live URL, as on a record page.
    head = HM.head(m.head_meta, p["path"],
                   V.head(p["head_title"], noindex, p["url"],
                          V.social(p["title"], p.get("description", ""), p["url"], "", m.site.title),
                          V.jsonld(p["jsonld"]) if p.get("jsonld") else ""))
    return _page("room/entity.html", V.entity_view(p, m, at, pack), at, head, [], pack)


def _collections_index_page(m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    ix = m.collections["index"]
    head = HM.head(m.head_meta, ix["path"],
                   V.head(ix["head_title"], noindex, ix["url"],
                          V.social(ix["title"], ix.get("lede", ""), ix["url"], "", m.site.title)))
    return _page("room/collections.html", V.collections_index_view(m, at, pack), at, head,
                 [f"{at}assets/room-collections.js"], pack)


def _collection_page(p: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # The canonical and the JSON-LD name the live URL, as on a record page.
    head = HM.head(m.head_meta, p["path"],
                   V.head(p["head_title"], noindex, p["url"],
                          V.social(p["title"], p.get("blurb") or p.get("description", ""), p["url"], "", m.site.title),
                          V.jsonld(p["jsonld"]) if p.get("jsonld") else ""))
    return _page("room/collection.html", V.collection_view(p, m, at, pack), at, head,
                 [f"{at}assets/room-collections.js"] if p.get("search") else [], pack)


def _topics_index_page(m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    ix = m.topics["index"]
    head = HM.head(m.head_meta, ix["path"],
                   V.head(ix["head_title"], noindex, ix["url"],
                          V.social(ix["title"], ix["subtitle"], ix["url"], "", m.site.title)))
    return _page("room/topics.html", V.topics_index_view(m, at, pack), at, head, [], pack)


def _topic_page(p: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # The canonical and the JSON-LD name the live URL; each /page/N/ is its own canonical, as live.
    head = HM.head(m.head_meta, p["path"],
                   V.head(p["head_title"], noindex, p["url"],
                          V.social(p["title"], p["subtitle"], p["url"], "", m.site.title),
                          V.jsonld(p["jsonld"]) if p.get("jsonld") else ""))
    return _page("room/topic.html", V.topic_view(p, m, at, pack), at, head, [], pack)


def _404_page(m: Manifest, at: str, pack: dict) -> str:
    head = V.head(f"Not found | {m.site.title}", True)
    return _page("room/404.html", V.not_found_view(m, at, pack), at, head, [], pack)


def _search_handoff(m: Manifest, at: str, pack: dict) -> str:
    """The server-search param the room must hand back to the site, or "".

    Only when the room is mounted at the URL that search answers (site B's cutover:
    the room at /reading-room/, the form at /reading-room/?rr_search=). Apache
    then finds the room's directory and serves index.html, so WordPress would
    never see the query. A room mounted anywhere else (staging) sends its form to
    the live URL, which WordPress still serves, and needs nothing.
    """
    ss = m.site.index.get("server_search")
    if not (ss and pack.get("features", {}).get("server-search")):
        return ""
    return ss["param"] if urlparse(ss["action"]).path == at else ""


def _topic_handoffs(m: Manifest, at: str, pack: dict) -> tuple[str, ...]:
    """The in-topic search params WordPress must answer: as _search_handoff, only for
    a room served at the live room_path, where the forms' live topic URLs land."""
    if not (m.topics and pack.get("features", {}).get("server-search") and at == m.site.room_path):
        return ()
    return tuple(sorted({p["search"]["param"] for p in m.topics["pages"] if p.get("search", {}).get("param")}))


def _exts(images: bool, theme: tuple[str, ...]) -> str:
    """The hashed-asset extensions a room serves: always css/js/json, thumbnails'
    and the theme's files only in a room that ships them (a room without changes no byte)."""
    out = ["css", "js", "json"] + (["jpg", "png", "webp"] if images else [])
    return "|".join(out + sorted(set(theme) - set(out)))


def _htaccess(at: str, images: bool = False, csp: bool | str = False, text: bool = False,
              search_param: str = "", theme: tuple[str, ...] = (),
              moved: list[tuple[str, str]] | tuple = ()) -> str:
    # Thumbnails are hashed assets too; their extensions are named only in a room
    # that ships them, so a room without changes no byte. The same for machine text:
    # a .txt file is a page (the HTML cache policy) in UTF-8, as the site sends it.
    exts = _exts(images, theme)
    # A RewriteEngine here replaces the parent's WordPress block for everything
    # under the room, so it repeats that block's fallback: the routes the room has
    # no file for (site B's /<slug>/file/ and /thumb/) still reach WordPress.
    handoff = [
        "<IfModule mod_rewrite.c>",
        "RewriteEngine On",
        f"RewriteCond %{{QUERY_STRING}} (^|&){search_param}= [NC]",
        "RewriteRule ^(index\\.html)?$ /index.php [L]",
        "RewriteCond %{REQUEST_FILENAME} !-f",
        "RewriteCond %{REQUEST_FILENAME} !-d",
        "RewriteRule . /index.php [L]",
        "</IfModule>",
    ] if search_param else []
    return "\n".join([
        "# Written by roomkit. Cache policy: build.py module docstring.",
        f"ErrorDocument 404 {at}404.html",
        *RD.htaccess_lines(at, list(moved)),
        *handoff,
        *(["AddCharset UTF-8 .txt"] if text else []),
        "<IfModule mod_headers.c>",
        f'<FilesMatch "\\.[0-9a-f]{{12}}\\.({exts})$">',
        f'Header set Cache-Control "{CACHE_ASSET}"',
        "</FilesMatch>",
        '<FilesMatch "\\.(html|txt)$">' if text else '<FilesMatch "\\.html$">',
        f'Header set Cache-Control "{CACHE_HTML}"',
        "</FilesMatch>",
        *([f'Header always set Content-Security-Policy "{_policy(csp)}"'] if csp else []),
        "</IfModule>",
        "",
    ])


def _nginx(at: str, root: str, images: bool = False, csp: bool | str = False, text: bool = False,
           search_param: str = "", topic_params: tuple[str, ...] = (), theme: tuple[str, ...] = (),
           moved: list[tuple[str, str]] | tuple = ()) -> str:
    """The .htaccess's rules for an nginx host (pack `nginx.root`, site A's $SITE_A_HOST).

    One location the site's server block includes. A file the room has is served
    from `root` with the .htaccess's cache headers; anything else (site A's
    /<slug>/file/, /page/N/ past the export, a search) falls to /index.php, which
    WordPress answers by the original URI, as the .htaccess's fallback does. Run
    against a real nginx in tests/roomkit/sites/test_nginx_conf.py.
    """
    exts = _exts(images, theme)
    q = re.escape(at)

    def headers(cache: str) -> list[str]:
        # add_header is inherited only by a block with none of its own, so each block repeats them.
        return [f'        add_header Cache-Control "{cache}";',
                *([f'        add_header Content-Security-Policy "{_policy(csp)}" always;'] if csp else [])]

    def handoff(path_re: str, param: str) -> list[str]:
        # rewrite...last is one of the two things that are safe inside `if` in a location.
        return [f'    location ~ "{path_re}" {{',
                f'        if ($args ~ "(^|&){param}=") {{ rewrite ^ /index.php last; }}',
                *headers(CACHE_HTML),
                "        try_files $uri $uri/ /index.php?$args;",
                "    }"]

    return "\n".join([
        "# Written by roomkit: the room's .htaccess rules for nginx (build.py _nginx).",
        f"location ^~ {at} {{",
        f"    root {root};",
        "    index index.html;",
        # A directory without its slash redirects relative to the request, not to
        # http://<server_name>/ (Cloudflare reaches the origin over :80).
        "    absolute_redirect off;",
        *(["    charset utf-8;"] if text else []),
        "    # Server config (.htaccess, this file) is never served.",
        "    location ~ /\\. { return 404; }",
        *RD.nginx_lines(at, list(moved)),
        f'    location ~ "\\.[0-9a-f]{{12}}\\.({exts})$" {{',
        *headers(CACHE_ASSET),
        "        try_files $uri /index.php?$args;",
        "    }",
        *(handoff(f"^{q}(index\\.html)?$", search_param) if search_param else []),
        *(line for p in topic_params
          for line in handoff(f"^{q}topics/[^/]+/(page/[0-9]+/)?(index\\.html)?$", p)),
        '    location ~ "(/|\\.html|\\.txt)$" {',
        *headers(CACHE_HTML),
        "        try_files $uri $uri/ /index.php?$args;",
        "    }",
        "    try_files $uri $uri/ /index.php?$args;",
        "}",
        "",
    ])


def _pages_headers(at: str, csp: bool | str = False, site: str = "") -> str:
    """The room's header rules for Cloudflare Pages (pack `host`).

    Pages has no .htaccess and no nginx: it reads one root `_headers` file, 100
    rules at most, where a rule is a path pattern and its indented headers. The
    publish script splices this fragment into that file between markers.

    Two things the format forces:

    - A header that two matching rules set is **joined with a comma**, not
      overridden. So the assets rule cannot simply restate Cache-Control: it
      detaches the page rule's value first (`! Cache-Control`) and then sets its
      own. That ordering is load-bearing, and a test pins it.
    - Matching is on the request path, not the file it resolves to, so a
      directory request (every record page) has to be covered by `/mount/*`.

    Only `assets/` gets the immutable policy: everything the build puts there is
    content-hashed. Pagefind's files are not all hashed (pagefind.js and
    pagefind-worker.js keep their names), so they keep the page policy.

    The first line names the pack's site (`identity.site`) and the mount: the
    splice takes the site from there, so a site is named by its pack and not by
    whatever a caller passes on the command line.
    """
    rules = [
        f"{at}*",
        f"  Cache-Control: {CACHE_HTML}",
        *([f"  Content-Security-Policy: {_policy(csp)}"] if csp else []),
        "",
        f"{at}assets/*",
        "  ! Cache-Control",
        f"  Cache-Control: {CACHE_ASSET}",
        "",
    ]
    return "\n".join([
        f"# roomkit {site or 'room'} {at} -- the room's rules for Cloudflare Pages (build.py _pages_headers).",
        "# A fragment, not a file to serve: the publish script splices it into the site's",
        "# root _headers between its markers, and never copies this into the room.",
        "",
        *rules,
    ])


def _fingerprint(files: dict[str, bytes], at: str) -> tuple[dict[str, bytes], dict[str, str]]:
    """Content-hashed names for every asset and pages.json; references rewritten.

    Leaves first, then rr-config.js (it names pdf.js files), then the HTML that
    names them all. A reference is rewritten only as a whole quoted URL.
    """
    def named(path: str) -> str:
        head, _dot, ext = path.rpartition(".")
        return f"{head}.{sha256(files[path])[:12]}.{ext}"

    def leaf(p: str) -> bool:
        base = p.rsplit("/", 1)[-1]
        # The theme's files are named by their hash already (_theme_files): room.css names them.
        return ((p.startswith("assets/") and "." in base and p != "assets/rr-config.js"
                 and not p.startswith(THEME_DIR)) or p.endswith("/pages.json"))

    def rewrite(data: bytes, mapping: dict[str, str]) -> bytes:
        text = data.decode("utf-8")
        for old, new in mapping.items():
            text = text.replace(f'"{at}{old}"', f'"{at}{new}"')
        return text.encode()

    mapping = {p: named(p) for p in sorted(files) if leaf(p)}
    if "assets/rr-config.js" in files:
        files["assets/rr-config.js"] = rewrite(files["assets/rr-config.js"], mapping)
        mapping["assets/rr-config.js"] = named("assets/rr-config.js")
    out = {}
    for p, data in files.items():
        if p.endswith(".html"):
            data = rewrite(data, mapping)
        out[mapping.get(p, p)] = data
    return out, mapping


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


# --- the site theme's files (pack fonts, identity.logo, identity.favicon) ------

THEME_DIR = "assets/theme/"


def _theme_files(pack: dict, root: Path) -> dict[str, tuple[str, bytes]]:
    """{pack file: (published path, bytes)} for every theme file the pack names.

    Named by content hash already, so room.css can name a font's final URL before
    the room is fingerprinted. Two files with one basename and different bytes get
    two names; the same bytes twice, one."""
    ident = pack["identity"]
    srcs = [f["src"] for f in pack.get("fonts", [])]
    srcs += [ident["logo"]["src"]] if ident.get("logo") else []
    srcs += [ident["favicon"]] if ident.get("favicon") else []
    a11y = pack.get("a11y_toolbar")
    srcs += [a11y["icon_font"], a11y["contrast_css"]] if a11y else []
    out = {}
    for src in dict.fromkeys(srcs):
        data = (root / src).read_bytes()
        head, _dot, ext = Path(src).name.rpartition(".")
        out[src] = (f"{THEME_DIR}{head}.{sha256(data)[:12]}.{ext}", data)
    return out


def _fonts_css(pack: dict, urls: dict[str, str]) -> str:
    """@font-face for each of the pack's fonts, at the room's own URLs (CSP font-src 'self')."""
    out = []
    for f in pack.get("fonts", []):
        fmt = {"woff2": "woff2", "woff": "woff", "ttf": "truetype", "otf": "opentype"}.get(
            f["src"].rsplit(".", 1)[-1], "woff2")
        out.append(f'@font-face{{font-family:"{f["family"]}";src:url("{urls[f["src"]]}") format("{fmt}");'
                   f'font-weight:{f.get("weight", "400")};font-style:{f.get("style", "normal")};font-display:swap}}')
    return "\n".join(out) + ("\n" if out else "")


# The plugin's @font-face for its icons names five formats beside its own stylesheet;
# the room serves the one woff2 the pack carries, at its own URL.
_A11Y_FONT_SRC = re.compile(r"src:url\('a11y\.eot'\);\s*src:[^;]+;")


def _a11y_css(pack: dict, root: Path, urls: dict[str, str]) -> str:
    """The toolbar's stylesheets as the plugin ships them (its icon font's, then its own),
    verbatim but for the font's URL. The site loads them on every WordPress page, unscoped,
    so they are not held to the pack's scope rule."""
    t = pack.get("a11y_toolbar")
    if not t:
        return ""
    icons, n = _A11Y_FONT_SRC.subn(f'src:url("{urls[t["icon_font"]]}") format("woff2");',
                                   (root / t["icons_css"]).read_text(encoding="utf-8"))
    if n != 1:
        raise ValueError(f"{t['icons_css']}: the plugin's @font-face src is not where it was ({n} matches)")
    return icons + "\n" + (root / t["css"]).read_text(encoding="utf-8") + "\n"


def render(m: Manifest, engine: Path = ENGINE, mount: str | None = None, noindex: bool = False,
           pack: dict | None = None, indexer: S.Indexer | None = None) -> dict[str, bytes]:
    """Every output file of the room, keyed by its path in the tree.

    `mount` serves the tree somewhere other than the site's room_path (staging:
    `/rr-staging/`); links and assets follow it, canonical links do not.
    `noindex` adds a robots meta to every page. `pack` (pack.load's output) is
    the site pack; without one, the manifest's site's pack (`site.template`), or
    the default. `indexer` builds the corpus search index when the pack turns it
    on (default: the pinned Pagefind; tests pass search.stand_in).
    """
    at = mount or m.site.room_path
    try:
        at = validate_room_path(at, "mount")
    except ManifestError as exc:
        raise ValueError(str(exc)) from exc
    if m.refusals:
        raise ValueError("render() called on a manifest with refusals")
    pack = _pack(m, pack)
    root = Path(pack.get(P.ROOT_KEY) or pack_dir(pack["identity"]["site"]))
    pack = {k: v for k, v in pack.items() if k != P.ROOT_KEY}
    theme = _theme_files(pack, root)
    if theme:
        # The view needs the theme files' URLs (logo, icon); a pack without any is unchanged.
        pack = {**pack, V.THEME_URLS: {src: at + path for src, (path, _b) in theme.items()}}
    theme_exts = tuple(sorted({path.rsplit(".", 1)[-1] for path, _b in theme.values()}))
    # Without the pack's entities switch the room never sees the block: no pages,
    # no links into them, no stylesheet (entities.gate). The same for collections,
    # passages, machine text and topics.
    m = HM.gate(TP.gate(MT.gate(PS.gate(CO.gate(E.gate(m, pack), pack), pack), pack), pack), pack)
    facet_pages: list[dict] = []
    if B.facet_pages_on(pack) and m.site.index.get("browse"):
        problems = B.problems(m)
        if problems:
            raise ValueError("browse refused:\n" + "\n".join(f"   {x}" for x in problems))
        facet_pages = B.pages(m)
    if any(d.is_snapshot for d in m.documents) and not pack.get("features", {}).get("web-archive"):
        raise ValueError("snapshot records require pack features.web-archive")
    text_docs = [d for d in m.documents if PT.on(d, pack)]
    files: dict[str, bytes] = {
        "assets/rr-config.js": _config(at, m.passages["api"] if m.passages else "",
                                        any(d.snapshot.get("kind") == "wacz" for d in m.documents)).encode(),
        **_engine_files(engine),
    }
    if pack.get("host") == "cloudflare-pages":
        files[HEADERS_ROOM] = _pages_headers(at, _pack_csp(pack),
                                             pack["identity"]["site"]).encode()
    for d in m.documents:
        if V.thumb_path(d):
            files[V.thumb_path(d)] = thumb_bytes(d.index["thumb"])
    search = S.enabled(pack)
    files.update({path: data for path, data in theme.values()})
    read_aloud = bool(pack.get("features", {}).get("read-aloud")) and any(V.read_aloud_on(d, pack) for d in m.documents)
    seam = T.seam_on(pack) and any(_has_mount(d) for d in m.documents)
    files["assets/room.css"] = (_fonts_css(pack, pack.get(V.THEME_URLS, {}))
                                + R.ROOM_CSS + R.chrome_css(pack) + (R.SEARCH_CSS if search else "")
                                + (R.ENTITIES_CSS if m.entities else "") + (R.BROWSE_CSS if facet_pages else "")
                                + (R.COLLECTIONS_CSS if m.collections else "")
                                + (R.TOPICS_CSS if m.topics else "")
                                + (R.PAGE_TEXT_CSS if text_docs else "")
                                + CSS.theme_css(pack) + _a11y_css(pack, root, pack.get(V.THEME_URLS, {}))
                                + (R.ROOM_TOOLS_CSS if seam else "")
                                + (R.READ_ALOUD_CSS if read_aloud else "")
                                + (R.GALLERY_CSS if V.gallery_on(pack) else "")
                                + (R.PAGER_CSS if V.page_size(pack) else "")
                                + (pack.get("theme") or {}).get("css", "")).encode()
    files["assets/room.js"] = R.ROOM_JS.encode()
    if pack.get("a11y_toolbar"):
        files["assets/room-a11y.js"] = R.ROOM_A11Y_JS.encode()
    if seam:
        files["assets/room-tools.js"] = R.ROOM_TOOLS_JS.encode()
    if read_aloud:
        files["assets/rr-read-aloud.js"] = READ_ALOUD_JS.read_bytes()
    if m.collections:
        files["assets/room-collections.js"] = R.ROOM_COLLECTIONS_JS.encode()
    if V.gallery_on(pack):
        files["assets/room-gallery.js"] = R.ROOM_GALLERY_JS.encode()
    if V.page_size(pack):
        files["assets/room-pager.js"] = R.pager_js(V.page_size(pack)).encode()
    if search:
        files["assets/room-search.js"] = R.ROOM_SEARCH_JS.encode()
        # Pagefind names its own files (content hashes inside pagefind/); they are
        # not fingerprinted again, or its loader could not find them.
        files.update(S.index_files(m, at, indexer))
    files["index.html"] = _index_page(m, at, noindex, pack, facet_pages).encode()
    for p in facet_pages:
        files[p["path"] + "index.html"] = _facet_page(p, m, at, noindex, pack).encode()
    for f in B.roots(facet_pages):
        files[f["path"] + "index.html"] = _facet_root_page(f, m, at, noindex, pack).encode()
    if B.sitemap_on(pack):
        room = m.site.base_url + m.site.room_path
        files[B.SITEMAP] = B.sitemap_xml(B.urls(m, facet_pages, [room + PT.text_path(d) for d in text_docs]
                                                if PT.indexed(pack) else [])).encode()
    files["404.html"] = _404_page(m, at, pack).encode()
    if m.entities:
        if m.entities["index"]:
            files[m.entities["index"]["path"] + "index.html"] = _entity_index_page(m, at, noindex, pack).encode()
        for p in m.entities["pages"]:
            files[p["path"] + "index.html"] = _entity_page(p, m, at, noindex, pack).encode()
    for f in (m.machine_text or {}).get("files", []):
        files[f["path"]] = f["text"].encode()
    if m.collections:
        if m.collections["index"]:
            files[m.collections["index"]["path"] + "index.html"] = _collections_index_page(m, at, noindex, pack).encode()
        for p in m.collections["pages"]:
            files[p["path"] + "index.html"] = _collection_page(p, m, at, noindex, pack).encode()
    if m.topics:
        if m.topics["index"]:
            files[m.topics["index"]["path"] + "index.html"] = _topics_index_page(m, at, noindex, pack).encode()
        for p in m.topics["pages"]:
            files[p["path"] + "index.html"] = _topic_page(p, m, at, noindex, pack).encode()
    for d in m.documents:
        files[f"{d.slug}/index.html"] = _doc_page(d, m, at, noindex, pack).encode()
        if PT.on(d, pack):
            files[PT.text_path(d) + "index.html"] = _text_page(d, m, at, noindex, pack).encode()
            files[PT.txt_path(d)] = PT.txt(d, f"{m.site.base_url}{m.site.room_path}{d.slug}/").encode()
        if d.pages:
            pages_list = []
            for p in d.pages:
                p_dict = {"n": p.n, "provenance": p.provenance, "text": p.text}
                if p.image_url:
                    p_dict["image_url"] = p.image_url
                if p.boxes:
                    p_dict["boxes"] = list(p.boxes)
                if m.passages and p.cite:
                    p_dict["cite"] = p.cite
                pages_list.append(p_dict)
            pages = {"schema_version": m.schema_version, "slug": d.slug, "total": len(d.pages), "pages": pages_list}
            if d.provenance:
                pages["provenance"] = d.provenance
            if d.lang:
                pages["lang"] = d.lang
            if d.relations:
                pages["relations"] = list(d.relations)
            files[f"{d.slug}/pages.json"] = (json.dumps(pages, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if m.passages:
        files["citations.json"] = (json.dumps(PS.citations_json(m.passages), ensure_ascii=False,
                                              sort_keys=True) + "\n").encode()
    # Server config last: a redirect is written only when the room no longer serves
    # its page and does serve its target (redirects.py).
    moved, skipped = RD.active(m.redirects, files)
    skipped = list(m.redirect_notes) + skipped
    files[HTACCESS] = _htaccess(at, any(V.thumb_path(d) for d in m.documents),
                                _pack_csp(pack), bool(m.machine_text) or bool(text_docs),
                                _search_handoff(m, at, pack), theme_exts, moved).encode()
    if pack.get("nginx"):
        files[NGINX] = _nginx(at, pack["nginx"]["root"], any(V.thumb_path(d) for d in m.documents),
                              _pack_csp(pack), bool(m.machine_text) or bool(text_docs),
                              _search_handoff(m, at, pack), _topic_handoffs(m, at, pack), theme_exts,
                              moved).encode()
    files, assets = _fingerprint(files, at)
    lock = {"roomkit": ROOMKIT_VERSION,
            "schema": m.schema_version,
            "engine": (engine / "VERSION").read_text().strip(),
            "documents": len(m.documents),
            "mount": at,
            "noindex": noindex,
            # The pack is an input like the manifest: a menu or token change shows up here.
            "pack": sha256(json.dumps(pack, sort_keys=True).encode()),
            "assets": assets,
            **({"search": {"pagefind": S.PAGEFIND_VERSION if indexer is None else "stand-in",
                           "input": sha256(json.dumps(S.pages(m, at), sort_keys=True).encode())}} if search else {}),
            # Served files. .htaccess and .nginx.conf are server config: hosts refuse to
            # serve them, so they are hashed apart and a publish's served-file check skips them.
            "server_config": {p: sha256(files[p]) for p in SERVER_CONFIG if p in files},
            # A viewing copy (file.view_url) is a derivative served by the site, never a
            # replacement: its hash sits beside the original's (roadmap E2).
            **({"derivatives": {d.slug: {"source_sha256": d.sha256, "view_sha256": d.view_sha256}
                                for d in m.documents if d.view_sha256}}
               if any(d.view_sha256 for d in m.documents) else {}),
            **({"redirects": len(moved)} if moved else {}),
            **({"redirects_skipped": skipped} if skipped else {}),
            "files": {p: sha256(b) for p, b in sorted(files.items()) if p not in SERVER_CONFIG}}
    files[LOCK] = (json.dumps(lock, indent=1, sort_keys=True) + "\n").encode()
    return files


def published(files: dict[str, bytes], logical: str) -> str:
    """The published path of a logical one (`assets/room.css` -> `assets/room.<hash>.css`)."""
    return json.loads(files[LOCK])["assets"].get(logical, logical)


def write(files: dict[str, bytes], out: Path) -> None:
    """Write the render to `out` all at once: into a sibling copy of the tree on disk
    (so files no longer in the room stay until the publish step removes them), then
    swapped in with two renames. A failure while writing leaves the previous tree
    as it was and removes the copy."""
    out = Path(out).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.new")
    old = out.with_name(f".{out.name}.old")
    for left in (tmp, old):
        if left.exists():
            shutil.rmtree(left)
    try:
        if out.is_dir():
            shutil.copytree(out, tmp, symlinks=True)
        for rel, data in files.items():
            p = tmp / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
    except BaseException:
        shutil.rmtree(tmp, ignore_errors=True)
        raise
    if out.exists():
        out.rename(old)
    tmp.rename(out)
    shutil.rmtree(old, ignore_errors=True)


def _without_pagefind(lock: bytes) -> bytes:
    d = json.loads(lock)
    d["files"] = {p: h for p, h in d["files"].items() if not p.startswith(S.OUT + "/")}
    return json.dumps(d, indent=1, sort_keys=True).encode()


def _served_index(lock: dict, served: Path) -> dict[str, str] | None:
    """The published index's entries when it answers this build's query, else None.

    Same rule as `compare`: the lock's `search` (a hash of every indexed field,
    and the binary version) is what decides whether two indexes answer the same
    question. The bytes on disk must also still hash to that lock: a damaged
    index is never adopted, or the lock would describe files that are not there.
    """
    if lock.get("search", {}).get("pagefind") in (None, "stand-in"):
        return None
    lock_file = served / LOCK
    if not lock_file.is_file():
        return None
    old = json.loads(lock_file.read_bytes())
    if old.get("search") != lock.get("search"):
        return None
    old_pf = {p: h for p, h in old.get("files", {}).items() if p.startswith(S.OUT + "/")}
    if not old_pf:
        return None
    for p, h in old_pf.items():
        if not (served / p).is_file() or sha256((served / p).read_bytes()) != h:
            return None
    return old_pf


def adopt_search(files: dict[str, bytes], out: Path) -> bool:
    """Keep the published Pagefind index when it answers the same query.

    Pagefind's bytes are not reproducible (search.py: it writes each filter's
    values in a random order, so `filter/*.pf_filter`, `pagefind.*.pf_meta`, the
    hashes in their names and pagefind-entry.json all differ between runs of the
    same input). A publish that ships a rebuilt-but-equivalent index therefore
    diffs in git on every run, for no change to the corpus. That is the same
    fact `compare` already relies on: when the lock's `search` matches and the
    index on disk is the one that lock lists, the two indexes are
    interchangeable.

    So this swaps the built index for the published one and rewrites the new
    lock's pagefind entries from the published lock. Returns True when it
    adopted. Called before writing, never after: the lock that ships must
    describe the index that ships. `reuse_search` is the same rule for a room
    that is already on disk.
    """
    old_pf = _served_index(json.loads(files[LOCK]), out)
    if old_pf is None:
        return False
    lock = json.loads(files[LOCK])
    for p in [p for p in files if p.startswith(S.OUT + "/")]:
        del files[p]
    for p in old_pf:
        files[p] = (out / p).read_bytes()
    lock["files"] = {p: h for p, h in lock["files"].items() if not p.startswith(S.OUT + "/")} | old_pf
    files[LOCK] = (json.dumps(lock, indent=1, sort_keys=True) + "\n").encode()
    return True


def reuse_search(out: Path, served: Path) -> bool:
    """`adopt_search` for a built room on disk: `out` takes `served`'s index.

    A publish builds into a temp tree and copies it in; this makes that tree's
    index the published one before anything is copied, so an unchanged corpus
    produces an unchanged tree. Rewrites `out`'s lock to match.
    """
    lock_file = out / LOCK
    if not lock_file.is_file():
        return False
    lock = json.loads(lock_file.read_bytes())
    old_pf = _served_index(lock, served)
    if old_pf is None:
        return False
    built = out / S.OUT
    if built.is_dir():
        shutil.rmtree(built)
    shutil.copytree(served / S.OUT, built)
    lock["files"] = {p: h for p, h in lock["files"].items() if not p.startswith(S.OUT + "/")} | old_pf
    lock_file.write_bytes((json.dumps(lock, indent=1, sort_keys=True) + "\n").encode())
    return True


def compare(files: dict[str, bytes], out: Path) -> dict[str, list[str]]:
    """What differs between a render and the tree on disk. Empty lists = current.

    Pagefind's own bytes are not reproducible (it writes each filter's values in
    a random order, so the file names change between runs). With the real indexer
    the index is current when its input (lock `search.input`, a hash of every
    indexed field) and version match and the files on disk are the ones the
    on-disk lock lists; the stand-in indexer is compared byte for byte.
    """
    on_disk = {str(p.relative_to(out)) for p in out.rglob("*") if p.is_file()} if out.is_dir() else set()
    real = json.loads(files[LOCK]).get("search", {}).get("pagefind") not in (None, "stand-in")
    if real and LOCK in on_disk:
        pf_new = {p for p in files if p.startswith(S.OUT + "/")}
        old_lock = json.loads((out / LOCK).read_bytes())
        pf_old = {p for p in old_lock.get("files", {}) if p.startswith(S.OUT + "/")}
        broken = {p for p, h in old_lock.get("files", {}).items() if p.startswith(S.OUT + "/")
                  and not ((out / p).is_file() and sha256((out / p).read_bytes()) == h)}
        same = (_without_pagefind((out / LOCK).read_bytes()) == _without_pagefind(files[LOCK])
                and old_lock.get("search") == json.loads(files[LOCK]).get("search"))
        files = {p: b for p, b in files.items() if p not in pf_new and p != LOCK} | (
            {LOCK: files[LOCK]} if not same else {LOCK: (out / LOCK).read_bytes()})
        on_disk -= pf_old | {p for p in on_disk if p.startswith(S.OUT + "/")}
        pf_problem = sorted(broken | (pf_old - {p for p in pf_old if (out / p).is_file()}))
    else:
        pf_problem = []
    missing = sorted(set(files) - on_disk)
    extra = sorted(on_disk - set(files))
    stale = sorted(p for p in set(files) & on_disk if (out / p).read_bytes() != files[p])
    return {"missing": missing, "stale": sorted(stale + pf_problem), "extra": extra}
