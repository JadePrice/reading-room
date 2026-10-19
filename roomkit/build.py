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
    assets/room.<hash>.css           the shared styles, the room's chrome, the site pack's tokens (templates/room/)
    assets/room.<hash>.js            index filters and the light/dark toggle
    assets/rr-config.<hash>.js       window.rrReaderConfig for the engine
    assets/vendor/rr-reader/...      the shared engine, verbatim
    assets/vendor/pdfjs/...          pdf.js as the engine pins it
    assets/room-search.<hash>.js     the finder's text search and suggestions (pack features.corpus-search)
    entities/index.html, entity/<type>/<slug>/index.html
                                     the site's entity index and pages, at their live paths
                                     (pack features.entities, manifest `entities`; entities.py)
    pagefind/...                     the Pagefind index over every record (same switch; search.py)
    citations.json                   GG's curated citations by stable_key, and each page's site
                                     citation in pages.json (pack features.passage-cite,
                                     manifest `passages`; passages.py)
    .htaccess                        cache headers and the 404 page (Apache/LiteSpeed hosts)
    room.lock.json                   sha256 of every file above, logical -> published asset names, the pack's hash

Caching. Every asset and pages.json carries a content hash in its name, so it
can be cached for a year as immutable: a new build is new names, never a stale
file. HTML is the only thing that changes in place; it revalidates in the
browser and is what a publish purges from the edge (`roomkit diff`).

Every page is the one shared template (Jinja, `scripts/roomkit/templates/room/`,
fed a plain view model from `view.py`, rendered by `room.py`). The page is the
room's own: it draws its header, navigation and footer from the site pack's
`chrome` (`packs/<site>/pack.json`), which also gives its tokens, labels and
layout. Nothing is captured from WordPress (plan D7, superseded 2026-10-14: a
standalone room cannot depend on WordPress output).
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from roomkit import css as CSS
from roomkit import entities as E
from roomkit import pack as P
from roomkit import passages as PS
from roomkit import room as R
from roomkit import search as S

try:
    from roomkit import view as V
    from roomkit.manifest import (
        IMAGE,
        PDF,
        READER,
        TEXT,
        Document,
        Manifest,
        ManifestError,
        validate_room_path,
    )
except ImportError:
    from scripts.roomkit import view as V
    from scripts.roomkit.manifest import (
        IMAGE,
        PDF,
        READER,
        TEXT,
        Document,
        Manifest,
        ManifestError,
        validate_room_path,
    )
REPO_ROOT = Path(__file__).resolve().parents[1]
ENGINE = REPO_ROOT / "reading-room-reader"
LOCK = "room.lock.json"
ROOMKIT_VERSION = "0.3.0"
HTACCESS = ".htaccess"
# Cache policy (see the module docstring). s-maxage lets an edge cache hold HTML
# for an hour between purges; browsers always revalidate it.
CACHE_ASSET = "public, max-age=31536000, immutable"
CACHE_HTML = "public, max-age=0, s-maxage=3600, must-revalidate"
FINGERPRINT = re.compile(r"\.[0-9a-f]{12}\.[a-z0-9]+$")

def _module(ext: str) -> str:
    if ext in PDF:
        return "rr-reader-pdf.js"
    if ext in IMAGE:
        return "rr-reader-image.js"
    if ext in TEXT:
        return "rr-reader-text.js"
    raise ValueError(ext)  # manifest.parse already refused it


def _engine_scripts(doc: Document, at: str) -> list[str]:
    if doc.ext not in READER:
        return []
    assets = at + "assets/"
    scripts = [f"{assets}rr-config.js", f"{assets}vendor/rr-reader/rr-reader.js"]
    if doc.ext in PDF:
        scripts.append(f"{assets}vendor/pdfjs/pdf.min.js")
    scripts.append(f"{assets}vendor/rr-reader/modules/{_module(doc.ext)}")
    return scripts


def _config(at: str, passage_url: str = "") -> str:
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

def _pack(m: Manifest, pack: dict | None) -> dict:
    """The site pack: the one given; else the manifest's site's; else the default."""
    if pack is None:
        return P.for_site(m.site.template or "default")
    # A manifest that names its site gets that site's pack.
    if m.site.template and pack["identity"]["site"] != m.site.template:
        raise ValueError(f"pack is for {pack['identity']['site']!r}, manifest template is {m.site.template!r}")
    return pack


def _page(main: str, content: dict, at: str, head: dict, scripts: list[str], pack: dict) -> str:
    """One page: the room's content element in the room's own chrome from the pack."""
    return R.render("room/base.html", V.page_view(main, content, at, head, scripts, V.chrome_view(pack)))


def _doc_page(doc: Document, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # `at` is where this tree is served (room_path, or a staging mount).
    # Canonical links always name the live room_path URL.
    s = m.site
    canonical = f"{s.base_url}{s.room_path}{doc.slug}/"
    head = V.head(f"{doc.title} | {s.title}", noindex, canonical,
                  V.social(doc.title, doc.summary, canonical, doc.poster_url, s.title),
                  V.jsonld(doc.display["jsonld"]) if doc.display.get("jsonld") else "")
    scripts = [*_engine_scripts(doc, at), f"{at}assets/vendor/rr-reader/modules/rr-cite.js"]
    return _page("room/document.html", V.doc_view(doc, m, at, pack), at, head, scripts, pack)


def _index_page(m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    s = m.site
    canonical = s.base_url + s.room_path
    title = s.index.get("title") or s.title
    head = V.head(title, noindex, canonical, V.social(title, s.index.get("lede", ""), canonical, "", s.title))
    scripts = [f"{at}assets/room-search.js"] if S.enabled(pack) else []
    return _page("room/index.html", V.index_view(m, at, pack), at, head, scripts, pack)


def _entity_index_page(m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    ix = m.entities["index"]
    head = V.head(ix["head_title"], noindex, ix["url"],
                  V.social(ix["title"], ix.get("description", ""), ix["url"], "", m.site.title))
    return _page("room/entities.html", V.entity_index_view(m, at, pack), at, head, [], pack)


def _entity_page(p: dict, m: Manifest, at: str, noindex: bool, pack: dict) -> str:
    # The canonical and the JSON-LD name the live URL, as on a record page.
    head = V.head(p["head_title"], noindex, p["url"],
                  V.social(p["title"], p.get("description", ""), p["url"], "", m.site.title),
                  V.jsonld(p["jsonld"]) if p.get("jsonld") else "")
    return _page("room/entity.html", V.entity_view(p, m, at, pack), at, head, [], pack)


def _404_page(m: Manifest, at: str, pack: dict) -> str:
    head = V.head(f"Not found | {m.site.title}", True)
    return _page("room/404.html", V.not_found_view(m, at, pack), at, head, [], pack)


def _htaccess(at: str) -> str:
    return "\n".join([
        "# Written by roomkit. Cache policy: build.py module docstring.",
        f"ErrorDocument 404 {at}404.html",
        "<IfModule mod_headers.c>",
        '<FilesMatch "\\.[0-9a-f]{12}\\.(css|js|json)$">',
        f'Header set Cache-Control "{CACHE_ASSET}"',
        "</FilesMatch>",
        '<FilesMatch "\\.html$">',
        f'Header set Cache-Control "{CACHE_HTML}"',
        "</FilesMatch>",
        "</IfModule>",
        "",
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
        return ((p.startswith("assets/") and "." in base and p != "assets/rr-config.js")
                or p.endswith("/pages.json"))

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
    # Without the pack's entities switch the room never sees the block: no pages,
    # no links into them, no stylesheet (entities.gate). The same for passages.
    m = PS.gate(E.gate(m, pack), pack)
    files: dict[str, bytes] = {
        "assets/rr-config.js": _config(at, m.passages["api"] if m.passages else "").encode(),
        HTACCESS: _htaccess(at).encode(),
        **_engine_files(engine),
    }
    search = S.enabled(pack)
    files["assets/room.css"] = (R.ROOM_CSS + R.chrome_css(pack) + (R.SEARCH_CSS if search else "")
                                + (R.ENTITIES_CSS if m.entities else "") + CSS.theme_css(pack)).encode()
    files["assets/room.js"] = R.ROOM_JS.encode()
    if search:
        files["assets/room-search.js"] = R.ROOM_SEARCH_JS.encode()
        # Pagefind names its own files (content hashes inside pagefind/); they are
        # not fingerprinted again, or its loader could not find them.
        files.update(S.index_files(m, at, indexer))
    files["index.html"] = _index_page(m, at, noindex, pack).encode()
    files["404.html"] = _404_page(m, at, pack).encode()
    if m.entities:
        if m.entities["index"]:
            files[m.entities["index"]["path"] + "index.html"] = _entity_index_page(m, at, noindex, pack).encode()
        for p in m.entities["pages"]:
            files[p["path"] + "index.html"] = _entity_page(p, m, at, noindex, pack).encode()
    for d in m.documents:
        files[f"{d.slug}/index.html"] = _doc_page(d, m, at, noindex, pack).encode()
        if d.pages:
            pages = {"slug": d.slug, "total": len(d.pages),
                     "pages": [{"n": p.n, "provenance": p.provenance, "text": p.text,
                                **({"cite": p.cite} if m.passages and p.cite else {})} for p in d.pages]}
            files[f"{d.slug}/pages.json"] = (json.dumps(pages, ensure_ascii=False, sort_keys=True) + "\n").encode()
    if m.passages:
        files["citations.json"] = (json.dumps(PS.citations_json(m.passages), ensure_ascii=False,
                                              sort_keys=True) + "\n").encode()
    files, assets = _fingerprint(files, at)
    lock = {"roomkit": ROOMKIT_VERSION,
            "engine": (engine / "VERSION").read_text().strip(),
            "documents": len(m.documents),
            "mount": at,
            "noindex": noindex,
            # The pack is an input like the manifest: a menu or token change shows up here.
            "pack": sha256(json.dumps(pack, sort_keys=True).encode()),
            "assets": assets,
            **({"search": {"pagefind": S.PAGEFIND_VERSION if indexer is None else "stand-in",
                           "input": sha256(json.dumps(S.pages(m, at), sort_keys=True).encode())}} if search else {}),
            # Served files. .htaccess is server config: hosts refuse to serve it, so
            # it is hashed apart and a publish's served-file check skips it.
            "server_config": {HTACCESS: sha256(files[HTACCESS])},
            "files": {p: sha256(b) for p, b in sorted(files.items()) if p != HTACCESS}}
    files[LOCK] = (json.dumps(lock, indent=1, sort_keys=True) + "\n").encode()
    return files


def published(files: dict[str, bytes], logical: str) -> str:
    """The published path of a logical one (`assets/room.css` -> `assets/room.<hash>.css`)."""
    return json.loads(files[LOCK])["assets"].get(logical, logical)


def write(files: dict[str, bytes], out: Path) -> None:
    for rel, data in files.items():
        p = out / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)


def _without_pagefind(lock: bytes) -> bytes:
    d = json.loads(lock)
    d["files"] = {p: h for p, h in d["files"].items() if not p.startswith(S.OUT + "/")}
    return json.dumps(d, indent=1, sort_keys=True).encode()


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
