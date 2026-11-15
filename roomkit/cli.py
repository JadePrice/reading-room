"""roomkit: a reading room as static files, built from a site's manifest.

    build  --manifest M --out DIR [--json]   validate M, write the room into DIR
           [--mount /rr-staging/ --noindex]  (staging: served elsewhere, canonicals stay live)
                                             (exit 1 and write nothing if any row is refused)
    check  --manifest M --out DIR [--json]   rebuild in memory and compare with DIR;
                                             changes nothing; exit 1 on any difference
    status --manifest M --out DIR [--json]   where DIR stands, and the next command
    parity --manifest M [--json]             fetch each live page and check its citation,
                                             reader URL and download URL against M; exit 1 on any difference
    parity --matrix X [--site S] [--json]    the parity matrix's rows by status per site; exit 1 if a
                                             required static/dynamic-api row is not done (or a dropped
                                             row awaits sign-off), 2 if the matrix is refused
    parity --entities LIVE.json --out ROOM   parity.entities: the live entity set, index grouping and each
           [--json]                          entity's documents (and site A's "appears alongside") vs the built
                                             room; exit 1 on any difference (entity_parity.py)
    parity --entities-from PAGES.tsv --site S  the live file for --entities, from pages fetched by
                                             exporters/fetch-entity-pages.sh (prints JSON; reads nothing else)
    parity --collections LIVE.json --out ROOM  parity.collections: the live collections page, every collection
           [--json]                          page and the index's collections table vs the built room; exit 1
                                             on any difference (collection_parity.py)
    parity --collections-from PAGES.tsv --site S  the live file for --collections, from pages fetched by
                                             exporters/fetch-entity-pages.sh (prints JSON; reads nothing else)
    parity --topics LIVE.json --out ROOM     parity.topics: the live topics page and every page of every
           [--json]                          topic vs the built room; exit 1 on any difference
                                             (topic_parity.py)
    parity --topics-from PAGES.tsv --site S  the live file for --topics, from pages fetched by
                                             exporters/fetch-entity-pages.sh (prints JSON; reads nothing else)
    parity --machine-text LIVE.txt --out ROOM  parity.machine_text: the live documents.txt (one GET, saved)
           [--path documents.txt] [--json]   vs the room's, line by line, the "Generated:" time aside;
                                             exit 1 on any difference (machine_text.py)
    parity --head PAGES.tsv [...] --out ROOM parity.head_meta: each fetched live page's <title>, meta
           [--json]                          description, canonical and og:* vs the built room's page;
                                             pages fetched by exporters/fetch-entity-pages.sh; exit 1 on
                                             any difference, 2 on an unfetched page (head_meta.py)
    parity --passages LIVE.json --out ROOM  parity.passages: the live passage route's answers vs the built
           [--json]                          room's page citations, page texts and citations.json (site A);
                                             exit 1 on any difference (passage_parity.py)
    parity --passages-fetch --out ROOM       the live file for --passages: paced public GETs of a sample
           --sample N [--keys K] [--pace 2]  (--keys: curated stable_keys, one a line; default: the room's
                                             citations.json); stops at a 429/403
    parity --facet-pages LIVE.json --out ROOM  parity.facet_pages: each live facet value's records vs the
           [--json]                          room's facet page for it, every page linked from the index;
                                             exit 1 on any difference (browse_parity.py)
    parity --facets-from INDEX.html --site S  the live file for --facet-pages, from the live index page
                                             as fetched (prints JSON; reads nothing else)
    parity --sitemaps XML [XML ...] --out ROOM  parity.sitemaps: the live sitemap providers' URLs under the
           [--json]                          room vs the room's sitemap.xml; exit 1 on any difference
    parity --thumbs LIVE.tsv --out ROOM      parity.thumbnails: each live card's thumbnail bytes vs the
           [--json]                          room's copy (exporters/*-fetch-thumbs.sh); exit 1 on any
                                             difference (thumb_parity.py)
    parity --index INDEX.html --out ROOM     parity.index: the live index page's holdings line (documents,
           [--json]                          collections, years) vs the room's; exit 1 on any difference
                                             (index_parity.py)
    parity --style-from URL --site S         capture WordPress's computed styles for the style pairs
    parity --style LIVE.json --out ROOM      parity.style: the room's computed styles vs that capture
                                             (style_parity.py; 1280 and 390 px, light and dark)
    parity --index-facets INDEX.html --out ROOM  parity.index_facets: live's own filter and sort code over
           [--query Q ...] [--json]          the live index page's rows vs the room driven through its
                                             selects, in Chromium; --query adds text x sort cases in a
                                             corpus-search room; exit 1 on any difference (finder_parity.py)
    parity --index-suggest INDEX.html --answers LIVE.json --out ROOM [--as-served] [--json]
                                             parity.index_suggest: live's own suggestion code over the live
                                             index page plus its saved /suggest answers vs the room's box,
                                             in Chromium; exit 1 on any difference (suggest_parity.py)
    diff   --old LOCK --new LOCK [--json]    what a publish must purge and remove, from two locks
    gate   --out DIR [--max-bytes N] [--json]  a built room's links into its mount all land on a file,
                                             and no file is over the size limit (default 25 MiB);
                                             changes nothing; exit 1 on any failure (gate.py)
    vendor write --to DIR                    copy the room's core into another codebase, pinned
    pack import --map MAP [--write] [--json] a site pack's tokens from its design-tokens file via MAP
                                             (dry run by default: prints what changes; exit 2 if refused)
    pack theme --map MAP --page PAGE.html [--repos DIR] [--write|--check] [--json]
                                             a site pack's fonts, logo, icon, menu and element styles from
                                             its WordPress theme and page (theme_map.py); --check exits 1
                                             when the pack no longer matches the map
    vendor check --to DIR [--json]           how that copy has drifted; changes nothing; exit 1 on any drift

status --matrix X [--site S] [--json] names the next row that blocks cutover
(with or without --manifest/--out).

build/check/status take --site-pack packs/<site>/ (the site pack; refused, exit 2,
if it fails pack.py's checks). The pack (packs/<site>/pack.json) gives the room's
own header, navigation and footer, its tokens, labels and layout: --site-pack
DIR, else the manifest's site's pack (site.template), else packs/default.

Reads the manifest and this repo's reading-room-reader; writes only DIR. parity
makes read-only GETs to the site the manifest came from. No database and no
publish step: publishing is a separate, human decision.

Records the exporter could not export arrive in the manifest's `excluded` list
and are named by every command. They are never dropped quietly.

Exporters (read-only): roomkit/exporters/ (folder.py), and a site's own under
roomkit/sites/exporters/ where the sites layer is present.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roomkit import build as B
from roomkit import gate as G
from roomkit import kitlog
from roomkit import pack as K
from roomkit import pack_import as PI
from roomkit import vendor as V
from roomkit.manifest import ManifestError, load

# The sites layer (roomkit/sites/: parity, pack theme, status --matrix) is
# private; the public mirror ships roomkit without it, and then those commands
# are simply not registered.
try:
    from roomkit.sites import cli_ext as SX
except ModuleNotFoundError as exc:
    if exc.name not in ("roomkit.sites", "roomkit.sites.cli_ext"):
        raise
    SX = None
# A pack is refused for its own problems, and (with the sites layer) for a feature the matrix drops.
PACK_REFUSED = (K.PackError,) + ((SX.MatrixError,) if SX else ())


def _print(obj, as_json: bool, text: str) -> None:
    print(json.dumps(obj, indent=2, sort_keys=True) if as_json else text)


def _excluded_lines(m) -> str:
    cites = (m.passages or {}).get("excluded", [])
    return ("".join(f"\n   EXCLUDED by the exporter: {s}: {why}" for s, why in m.excluded)
            + "".join(f"\n   EXCLUDED by the exporter: citation {k}: {why}" for k, why in cites))


def _refused(m, as_json: bool) -> int:
    rows = [{"row": r, "reason": why} for r, why in m.refusals]
    _print({"refused": rows, "built": False}, as_json,
           "REFUSED, nothing written:\n" + "\n".join(f"   {r}: {why}" for r, why in m.refusals))
    return 1


def diff_locks(old: dict, new: dict) -> dict:
    """What publishing `new` over `old` must do at the edge and on disk.

    purge:  paths whose bytes changed in place or went away (HTML; nothing
            fingerprinted changes in place, so assets never need a purge).
    remove_now: paths to delete with the upload: everything no longer in the
            room except shared assets. A retracted record's page and page text
            go here, so a retraction is not left behind at a hashed URL.
    remove_later: old assets, kept for one more generation so an HTML page an
            edge still holds can load what it names until the purge lands.
    """
    o, n = old.get("files", {}), new.get("files", {})
    gone = sorted(set(o) - set(n))
    changed = sorted(p for p in set(o) & set(n) if o[p] != n[p])
    purge = sorted(set(changed) | {p for p in gone if not p.startswith("assets/")})
    return {"purge": purge,
            "remove_now": [p for p in gone if not p.startswith("assets/")],
            "remove_later": [p for p in gone if p.startswith("assets/")],
            "added": sorted(set(n) - set(o))}


def _pack_import_cmd(args) -> int:
    try:
        res = PI.derive(args.map, B.REPO_ROOT)
    except PI.ImportRefused as exc:
        _print({"refused": exc.problems}, args.json,
               "REFUSED, nothing written:\n" + "\n".join(f"   {x}" for x in exc.problems))
        return 2
    if args.write:
        PI.write(args.map, res)
    out = {"source": res["source"], "written": args.write,
           "changes": [{"token": k, "old": a, "new": b} for k, a, b in res["changes"]],
           "variants_not_imported": res["variants"]}
    lines = [(f"{'wrote' if args.write else 'would write'} {args.map.parent / 'pack.json'} from {res['source']}: "
              f"{len(res['changes'])} token(s) change")]
    lines += [f"   {k}: {a!r} -> {b!r}" for k, a, b in res["changes"]]
    lines += [f"   variant, not imported: {v}: {'; '.join(w)}" for v, w in res["variants"].items()]
    _print(out, args.json, "\n".join(lines))
    return 0


def _vendor_cmd(args) -> int:
    try:
        if args.vendor_command == "write":
            pin = V.write(args.to, V.source_commit())
            print(f"vendored {len(pin['files'])} files at {pin['commit'][:12]} into {args.to}")
            return 0
        st = V.check(args.to)
    except V.VendorError as exc:
        print(f"roomkit vendor: {exc}", file=sys.stderr)
        return 2
    _print(st, args.json, (f"{'current' if st['current'] else 'DRIFTED'}  {args.to}  (pinned {st['commit'][:12]})"
                           + "".join(f"\n   {k:8} {p}" for k in ("modified", "missing", "behind") for p in st[k])))
    return 0 if st["current"] else 1


def _load_pack(path: Path | None) -> dict | None:
    """A site pack, checked against the parity matrix (a dropped feature is refused).
    Without the sites layer there is no matrix, and that one check is skipped."""
    if not path:
        return None
    if SX is None:
        print("roomkit: no parity matrix (roomkit/sites/ is absent): "
              "the pack's dropped-feature check is skipped", file=sys.stderr)
        return K.load(path)
    return K.load(path, SX.matrix())


def _state(m, out: Path, mount: str | None = None, noindex: bool = False, pack: dict | None = None) -> dict:
    if m.refusals:
        return {"stage": "refused", "refused": len(m.refusals),
                "next": "fix the manifest's refused rows (roomkit build lists them)"}
    diff = B.compare(B.render(m, mount=mount, noindex=noindex, pack=pack), out)
    if not (out / B.LOCK).is_file():
        stage = "unbuilt"
    elif any(diff.values()):
        stage = "stale"
    else:
        stage = "current"
    nxt = {"unbuilt": "roomkit build", "stale": "roomkit build", "current": None}[stage]
    return {"stage": stage, "documents": len(m.documents),
            "excluded": [{"slug": s, "problem": why} for s, why in m.excluded],
            **{k: len(v) for k, v in diff.items()},
            "next": (f"{nxt} --manifest <M> --out {out}" + (f" --mount {mount}" if mount else "")
                     + (" --noindex" if noindex else "") + (" --site-pack <P>" if pack else "")) if nxt else None}


def _run(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="roomkit", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    kitlog.add_logging_flags(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    for status, p in ((False, sub.add_parser("build", help="validate the manifest and write the room")),
                      (False, sub.add_parser("check", help="compare the room on disk with a fresh render; changes nothing")),
                      (True, sub.add_parser("status", help="where the room stands, and the next command"))):
        p.add_argument("--manifest", required=not status, type=Path)
        p.add_argument("--out", required=not status, type=Path)
        p.add_argument("--mount", help="serve the tree at this path instead of the site's room_path (staging: /rr-staging/)")
        p.add_argument("--noindex", action="store_true", help="add a robots noindex to every page (staging)")
        p.add_argument("--site-pack", type=Path, help="packs/<site>/: the site's chrome, tokens, labels and layout")
        p.add_argument("--json", action="store_true")
        if status and SX:
            SX.add_status_args(p)
    if SX:
        SX.add_parity_parser(sub)
    vp = sub.add_parser("vendor", help="the room's core copied into another codebase, and its drift")
    vs = vp.add_subparsers(dest="vendor_command", required=True)
    for q in (vs.add_parser("write", help="copy the core into --to and pin it to this commit"),
              vs.add_parser("check", help="compare the copy with its pin and with the source; changes nothing")):
        q.add_argument("--to", required=True, type=Path, help="the copy's package directory (app/room)")
        q.add_argument("--json", action="store_true")
    kp = sub.add_parser("pack", help="site packs")
    ks = kp.add_subparsers(dest="pack_command", required=True)
    ki = ks.add_parser("import", help="derive a pack's tokens from its design-tokens file through a map")
    ki.add_argument("--map", required=True, type=Path, help="packs/<site>/tokens.map.json")
    ki.add_argument("--write", action="store_true", help="write the pack (default: show what would change)")
    ki.add_argument("--json", action="store_true")
    if SX:
        SX.add_pack_theme_parser(ks)
    dp = sub.add_parser("diff", help="what a publish must purge and remove, from the old and new locks")
    dp.add_argument("--old", required=True, type=Path)
    dp.add_argument("--new", required=True, type=Path)
    dp.add_argument("--json", action="store_true")
    gp = sub.add_parser("gate", help="a built room's internal links and file sizes; changes nothing")
    gp.add_argument("--out", required=True, type=Path)
    gp.add_argument("--max-bytes", type=int, default=G.MAX_BYTES)
    gp.add_argument("--json", action="store_true")
    ap = sub.add_parser("adopt-search",
                        help="keep the published Pagefind index when it answers the same query")
    ap.add_argument("--out", required=True, type=Path, help="the room just built (its index is replaced)")
    ap.add_argument("--from", dest="served", required=True, type=Path,
                    help="the published room (its index is the one kept)")
    args = parser.parse_args(argv)
    if SX:
        rc = SX.dispatch(args, parser)
        if rc is not None:
            return rc

    if args.command == "adopt-search":
        try:
            kept = B.reuse_search(args.out, args.served)
        except (OSError, ValueError, KeyError) as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        print("adopted the published index: same input, same Pagefind version"
              if kept else "rebuilt the index: no published index answers this query")
        return 0

    if args.command == "gate":
        try:
            res = G.run(args.out, args.max_bytes)
        except G.GateError as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        _print(res, args.json, G.text(res))
        return 0 if res["ok"] else 1
    if args.command == "vendor":
        return _vendor_cmd(args)
    if args.command == "pack":
        return _pack_import_cmd(args)
    if args.command == "diff":
        old = json.loads(args.old.read_text()) if args.old.is_file() else {}
        d = diff_locks(old, json.loads(args.new.read_text()))
        _print(d, args.json, "\n".join(f"{k}: {len(v)}" + "".join(f"\n   {p}" for p in v) for k, v in d.items()))
        return 0

    matrix = getattr(args, "matrix", None)  # status --matrix exists only with the sites layer
    if args.command == "status":
        if not (args.manifest or matrix) or bool(args.manifest) != bool(args.out):
            parser.error("status needs --manifest and --out, --matrix, or all three" if SX
                         else "status needs --manifest and --out")
        if not args.manifest:
            st = SX.matrix_state(matrix, args.site)
            _print(st, args.json, SX.matrix_status_text(st))
            return 0

    try:
        m = load(args.manifest)
    except ManifestError as exc:
        print(f"roomkit: {exc}", file=sys.stderr)
        return 2

    if args.command in ("build", "check", "status"):
        try:
            pack = _load_pack(args.site_pack)
        except PACK_REFUSED as exc:
            print("roomkit: site pack refused:\n" + "\n".join(f"   {x}" for x in exc.problems), file=sys.stderr)
            return 2

    if args.command == "status":
        try:
            st = _state(m, args.out, args.mount, args.noindex, pack)
        except ValueError as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        if matrix:
            st["parity"] = SX.matrix_state(matrix, args.site)
        _print(st, args.json, f"{st['stage']}  ({st.get('documents', 0)} documents)\n"
                              f"   next: {st['next'] or 'nothing to do'}" + _excluded_lines(m)
               + ("\nparity matrix: " + SX.matrix_status_text(st["parity"]) if matrix else ""))
        return 0

    if m.refusals:
        return _refused(m, args.json)

    if args.command == "parity":  # parity --manifest (only registered with the sites layer)
        return SX.parity_manifest(args, m, _excluded_lines)

    try:
        files = B.render(m, mount=args.mount, noindex=args.noindex, pack=pack)
    except ValueError as exc:
        print(f"roomkit: {exc}", file=sys.stderr)
        return 2

    if args.command == "check":
        diff = B.compare(files, args.out)
        ok = not any(diff.values())
        lines = [f"{'current' if ok else 'DIFFERS'}  {args.out}  ({len(m.documents)} documents, {len(files)} files)"]
        for k, paths in diff.items():
            lines += [f"   {k:8} {p}" for p in paths]
        _print({"current": ok, **diff}, args.json, "\n".join(lines) + _excluded_lines(m))
        return 0 if ok else 1

    # build. Files that are no longer part of the room (a retracted record's
    # page) are listed, not deleted: the publish step owns removal and the purge
    # that has to follow it, and build never deletes outside its own output.
    extra = B.compare(files, args.out)["extra"]
    B.write(files, args.out)
    _print({"built": True, "documents": len(m.documents), "files": len(files), "not_in_room": extra,
            "excluded": [{"slug": s, "problem": w} for s, w in m.excluded]},
           args.json,
           f"built {args.out}: {len(m.documents)} documents, {len(files)} files"
           + ("".join(f"\n   not in room (remove before publishing): {p}" for p in extra) if extra else "")
           + _excluded_lines(m))
    return 0


def main(argv: list[str] | None = None) -> int:
    log = kitlog.configure("roomkit")
    with kitlog.run(log, kitlog.command_of(argv, ("--manifest", "--out")), argv):
        return _run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
