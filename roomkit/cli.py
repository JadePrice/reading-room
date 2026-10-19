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
           [--json]                          entity's documents (and GG's "appears alongside") vs the built
                                             room; exit 1 on any difference (entity_parity.py)
    parity --entities-from PAGES.tsv --site S  the live file for --entities, from pages fetched by
                                             exporters/fetch-entity-pages.sh (prints JSON; reads nothing else)
    parity --passages LIVE.json --out ROOM   parity.passages: the live passage route's answers vs the built
           [--json]                          room's page citations, page texts and citations.json (GG);
                                             exit 1 on any difference (passage_parity.py)
    parity --passages-fetch --out ROOM       the live file for --passages: paced public GETs of a sample
           --sample N [--keys K] [--pace 2]  (--keys: curated stable_keys, one a line; default: the room's
                                             citations.json); stops at a 429/403
    diff   --old LOCK --new LOCK [--json]    what a publish must purge and remove, from two locks
    vendor write --to DIR                    copy the room's core into another codebase (Civica), pinned
    pack import --map MAP [--write] [--json] a site pack's tokens from its design-tokens file via MAP
                                             (dry run by default: prints what changes; exit 2 if refused)
    vendor check --to DIR [--json]           how that copy has drifted; changes nothing; exit 1 on any drift

status --matrix X [--site S] [--json] names the next row that blocks cutover
(with or without --manifest/--out).

build/check/status take --site-pack packs/<site>/ (the site pack; refused, exit 2,
if it fails pack.py's checks). The pack (packs/<site>/pack.json) gives the room's
own header, navigation and footer, its tokens, labels and layout: --site-pack
DIR, else the manifest's site's pack (site.template), else packs/default.

Reads the manifest and this repo's reading-room-reader; writes only DIR. parity
makes read-only GETs to the site the manifest came from. No database and no
publish step: publishing is a separate, human decision
(conductor/plans/2026-10-08-static-reading-room.md, step 3).

Records the exporter could not export arrive in the manifest's `excluded` list
and are named by every command. They are never dropped quietly.

Exporters (read-only, run on the site): scripts/roomkit/exporters/.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from roomkit import kitlog
from roomkit import build as B
from roomkit import entity_parity as EP
from roomkit import pack as K
from roomkit import pack_import as PI
from roomkit import parity as P
from roomkit import passage_parity as PP
from roomkit import search_parity as SP
from roomkit import vendor as V
from roomkit.manifest import ManifestError, load


MATRIX = Path(__file__).resolve().parent / "parity-matrix.yaml"


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
    lines = [f"{'wrote' if args.write else 'would write'} {args.map.parent / 'pack.json'} from {res['source']}: "
             f"{len(res['changes'])} token(s) change"]
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
    """A site pack, checked against the parity matrix (a dropped feature is refused)."""
    return K.load(path, P.load_matrix(MATRIX)) if path else None


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


def _matrix_state(path: Path, site: str | None) -> dict:
    """What `status` says about the parity matrix: the next row that blocks."""
    try:
        rep = P.matrix_report(P.load_matrix(path), site)
    except P.MatrixError as exc:
        return {"stage": "refused", "problems": exc.problems, "next": f"fix {path} (roomkit parity --matrix lists why)"}
    cmd = f"roomkit parity --matrix {path}" + (f" --site {site}" if site else "")
    return {"stage": "green" if rep["green"] else "blocked",
            "blocking": {s: len(v["blocking"]) for s, v in rep["sites"].items()},
            "awaiting_signoff": rep["awaiting_signoff"], "next_row": rep["next"],
            "next": None if rep["green"] else cmd}


def _matrix_cmd(args) -> int:
    try:
        rep = P.matrix_report(P.load_matrix(args.matrix), args.site)
    except P.MatrixError as exc:
        _print({"refused": exc.problems, "matrix": str(args.matrix)}, args.json,
               f"REFUSED {args.matrix}:\n" + "\n".join(f"   {p}" for p in exc.problems))
        return 2
    _print({"matrix": str(args.matrix), **rep}, args.json, P.matrix_text(rep))
    return 0 if rep["green"] else 1


def _matrix_status_text(st: dict) -> str:
    if st["stage"] == "refused":
        return "refused\n" + "\n".join(f"   {p}" for p in st["problems"]) + f"\n   next: {st['next']}"
    row = st["next_row"]
    where = (f"{row['id']} ({row['site']}, {'awaiting sign-off' if row['awaiting_signoff'] else row['status']})"
             if row else "nothing blocks")
    return f"{st['stage']}  next row: {where}\n   next: {st['next'] or 'nothing to do'}"


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
        if status:
            p.add_argument("--matrix", type=Path, help="also name the parity matrix's next blocking row")
            p.add_argument("--site", choices=P.SITES, help="with --matrix: one site only")
    pp = sub.add_parser("parity", help="live pages vs the manifest (read-only GETs), or the parity matrix's gap")
    src = pp.add_mutually_exclusive_group(required=True)
    src.add_argument("--manifest", type=Path)
    src.add_argument("--matrix", type=Path, help="scripts/roomkit/parity-matrix.yaml: report rows by status per site")
    src.add_argument("--search", type=Path, metavar="LIVE.json",
                     help="parity.search: live search results (search_parity.py documents the file) vs the built room's "
                          "own search, with --out ROOM")
    src.add_argument("--entities", type=Path, metavar="LIVE.json",
                     help="parity.entities: the live entities (entity_parity.py documents the file) vs the built "
                          "room's entity pages, with --out ROOM")
    src.add_argument("--entities-from", type=Path, metavar="PAGES.tsv",
                     help="print the live file for --entities from pages fetched by exporters/fetch-entity-pages.sh "
                          "(with --site)")
    src.add_argument("--passages", type=Path, metavar="LIVE.json",
                     help="parity.passages: the live passage route's answers (passage_parity.py documents the file) "
                          "vs the built room, with --out ROOM")
    src.add_argument("--passages-fetch", action="store_true",
                     help="print the live file for --passages: paced public GETs of a sample of --out ROOM")
    pp.add_argument("--sample", type=int, default=10, help="with --passages-fetch: pages (and spans) to ask for (default 10)")
    pp.add_argument("--keys", type=Path, help="with --passages-fetch: curated stable_keys to ask ggrr/v1/citation for, one a line")
    pp.add_argument("--pace", type=float, default=2.0, help="with --passages-fetch: seconds between requests (default 2)")
    pp.add_argument("--out", type=Path, help="with --search, --entities or --passages: the built room")
    pp.add_argument("--top", type=int, default=SP.TOP_N, help=f"with --search: N, the live hits must be in the room's top N (default {SP.TOP_N})")
    pp.add_argument("--site", choices=P.SITES, help="with --matrix: one site only; with --entities-from: whose pages")
    pp.add_argument("--pause", type=float, default=1.0, help="seconds between requests (default 1)")
    pp.add_argument("--json", action="store_true")
    pp.add_argument("--pages", type=Path, help="answer from a fetched-pages file instead of HTTP (exporters/*-fetch-pages.sh)")
    vp = sub.add_parser("vendor", help="the room's core copied into another codebase (Civica), and its drift")
    vs = vp.add_subparsers(dest="vendor_command", required=True)
    for q in (vs.add_parser("write", help="copy the core into --to and pin it to this commit"),
              vs.add_parser("check", help="compare the copy with its pin and with the source; changes nothing")):
        q.add_argument("--to", required=True, type=Path, help="the copy's package directory (civica/app/room)")
        q.add_argument("--json", action="store_true")
    kp = sub.add_parser("pack", help="site packs")
    ks = kp.add_subparsers(dest="pack_command", required=True)
    ki = ks.add_parser("import", help="derive a pack's tokens from its design-tokens file through a map")
    ki.add_argument("--map", required=True, type=Path, help="packs/<site>/tokens.map.json")
    ki.add_argument("--write", action="store_true", help="write the pack (default: show what would change)")
    ki.add_argument("--json", action="store_true")
    dp = sub.add_parser("diff", help="what a publish must purge and remove, from the old and new locks")
    dp.add_argument("--old", required=True, type=Path)
    dp.add_argument("--new", required=True, type=Path)
    dp.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "vendor":
        return _vendor_cmd(args)
    if args.command == "pack":
        return _pack_import_cmd(args)
    if args.command == "diff":
        old = json.loads(args.old.read_text()) if args.old.is_file() else {}
        d = diff_locks(old, json.loads(args.new.read_text()))
        _print(d, args.json, "\n".join(f"{k}: {len(v)}" + "".join(f"\n   {p}" for p in v) for k, v in d.items()))
        return 0

    if args.command == "parity" and args.matrix:
        return _matrix_cmd(args)
    if args.command == "parity" and args.search:
        if not args.out:
            parser.error("parity --search needs --out ROOM")
        try:
            rep = SP.run(args.search, args.out, args.top, P.SITES)
        except (SP.SearchParityError, OSError, ValueError) as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        _print(rep, args.json, SP.text(rep))
        return 0 if rep["ok"] else 1
    if args.command == "parity" and args.entities_from:
        if not args.site:
            parser.error("parity --entities-from needs --site")
        try:
            head, pages = EP.read_pages_tsv(args.entities_from)
            live = EP.live_from_pages(args.site, head, pages)
        except (EP.EntityParityError, OSError, ValueError) as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(live, indent=1, sort_keys=True))
        return 0
    if args.command == "parity" and args.entities:
        if not args.out:
            parser.error("parity --entities needs --out ROOM")
        try:
            rep = EP.run(args.entities, args.out, P.SITES)
        except (EP.EntityParityError, OSError, ValueError) as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        _print(rep, args.json, EP.text(rep))
        return 0 if rep["ok"] else 1
    if args.command == "parity" and (args.passages or args.passages_fetch):
        if not args.out:
            parser.error("parity --passages / --passages-fetch needs --out ROOM")
        try:
            room = PP.room_data(args.out)
            if args.passages_fetch:
                # Curated keys: the file's, else a sample of the room's own citations.json.
                keys = args.keys.read_text().split() if args.keys else list(room["citations"])[:args.sample]
                live = PP.fetch(room["api"], PP.plan(room, args.sample, keys), pace=max(args.pace, 1.0))
                print(json.dumps(live, indent=1, sort_keys=True, ensure_ascii=False))
                return 3 if live.get("stopped") else 0
            rep = PP.compare(PP.load_live(args.passages), room)
        except (PP.LiveError, OSError, KeyError, ValueError) as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        _print(rep, args.json, PP.text(rep))
        return 0 if rep["ok"] else 1
    if args.command == "status":
        if not (args.manifest or args.matrix) or bool(args.manifest) != bool(args.out):
            parser.error("status needs --manifest and --out, --matrix, or all three")
        if not args.manifest:
            st = _matrix_state(args.matrix, args.site)
            _print(st, args.json, _matrix_status_text(st))
            return 0

    try:
        m = load(args.manifest)
    except ManifestError as exc:
        print(f"roomkit: {exc}", file=sys.stderr)
        return 2

    if args.command in ("build", "check", "status"):
        try:
            pack = _load_pack(args.site_pack)
        except (K.PackError, P.MatrixError) as exc:
            print("roomkit: site pack refused:\n" + "\n".join(f"   {x}" for x in exc.problems), file=sys.stderr)
            return 2

    if args.command == "status":
        try:
            st = _state(m, args.out, args.mount, args.noindex, pack)
        except ValueError as exc:
            print(f"roomkit: {exc}", file=sys.stderr)
            return 2
        if args.matrix:
            st["parity"] = _matrix_state(args.matrix, args.site)
        _print(st, args.json, f"{st['stage']}  ({st.get('documents', 0)} documents)\n"
                              f"   next: {st['next'] or 'nothing to do'}" + _excluded_lines(m)
               + ("\nparity matrix: " + _matrix_status_text(st["parity"]) if args.matrix else ""))
        return 0

    if m.refusals:
        return _refused(m, args.json)

    if args.command == "parity":
        res = (P.run(m, get=P.pages_from_file(args.pages), pause=0) if args.pages
               else P.run(m, pause=args.pause))
        bad = [r for r in res if not r["ok"]]
        _print({"checked": len(res), "differ": bad, "excluded": [{"slug": s, "problem": w} for s, w in m.excluded]},
               args.json,
               f"{'AGREES' if not bad else 'DIFFERS'}: {len(res) - len(bad)}/{len(res)} live pages match the manifest"
               + "".join(f"\n   {r['slug']}: {'; '.join(r['problems'])}" for r in bad) + _excluded_lines(m))
        return 1 if bad else 0

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
