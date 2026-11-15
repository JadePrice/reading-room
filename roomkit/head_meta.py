"""Head meta (pack features.head-meta): each page's <title> and meta tags as the site prints them.

site A's /library/ pages take their head from Yoast SEO and the plugin's filters on it
(its reading-room plugin's filter_yoast_title, filter_yoast_metadesc,
filter_yoast_og_title and filter_yoast_canonical): every route resolves to the one `library` page, so the
site-wide part (og:locale, og:type, og:site_name, article:*, og:image, twitter:*)
is that page's, and the filters replace the title, description, og:title,
og:description and og:url per route. The exporter writes each page's result
(the site's exporter, `head_meta`); the room prints it as written and
composes no word of it.

The manifest block (optional):

    "head_meta": {
      "pages": {"<path under the room>": {"title": "...",
                                           "meta": [["name" | "property", "<key>", "<content>"], ...],
                                           "schema": {...}}},
      "site": {"robots": "index, follow, ...", "schema": {"@context": "https://schema.org", "@graph": [...]}},
      "source": {"<plugin file>": "<sha256>"}
    }

A page's own `schema` (optional, the same shape) takes the place of the site's graph on
that page: on a site whose record and entity routes are virtual (site B's), Yoast has no post for
them, and its graph there is only the site's WebSite and Organization nodes (the
pre-cutover pages archived on 2026-07-22 show it), not the reading-room page's.

`site` (optional) is what Yoast prints the same on every route: the robots meta
and its JSON-LD graph (WebPage, BreadcrumbList, WebSite with its SearchAction,
Organization with the logo). The plugin filters neither (it hooks only
wpseo_title, wpseo_metadesc, wpseo_opengraph_* and wpseo_canonical), so a record
page's graph is the library page's, @id .../library/ and all, beside the record's
own DigitalDocument script; the saved pre-cutover record pages show exactly that.
The room prints both on every page the block has, the graph in Yoast's key order
and with its class (yoast-schema-graph). A room built with noindex keeps its own
robots meta and prints no other.

The path is the page's directory under the room ("" the index, "<slug>/" a
record, "topics/police/page/2/" a topic's second page). A page with no entry
keeps the room's own head, so a manifest without the block builds the bytes it
built before.

Refused: a path that is not one the room serves, a title or content that is
empty, not text, has a control character or runs over MAX_TEXT, a meta that is
not [attr, key, content], a key outside KEY or under the wrong attribute
(`name` for description and twitter:*, `property` for og:* and article:*), a
key that can appear once (description, og:url, og:title, og:description) twice,
and an og:url that is not the page's own URL. The room's canonical is the page's
own URL as before, so og:url and canonical agree. In `site`: a robots value that
is not Yoast's "index|noindex, follow|nofollow[, directive...]", and a schema that
is not {"@context": "https://schema.org", "@graph": [...]} with an @type and an
@id on the site on every node, or that runs over MAX_SCHEMA characters.

parity.head_meta (`roomkit parity --head LIVE.tsv --out ROOM`) compares the first
<title> in each live page's <head>, its meta description, canonical, robots and
every og:* value, text for text after HTML unescaping, and the Yoast graph, parsed
(JSON equal, not bytes), with the built room's.
"""

from __future__ import annotations

import json
import re
from dataclasses import replace
from html.parser import HTMLParser
from pathlib import Path

FEATURE = "head-meta"
PATH = re.compile(r"^(?:[a-z0-9][a-z0-9_-]*/)*$")
KEY = re.compile(r"^(?:description|og:[a-z_]+(?::[a-z_]+)?|article:[a-z_]+|twitter:[a-z0-9_]+)$")
ONCE = {"description", "og:url", "og:title", "og:description"}
CONTROL = re.compile(r"[\x00-\x1f\x7f]")
MAX_TEXT = 2000
ROBOTS = re.compile(r"^(?:index|noindex), (?:follow|nofollow)(?:, [a-z-]+(?::-?[a-z0-9]+)?)*$")
MAX_SCHEMA = 20000
SCHEMA_CLASS = "yoast-schema-graph"


def enabled(pack: dict) -> bool:
    return bool(pack.get("features", {}).get(FEATURE))


def gate(m, pack: dict):
    """The manifest without its head meta when the pack does not turn it on."""
    if getattr(m, "head_meta", None) and not enabled(pack):
        return replace(m, head_meta=None)
    return m


def _text_ok(s: object) -> bool:
    return isinstance(s, str) and s.strip() != "" and not CONTROL.search(s) and len(s) <= MAX_TEXT


def _page_problems(path: str, page: object, own_url: str, base_url: str) -> list[str]:
    if (not isinstance(page, dict) or not {"title", "meta"} <= set(page) <= {"title", "meta", "schema"}
            or not isinstance(page["meta"], list)):
        return [f"head_meta {path or '(index)'}: not {{title, meta: [...], schema?}}"]
    where = f"head_meta {path or '(index)'}"
    out = [] if _text_ok(page["title"]) else [f"{where}: title is empty, not text, has a control character or is too long"]
    if "schema" in page:
        out += _schema_problems(page["schema"], f"{where} schema", base_url)
    seen: set[str] = set()
    for t in page["meta"]:
        if not (isinstance(t, list) and len(t) == 3 and all(isinstance(x, str) for x in t)):
            out.append(f"{where}: a meta is not [attr, key, content]")
            continue
        attr, key, content = t
        if not KEY.match(key):
            out.append(f"{where}: meta key {key!r} is not one the room prints")
            continue
        want = "name" if key == "description" or key.startswith("twitter:") else "property"
        if attr != want:
            out.append(f"{where}: {key} is printed with {want}=, not {attr}=")
        if not _text_ok(content):
            out.append(f"{where}: {key} content is empty, not text, has a control character or is too long")
        if key in ONCE and key in seen:
            out.append(f"{where}: {key} twice")
        seen.add(key)
        if key == "og:url" and content != own_url:
            out.append(f"{where}: og:url {content!r} is not the page's own URL {own_url}")
    return out


def _site_problems(site: object, base_url: str) -> list[str]:
    if not isinstance(site, dict) or not set(site) <= {"robots", "schema"}:
        return ["head_meta.site is not {robots?, schema?}"]
    out = []
    robots = site.get("robots")
    if robots is not None and not (isinstance(robots, str) and ROBOTS.match(robots)):
        out.append(f"head_meta.site.robots {robots!r} is not Yoast's index|noindex, follow|nofollow[, directive...]")
    if site.get("schema") is not None:
        out += _schema_problems(site["schema"], "head_meta.site.schema", base_url)
    return out


def _schema_problems(schema: object, where: str, base_url: str) -> list[str]:
    graph = schema.get("@graph") if isinstance(schema, dict) else None
    if (not isinstance(schema, dict) or set(schema) != {"@context", "@graph"}
            or schema["@context"] != "https://schema.org" or not isinstance(graph, list) or not graph):
        return [f'{where} is not {{"@context": "https://schema.org", "@graph": [...]}}']
    out = []
    for i, n in enumerate(graph):
        if not (isinstance(n, dict) and isinstance(n.get("@type"), (str, list))
                and isinstance(n.get("@id"), str) and n["@id"].startswith(base_url + "/")):
            out.append(f"{where} @graph[{i}] has no @type, or no @id on {base_url}")
    if len(_graph_json(schema)) > MAX_SCHEMA:
        out.append(f"{where} runs over {MAX_SCHEMA} characters")
    return out


def _graph_json(schema: dict) -> str:
    """The graph as Yoast prints it: compact, keys in its order, slashes and non-ASCII unescaped;
    "</" escaped so nothing in it can end the script block."""
    return json.dumps(schema, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")


def parse(raw: object, base_url: str, room_path: str, served: set[str]) -> tuple[dict | None, list[str]]:
    """{"pages": {path: {title, meta: [(attr, key, content)]}}, "site": {robots, schema}} and every
    problem; a block with problems is not returned.

    `served` is every page path the manifest gives the room ("" the index)."""
    if raw is None:
        return None, []
    if (not isinstance(raw, dict) or not set(raw) <= {"pages", "site", "source"}
            or not isinstance(raw.get("pages"), dict)):
        return None, ["head_meta is not {pages: {...}, site?, source?}"]
    src = raw.get("source", {})
    if not (isinstance(src, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in src.items())):
        return None, ["head_meta.source is not {file: sha256}"]
    problems: list[str] = _site_problems(raw["site"], base_url) if "site" in raw else []
    pages = {}
    for path, page in sorted(raw["pages"].items()):
        if not PATH.match(path):
            problems.append(f"head_meta: {path!r} is not a page path under the room")
            continue
        if path not in served:
            problems.append(f"head_meta: {path or '(index)'} is not a page this room serves")
            continue
        bad = _page_problems(path, page, base_url + room_path + path, base_url)
        if bad:
            problems += bad
            continue
        pages[path] = {"title": page["title"], "meta": [tuple(t) for t in page["meta"]]}
        if "schema" in page:
            pages[path]["schema"] = _graph_json(page["schema"])
    if problems:
        return None, problems
    site = raw.get("site", {})
    return {"pages": pages, "site": {"robots": site.get("robots", ""),
                                     "schema": _graph_json(site["schema"]) if site.get("schema") else ""}}, []


def head(block: dict | None, path: str, room_head: dict) -> dict:
    """The page's head dict (view.head) with the site's own under "wp", when the block has the
    page: its title and meta, and the site-wide robots and Yoast graph (`site`; "" without)."""
    page = (block or {}).get("pages", {}).get(path)
    if not page:
        return room_head
    site = block.get("site") or {}
    return {**room_head, "wp": {**page, "robots": site.get("robots", ""),
                                "schema": page.get("schema", site.get("schema", "")), "schema_class": SCHEMA_CLASS}}


# --- parity.head_meta ---------------------------------------------------------------


class _Head(HTMLParser):
    """The first <title> and the meta/link tags of a page's <head>, values unescaped."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title: str | None = None
        self.meta: list[tuple[str, str]] = []
        self.canonical: list[str] = []
        self.graphs: list[str] = []
        self._in_title = self._in_graph = False
        self._buf: list[str] = []
        self.done = False

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        a = dict(attrs)
        if tag == "title" and self.title is None:
            self._in_title, self._buf = True, []
        elif tag == "meta" and (a.get("name") or a.get("property")):
            self.meta.append(((a.get("name") or a.get("property") or "").lower(), a.get("content") or ""))
        elif tag == "link" and (a.get("rel") or "").lower() == "canonical":
            self.canonical.append(a.get("href") or "")
        elif tag == "script" and SCHEMA_CLASS in (a.get("class") or "").split():
            self._in_graph, self._buf = True, []
        elif tag == "body":
            self.done = True

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        if self._in_title or self._in_graph:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "title" and self._in_title:
            self.title, self._in_title = "".join(self._buf).strip(), False
        elif tag == "script" and self._in_graph:
            self.graphs.append("".join(self._buf))
            self._in_graph = False
        elif tag == "head":
            self.done = True


def read_head(html: str) -> dict:
    """{title, description, canonical, robots, schema, og: {key: [values in order]}} from a page's
    <head>; schema is each Yoast graph parsed (a graph that is not JSON is kept as its text)."""
    p = _Head()
    p.feed(html.split("</head>", 1)[0] + "</head>")
    desc = [v for k, v in p.meta if k == "description"]
    og: dict[str, list[str]] = {}
    for k, v in p.meta:
        if k.startswith("og:"):
            og.setdefault(k, []).append(v)
    schema = []
    for g in p.graphs:
        try:
            schema.append(json.loads(g))
        except ValueError:
            schema.append(g)
    return {"title": p.title, "description": desc, "canonical": p.canonical,
            "robots": [v for k, v in p.meta if k == "robots"], "schema": schema, "og": og}


FIELDS = ("title", "description", "canonical", "robots", "schema", "og")


def _schema_diff(a: list, b: list) -> str:
    """Where two lists of graphs first differ, as a path (@graph[2].logo.width), not the whole graph."""
    def walk(x, y, at):
        if type(x) is not type(y):
            return at or "(graph)"
        if isinstance(x, dict):
            for k in sorted(set(x) | set(y)):
                if k not in x or k not in y:
                    return f"{at}.{k}".lstrip(".")
                d = walk(x[k], y[k], f"{at}.{k}")
                if d:
                    return d.lstrip(".")
            return ""
        if isinstance(x, list):
            if len(x) != len(y):
                return f"{at} (length {len(x)} vs {len(y)})"
            for i, (u, v) in enumerate(zip(x, y)):
                d = walk(u, v, f"{at}[{i}]")
                if d:
                    return d
            return ""
        return "" if x == y else at
    if len(a) != len(b):
        return f"{len(a)} graph(s) live, {len(b)} in the room"
    for i, (x, y) in enumerate(zip(a, b)):
        d = walk(x, y, "")
        if d:
            return f"graph {i}: {d.lstrip('.')} differs"
    return ""


def compare_page(live: dict, room: dict) -> list[str]:
    """What differs, one line per field: [] when the page's head equals live's."""
    out = []
    for f in ("title", "description", "canonical", "robots"):
        if live[f] != room[f]:
            out.append(f"{f}: live {live[f]!r}, room {room[f]!r}")
    if live["schema"] != room["schema"]:
        out.append(f"schema: {_schema_diff(live['schema'], room['schema'])}")
    for k in sorted(set(live["og"]) | set(room["og"])):
        a, b = live["og"].get(k, []), room["og"].get(k, [])
        if a != b:
            out.append(f"{k}: live {a!r}, room {b!r}")
    return out


def run(pages: dict[str, tuple[int, str]], fetched: dict, room: Path) -> dict:
    """parity.head_meta over fetched live pages ({host path: (code, html)}) and the built room."""
    mount = json.loads((Path(room) / "room.lock.json").read_text(encoding="utf-8")).get("mount", "/")
    prefix = mount.lstrip("/")
    same, diffs, unfetched, unbuilt, outside = 0, {}, {}, [], []
    fields = {f: 0 for f in FIELDS}
    for path, (code, html) in sorted(pages.items()):
        if code != 200:
            unfetched[path] = code
            continue
        if not path.startswith(prefix):
            outside.append(path)
            continue
        f = Path(room) / path[len(prefix):] / "index.html"
        if not f.is_file():
            unbuilt.append(path)
            continue
        lv, rm = read_head(html), read_head(f.read_text(encoding="utf-8"))
        for k in FIELDS:
            fields[k] += lv[k] == rm[k]
        d = compare_page(lv, rm)
        if d:
            diffs[path] = d
        else:
            same += 1
    total = len(pages) - len(unfetched) - len(outside)
    return {"check": "parity.head_meta", "ok": not diffs and not unbuilt and not unfetched and not outside and total > 0,
            "fetched": fetched.get("fetched", ""), "source": fetched.get("source", ""), "mount": mount,
            "total": total, "same": same, "fields": fields, "differ": diffs, "unbuilt": unbuilt,
            "unfetched": unfetched, "outside": outside}


def text_report(rep: dict, show: int = 10) -> str:
    lines = [(f"{'PASSES' if rep['ok'] else 'FAILS'}: page heads {rep['same']}/{rep['total']} equal live"
             f"{' (live fetched ' + rep['fetched'] + ')' if rep['fetched'] else ''}"),
             "   equal by field: " + ", ".join(f"{k} {n}/{rep['total']}" for k, n in rep["fields"].items())]
    for path, d in list(rep["differ"].items())[:show]:
        lines.append(f"   {path}:")
        lines += [f"     {x}" for x in d[:6]]
    if len(rep["differ"]) > show:
        lines.append(f"   ... and {len(rep['differ']) - show} more pages differ (--json lists every one)")
    lines += [f"   live page not in the room: {p}" for p in rep["unbuilt"]]
    lines += [f"   unfetched: {p} ({c})" for p, c in rep["unfetched"].items()]
    lines += [f"   outside the room's mount {rep['mount']}: {p}" for p in rep["outside"]]
    return "\n".join(lines)
