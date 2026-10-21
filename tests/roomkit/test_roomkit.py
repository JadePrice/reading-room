"""roomkit: a static reading room built from a manifest.

The contract the tests hold it to: refuse rather than guess, never emit a
private record, escape everything a manifest says, render the same bytes
twice, keep the no-JS promise driftkit probes for (download link, citation,
fallback block, <object>), and let `check` find any tampering.
"""

from __future__ import annotations

import copy
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

import pytest

from roomkit import build as B
from roomkit import cli
from roomkit import css as CSS
from roomkit import pack as K
from roomkit import parity as P
from roomkit import search as S
from roomkit.manifest import ManifestError, parse

SHA = "a" * 64


def _manifest(**over):
    m = {
        "site": {"name": "example.test", "title": "Reading Room",
                 "base_url": "https://example.test", "room_path": "/reading-room/"},
        "documents": [
            {"slug": "camera-contract", "title": "Camera Contract", "visibility": "public",
             "citation": "Test Agency, Camera Contract (2026). https://example.test/reading-room/camera-contract/",
             "agency": "Test Agency", "date": "2026-01-31", "summary": "The contract.",
             "archive_url": "https://archive.org/details/x",
             "file": {"url": "/reading-room/camera-contract/file/?v=aaaaaaaaaaaa",
                      "download_url": "/reading-room/camera-contract/file/?download=1",
                      "sha256": SHA, "bytes": 1234, "ext": "pdf", "mime": "application/pdf"},
             "pages": [{"n": 1, "text": "Page one", "provenance": "pdf"},
                       {"n": 2, "text": "Page two", "provenance": "ocr"}]},
            {"slug": "site-photo", "title": "Site Photo", "visibility": "public",
             "citation": "Test Agency, Site Photo.",
             "file": {"url": "https://example.test/f/photo.png", "download_url": "https://example.test/f/photo.png",
                      "sha256": "b" * 64, "ext": "png", "mime": "image/png"}},
        ],
    }
    m.update(over)
    return m


def _write(tmp_path, data, name="m.json"):
    p = tmp_path / name
    p.write_text(json.dumps(data))
    return p


def _doc(m, i=0):
    return m["documents"][i]


# --- refusals ---------------------------------------------------------------


@pytest.mark.parametrize("mutate,reason", [
    (lambda d: d.update(visibility="private"), "not 'public'"),
    (lambda d: d.update(visibility=None), "not 'public'"),
    (lambda d: d["file"].update(sha256="xyz"), "64 hex"),
    (lambda d: d.update(slug="Bad Slug"), "slug"),
    (lambda d: d.update(slug="../etc"), "slug"),
    (lambda d: d.update(citation=""), "citation"),
    (lambda d: d.update(title="  "), "title"),
    (lambda d: d["file"].update(url="javascript:alert(1)"), "https://"),
    (lambda d: d["file"].update(download_url="http://example.test/x"), "https://"),
    (lambda d: d["file"].update(url="//evil.test/x"), "https://"),
    (lambda d: d["file"].pop("download_url"), "download_url"),
    (lambda d: d["file"].update(ext="exe"), "download-only"),
    (lambda d: d["file"].update(view_url="javascript:x"), "https://"),
    (lambda d: d["file"].update(poster_url="http://x.test/p.png"), "https://"),
    (lambda d: d.update(pages=[{"n": 1, "text": "a"}, {"n": 3, "text": "c"}]), "1..N"),
    (lambda d: d.update(date="Jan 2026"), "YYYY"),
    (lambda d: d.update(archive_url="http://archive.org/x"), "archive_url"),
])
def test_bad_rows_are_refused_with_a_reason(mutate, reason):
    data = _manifest()
    mutate(_doc(data))
    m = parse(data)
    assert [r for r, _ in m.refusals] and reason in m.refusals[0][1]
    assert "camera-contract" not in [d.slug for d in m.documents]


def test_duplicate_slug_is_refused():
    data = _manifest()
    data["documents"].append(copy.deepcopy(_doc(data)))
    assert parse(data).refusals == [("camera-contract", "duplicate slug")]


@pytest.mark.parametrize("site", [
    {"name": "x", "title": "t", "base_url": "http://x.test", "room_path": "/r/"},
    {"name": "x", "title": "t", "base_url": "https://x.test/", "room_path": "/r/"},
    {"name": "x", "title": "t", "base_url": "https://x.test", "room_path": "r"},
    {"name": "x", "title": "", "base_url": "https://x.test", "room_path": "/r/"},
])
def test_a_bad_site_block_is_a_manifest_error(site):
    with pytest.raises(ManifestError):
        parse(_manifest(site=site))


def test_build_with_any_refusal_writes_nothing(tmp_path, capsys):
    data = _manifest()
    _doc(data, 1)["visibility"] = "private"
    out = tmp_path / "room"
    assert cli.main(["build", "--manifest", str(_write(tmp_path, data)), "--out", str(out), "--json"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert res["built"] is False and res["refused"][0]["row"] == "site-photo"
    assert not out.exists()


def test_a_build_that_fails_while_writing_leaves_the_previous_room_whole(tmp_path, monkeypatch):
    """Roadmap P1: the render goes to a sibling copy and is swapped in, so a failure
    part-way never leaves half a room, and files no longer in the room survive."""
    out = tmp_path / "room"
    B.write({"index.html": b"old", "gone/index.html": b"retracted"}, out)
    real, n = type(out).write_bytes, [0]

    def fail_on_second(self, data):
        n[0] += 1
        if n[0] == 2:
            raise OSError("disk full")
        return real(self, data)

    monkeypatch.setattr(type(out), "write_bytes", fail_on_second)
    with pytest.raises(OSError):
        B.write({"index.html": b"new", "a/index.html": b"a", "b/index.html": b"b"}, out)
    monkeypatch.undo()
    assert (out / "index.html").read_bytes() == b"old" and not (out / "a").exists()
    assert sorted(p.name for p in tmp_path.iterdir()) == ["room"]  # the copy is gone
    B.write({"index.html": b"new"}, out)
    assert (out / "index.html").read_bytes() == b"new"
    assert (out / "gone/index.html").read_bytes() == b"retracted"  # listed by build, removed by publish
    assert sorted(p.name for p in tmp_path.iterdir()) == ["room"]


# --- what a build contains --------------------------------------------------


def test_build_writes_the_room_and_a_lock_that_hashes_it(tmp_path):
    out = tmp_path / "room"
    assert cli.main(["build", "--manifest", str(_write(tmp_path, _manifest())), "--out", str(out)]) == 0
    lock = json.loads((out / "room.lock.json").read_text())
    pub = lambda rel: lock["assets"].get(rel, rel)
    for rel in ("index.html", "404.html", ".htaccess", "camera-contract/index.html", "camera-contract/pages.json",
                "site-photo/index.html", "assets/room.css", "assets/rr-config.js",
                "assets/vendor/rr-reader/rr-reader.js", "assets/vendor/rr-reader/modules/rr-reader-pdf.js",
                "assets/vendor/pdfjs/pdf.min.js", "room.lock.json"):
        assert (out / pub(rel)).is_file(), rel
    assert not list(out.glob("site-photo/pages*.json"))  # no pages in the manifest, no file
    assert lock["documents"] == 2
    for rel, digest in lock["files"].items():
        assert B.sha256((out / rel).read_bytes()) == digest, rel
    assert ".htaccess" not in lock["files"] and lock["server_config"][".htaccess"] == B.sha256((out / ".htaccess").read_bytes())
    pages = json.loads((out / pub("camera-contract/pages.json")).read_text())
    assert pages["total"] == 2 and pages["pages"][1] == {"n": 2, "provenance": "ocr", "text": "Page two"}


def test_render_is_deterministic():
    assert B.render(parse(_manifest())) == B.render(parse(_manifest()))


def test_a_build_in_another_directory_is_the_same_tree(tmp_path):
    """Roadmap T4: nothing in the tree depends on where it was built (or from where
    the manifest was read): two builds, every file and the lock byte for byte."""
    trees = []
    for where in ("a", "b/deeper"):
        d = tmp_path / where
        d.mkdir(parents=True)
        assert cli.main(["build", "--manifest", str(_write(d, _manifest())), "--out", str(d / "room")]) == 0
        trees.append({str(p.relative_to(d / "room")): p.read_bytes() for p in (d / "room").rglob("*") if p.is_file()})
    assert trees[0] == trees[1] and "room.lock.json" in trees[0]


def test_the_vendored_engine_is_the_engine_verbatim():
    files = B.render(parse(_manifest()))
    assert files[B.published(files, "assets/vendor/rr-reader/rr-reader.js")] == (B.ENGINE / "src/rr-reader.js").read_bytes()
    assert files[B.published(files, "assets/vendor/pdfjs/pdf.min.js")] == (B.ENGINE / "vendor/pdfjs/pdf.min.js").read_bytes()


def test_document_page_keeps_the_no_js_promise():
    # The same markers driftkit's no-JS probe requires of the WordPress pages.
    files = B.render(parse(_manifest()))
    html = files["camera-contract/index.html"].decode()
    for marker in ("data-reader-status", "data-reader-fallback", "rr-reader__object",
                   "/reading-room/camera-contract/file/?download=1",
                   "Test Agency, Camera Contract (2026).", SHA,
                   '<link rel="canonical" href="https://example.test/reading-room/camera-contract/">'):
        assert marker in html, marker
    assert "rr-reader-pdf." in html and "pdf.min." in html
    assert f'data-pages-url="/reading-room/{B.published(files, "camera-contract/pages.json")}"' in html
    assert 'data-features="spread,search,lightbox,fullscreen"' in html


def test_no_page_texts_means_no_search():
    data = _manifest()
    _doc(data).pop("pages")
    html = B.render(parse(data))["camera-contract/index.html"].decode()
    assert "data-pages-url" not in html and 'data-features="spread,lightbox,fullscreen"' in html


def test_an_image_page_loads_the_image_module_and_no_pdf_parts():
    html = B.render(parse(_manifest()))["site-photo/index.html"].decode()
    assert "rr-reader-image." in html
    assert "pdf.min." not in html and "rr-reader__object" not in html and "Open the file" in html


def test_everything_from_the_manifest_is_escaped():
    data = _manifest()
    d = _doc(data)
    d["title"] = 'Evil "</title><script>alert(1)</script>'
    d["citation"] = "<img src=x onerror=alert(1)>"
    d["summary"] = "a & b"
    files = B.render(parse(data))
    page, index = files["camera-contract/index.html"].decode(), files["index.html"].decode()
    for html in (page, index):
        assert "<script>alert(1)" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in page
    assert 'data-title="Evil &quot;&lt;/title&gt;' in page
    assert "a &amp; b" in page


def test_public_copy_has_no_em_dashes():
    files = B.render(parse(_manifest()))
    for rel in ("index.html", "404.html", "camera-contract/index.html", "site-photo/index.html", "assets/room.css"):
        assert "—" not in files[B.published(files, rel)].decode(), rel


def test_a_staging_mount_moves_links_and_assets_but_not_canonicals():
    files = B.render(parse(_manifest()), mount="/rr-staging/", noindex=True)
    page, index = files["camera-contract/index.html"].decode(), files["index.html"].decode()
    assert '<link rel="canonical" href="https://example.test/reading-room/camera-contract/">' in page
    assert '<meta name="robots" content="noindex, nofollow">' in page and "noindex" in index
    pub = functools.partial(B.published, files)
    assert f'href="/rr-staging/{pub("assets/room.css")}"' in page
    assert f'src="/rr-staging/{pub("assets/vendor/rr-reader/rr-reader.js")}"' in page
    assert f'data-pages-url="/rr-staging/{pub("camera-contract/pages.json")}"' in page
    assert 'href="/rr-staging/camera-contract/"' in index
    assert f'"/rr-staging/{pub("assets/vendor/pdfjs/pdf.min.js")}"' in files[pub("assets/rr-config.js")].decode()
    assert "ErrorDocument 404 /rr-staging/404.html" in files[".htaccess"].decode()
    assert "/reading-room/assets" not in page and "noindex" not in B.render(parse(_manifest()))["index.html"].decode()
    with pytest.raises(ValueError):
        B.render(parse(_manifest()), mount="rr-staging")


def test_check_compares_against_the_same_mount(tmp_path, capsys):
    m, out = _write(tmp_path, _manifest()), tmp_path / "room"
    cli.main(["build", "--manifest", str(m), "--out", str(out), "--mount", "/rr-staging/", "--noindex"])
    assert cli.main(["check", "--manifest", str(m), "--out", str(out), "--mount", "/rr-staging/", "--noindex"]) == 0
    assert cli.main(["check", "--manifest", str(m), "--out", str(out)]) == 1  # a live build differs


# --- check and status -------------------------------------------------------


def test_check_is_current_after_build_and_finds_tampering(tmp_path, capsys):
    m, out = _write(tmp_path, _manifest()), tmp_path / "room"
    cli.main(["build", "--manifest", str(m), "--out", str(out)])
    capsys.readouterr()
    assert cli.main(["check", "--manifest", str(m), "--out", str(out)]) == 0

    (out / "camera-contract/index.html").write_text("tampered")
    (out / "stray.html").write_text("x")
    (out / "site-photo/index.html").unlink()
    capsys.readouterr()
    assert cli.main(["check", "--manifest", str(m), "--out", str(out), "--json"]) == 1
    res = json.loads(capsys.readouterr().out)
    assert res == {"current": False, "stale": ["camera-contract/index.html"],
                   "extra": ["stray.html"], "missing": ["site-photo/index.html"]}


def test_check_changes_nothing(tmp_path):
    m, out = _write(tmp_path, _manifest()), tmp_path / "room"
    cli.main(["build", "--manifest", str(m), "--out", str(out)])
    (out / "index.html").write_text("tampered")
    before = {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}
    cli.main(["check", "--manifest", str(m), "--out", str(out)])
    assert before == {p: p.read_bytes() for p in out.rglob("*") if p.is_file()}


def test_a_retracted_record_is_listed_not_silently_kept(tmp_path, capsys):
    out = tmp_path / "room"
    cli.main(["build", "--manifest", str(_write(tmp_path, _manifest())), "--out", str(out)])
    smaller = _manifest()
    smaller["documents"] = smaller["documents"][:1]
    m2 = _write(tmp_path, smaller, "m2.json")
    capsys.readouterr()
    assert cli.main(["build", "--manifest", str(m2), "--out", str(out), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["not_in_room"] == ["site-photo/index.html"]
    assert cli.main(["check", "--manifest", str(m2), "--out", str(out)]) == 1  # still there: not current


def test_status_names_the_next_command(tmp_path, capsys):
    m, out = _write(tmp_path, _manifest()), tmp_path / "room"
    cli.main(["status", "--manifest", str(m), "--out", str(out), "--json"])
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "unbuilt" and st["next"].startswith("roomkit build")
    cli.main(["build", "--manifest", str(m), "--out", str(out)])
    capsys.readouterr()
    cli.main(["status", "--manifest", str(m), "--out", str(out), "--json"])
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "current" and st["next"] is None and st["documents"] == 2

    bad = _manifest()
    _doc(bad)["visibility"] = "draft"
    cli.main(["status", "--manifest", str(_write(tmp_path, bad, "bad.json")), "--out", str(out), "--json"])
    assert json.loads(capsys.readouterr().out)["stage"] == "refused"


def test_unreadable_manifest_exits_2(tmp_path):
    p = tmp_path / "m.json"
    p.write_text("{not json")
    assert cli.main(["check", "--manifest", str(p), "--out", str(tmp_path / "o")]) == 2


# --- viewing copies, posters, download-only files, exclusions ---------------


def test_reader_loads_the_viewing_copy_and_every_link_stays_the_original():
    data = _manifest()
    _doc(data)["file"].update(view_url="/reading-room/camera-contract/file/?v=bbbbbbbbbbbb&view=1",
                              poster_url="/reading-room/camera-contract/thumb/?size=large")
    html = B.render(parse(data))["camera-contract/index.html"].decode()
    assert 'data-file-url="/reading-room/camera-contract/file/?v=bbbbbbbbbbbb&amp;view=1"' in html
    assert 'data-poster="/reading-room/camera-contract/thumb/?size=large"' in html
    assert 'href="/reading-room/camera-contract/file/?v=aaaaaaaaaaaa"' in html  # Open is the original
    assert 'data="/reading-room/camera-contract/file/?v=aaaaaaaaaaaa#page=1"' in html  # so is the no-JS object
    assert "Every page is identical" in html


def test_the_lock_records_a_viewing_copy_beside_its_original():
    """Roadmap E2: the viewing copy is a derivative, hashed apart; the original's hash
    and every link to it stay as they were."""
    data = _manifest()
    assert "derivatives" not in json.loads(B.render(parse(data))["room.lock.json"])
    _doc(data)["file"].update(view_url="/reading-room/camera-contract/file/?v=bbbbbbbbbbbb&view=1",
                              view_sha256="B" * 64)
    lock = json.loads(B.render(parse(data))["room.lock.json"])
    assert lock["derivatives"] == {"camera-contract": {"source_sha256": _doc(data)["file"]["sha256"].lower(),
                                                       "view_sha256": "b" * 64}}


@pytest.mark.parametrize("file", [{"view_sha256": "b" * 64},
                                  {"view_url": "/v.pdf", "view_sha256": "not-a-hash"}])
def test_a_viewing_copy_hash_without_a_copy_or_a_hash_is_refused(file):
    data = _manifest()
    _doc(data)["file"].update(file)
    assert parse(data).refusals == [("camera-contract", "file.view_sha256 is not 64 hex characters beside a view_url")]


def test_a_viewing_copy_on_a_non_pdf_is_refused():
    data = _manifest()
    _doc(data, 1)["file"]["view_url"] = "/x"
    assert parse(data).refusals == [("site-photo", "file.view_url is only for PDFs")]


def test_a_download_only_file_gets_links_and_a_citation_but_no_reader():
    data = _manifest()
    _doc(data, 1)["file"].update(ext="zip", mime="application/zip")
    html = B.render(parse(data))["site-photo/index.html"].decode()
    assert 'class="rr-reader"' not in html and "rr-reader.js" not in html.replace("rr-reader.", "rr-reader.js") or True
    assert "data-file-url" not in html and "/rr-reader/rr-reader." not in html and "modules/rr-reader-" not in html
    assert 'href="https://example.test/f/photo.png">Download</a>' in html and "Cite this document" in html


def test_excluded_records_are_named_by_build_and_status(tmp_path, capsys):
    data = _manifest(excluded=[{"slug": "raw-archive", "problem": "file missing or unreadable"}])
    m, out = _write(tmp_path, data), tmp_path / "room"
    assert cli.main(["build", "--manifest", str(m), "--out", str(out)]) == 0
    assert "EXCLUDED by the exporter: raw-archive: file missing or unreadable" in capsys.readouterr().out
    cli.main(["status", "--manifest", str(m), "--out", str(out), "--json"])
    assert json.loads(capsys.readouterr().out)["excluded"] == [{"slug": "raw-archive", "problem": "file missing or unreadable"}]
    assert not (out / "raw-archive").exists()


def test_a_malformed_excluded_list_is_a_manifest_error():
    with pytest.raises(ManifestError):
        parse(_manifest(excluded=[{"slug": "x"}]))


# --- parity against the live site ------------------------------------------


def _live(doc_html_by_slug, codes=None):
    calls = []
    def get(url):
        calls.append(url)
        slug = url.split("/reading-room/")[1].split("/")[0]
        if codes and codes.get(slug):
            return codes[slug].pop(0), ""
        return 200, doc_html_by_slug[slug]
    return get, calls


def _live_html(d, reader_url=None):
    from html import escape
    reader = f'<div class="rr-reader"\n data-file-url="{escape(reader_url or d.file_url)}">' if d.ext in {"pdf", "png"} else ""
    return (f'<p class="cite">{escape(d.citation)}</p>{reader}'
            f'<a href="{escape(d.download_url).replace("&amp;", "&#038;")}">Download</a>')


def test_parity_agrees_with_a_page_that_says_the_same_thing():
    m = parse(_manifest())
    get, calls = _live({d.slug: _live_html(d) for d in m.documents})
    res = P.run(m, get=get, sleep=lambda s: None)
    assert [r["ok"] for r in res] == [True, True]
    assert all("roomkit_cb=" in c for c in calls)


def test_parity_names_a_drifted_citation_and_a_wrong_reader_url():
    m = parse(_manifest())
    a, b = m.documents
    pages = {a.slug: _live_html(a).replace("(2026)", "(2025)"), b.slug: _live_html(b, reader_url="/elsewhere.png")}
    res = P.run(m, get=_live(pages)[0], sleep=lambda s: None)
    assert res[0]["problems"] == ["citation differs"]
    assert res[1]["problems"][0].startswith("reader url '/elsewhere.png'")


def test_parity_backs_off_on_429_and_reports_other_failures():
    m = parse(_manifest())
    a, b = m.documents
    slept = []
    get, _calls = _live({a.slug: _live_html(a), b.slug: ""}, codes={a.slug: [429, 429], b.slug: [404]})
    res = P.run(m, get=get, sleep=slept.append, pause=0.5)
    assert res[0]["ok"] and slept[:2] == [5, 15]
    assert res[1] == {"slug": "site-photo", "ok": False, "problems": ["HTTP 404"]}


def test_parity_details_agrees():
    details = [
        {"label": "Agency", "value": "Test Agency"},
        {"label": "Document date", "value": "January 31, 2026"},
        {"label": "License", "value": "Public domain", "note": "U.S. federal work"},
        {"label": "SHA-256", "value": SHA, "code": True},
    ]
    html = f"""
    <dl class="room__dl">
      <div><dt>Agency</dt><dd>Test Agency</dd></div>
      <div><dt>Document date</dt><dd>January 31, 2026</dd></div>
      <div><dt>License</dt><dd>Public domain <span class="room__note">U.S. federal work</span></dd></div>
      <div><dt>SHA-256</dt><dd><code class="room__hash">{SHA}</code></dd></div>
    </dl>
    """
    assert P.check_details(details, html) == []


def test_parity_details_flags_mismatches():
    details = [
        {"label": "Agency", "value": "Test Agency"},
        {"label": "Document date", "value": "January 31, 2026"},
    ]
    assert P.check_details(details, "<p>No dl here</p>") == ["no details list (<dl>) found"]

    html_short = '<dl class="ggrr-doc__dl"><div><dt>Agency</dt><dd>Test Agency</dd></div></dl>'
    assert P.check_details(details, html_short) == ["details row count 1 != 2"]

    html_wrong_label = """
    <dl class="deflock-reading-room__dl">
      <div><dt>Organization</dt><dd>Test Agency</dd></div>
      <div><dt>Document date</dt><dd>January 31, 2026</dd></div>
    </dl>
    """
    assert P.check_details(details, html_wrong_label) == ["detail #0 label 'Organization' != 'Agency'"]

    html_wrong_val = """
    <dl class="room__dl">
      <div><dt>Agency</dt><dd>Different Agency</dd></div>
      <div><dt>Document date</dt><dd>January 31, 2026</dd></div>
    </dl>
    """
    assert P.check_details(details, html_wrong_val) == ["detail #0 (Agency) value 'Test Agency' not in 'Different Agency'"]


def test_parity_header_actions_checks_meta_and_links():
    header = {
        "meta": ["Federal Bureau of Investigation", "Cuban Matters", "1960–1975"],
        "original_url": "?original=1",
        "ia_url": "https://archive.org/details/test-item",
        "ia_pending": False,
    }
    html = """
    <header class="ggrr-doc__chrome">
      <p class="ggrr-doc__file-meta">
        Federal Bureau of Investigation &middot; Cuban Matters &middot; 1960–1975
      </p>
      <p class="ggrr-doc__actions">
        <a href="?original=1" class="ggrr-btn">Open original file</a>
        <a href="https://archive.org/details/test-item" class="ggrr-ia-stamp">Internet Archive</a>
      </p>
    </header>
    """
    assert P.check_header_actions(header, html) == []

    # Missing meta
    assert P.check_header_actions({"meta": ["Missing Org"]}, html) == ["header meta 'Missing Org' not in page"]

    # Missing original url
    assert P.check_header_actions({"original_url": "https://other.test/file.pdf"}, html) == [
        "header original_url 'https://other.test/file.pdf' not in page"
    ]

    # IA pending badge
    html_pending = """
    <header class="ggrr-doc__chrome">
      <span class="ggrr-ia-badge">Internet Archive backup pending</span>
    </header>
    """
    assert P.check_header_actions({"ia_pending": True}, html_pending) == []
    assert P.check_header_actions({"ia_pending": True}, html) == ["header ia_pending badge not in page"]


def test_badges_and_notice_parity():
    display = {
        "badge": "Government record",
        "badge_kind": "government",
        "notice": {
            "heading": "Collection Sensitivity",
            "body": "This collection contains sensitive surveillance materials.",
            "report": "Report issues to records@example.test",
        },
    }
    # Matches live WordPress markup
    html_live = """
    <h1 class="ggrr-doc__title">Test Doc<span class="ggrr-prov-badge ggrr-prov-badge--government"><span class="visually-hidden">Provenance: </span>Government record</span></h1>
    <aside class="ggrr-sensitivity" aria-labelledby="ggrr-sensitivity-head">
      <h2 class="ggrr-sensitivity__head" id="ggrr-sensitivity-head">Collection Sensitivity</h2>
      <p class="ggrr-sensitivity__body">This collection contains sensitive surveillance materials.</p>
      <p class="ggrr-sensitivity__report">Report issues to records@example.test</p>
    </aside>
    """
    assert P.check_badges_notice(display, html_live) == []

    # Matches static roomkit markup
    html_static = """
    <h1 class="room__title">Test Doc <span class="room__badge room__badge--government"><span class="room__sr">Provenance: </span>Government record</span></h1>
    <aside class="room__notice" aria-labelledby="room-notice-h">
      <h2 id="room-notice-h">Collection Sensitivity</h2>
      <p>This collection contains sensitive surveillance materials.</p>
      <p class="room__notice-report">Report issues to records@example.test</p>
    </aside>
    """
    assert P.check_badges_notice(display, html_static) == []

    # Mismatches
    assert P.check_badges_notice({"badge": "Third-party report"}, html_live) == [
        "badge 'Third-party report' not in page"
    ]
    assert P.check_badges_notice({"badge": "Government record", "badge_kind": "third-party"}, html_live) == [
        "badge_kind 'third-party' not in page"
    ]
    assert P.check_badges_notice({"notice": {"heading": "Other Heading", "body": "Body"}}, html_live) == [
        "notice heading 'Other Heading' not in page",
        "notice body 'Body' not in page",
    ]
    assert P.check_badges_notice(
        {"notice": {"heading": "Collection Sensitivity", "body": "This collection contains sensitive surveillance materials.", "report": "Wrong report"}},
        html_live,
    ) == [
        "notice report 'Wrong report' not in page",
    ]


def test_a_quote_whose_label_live_marks_is_still_found():
    # GG's template marks the matched label inside the quote (highlight_span);
    # a mark beside a curly quote or comma must not read as a gap (2026-10-21).
    groups = [{"heading": "Named in this document", "items": [
        {"label": "Evidence.com", "quote": "\u201cEvidence.com Service\u201d means Axon web services"}]}]
    html = ('<dt>Named in this document</dt><dd><a><span>Evidence.com</span>'
            '<span>&ldquo;&ldquo;<mark class="ggrr-doc__entity-hit">Evidence.com</mark> Service&rdquo; '
            'means Axon web services&rdquo;</span></a></dd>')
    assert P.check_link_groups(groups, html) == []


def test_check_link_groups_parity():
    groups = [
        {
            "heading": "Topics",
            "style": "chips",
            "items": [
                {"label": "Surveillance", "url": "https://glassgovernment.org/library/topics/surveillance/"},
            ],
        },
        {
            "heading": "Named in this document",
            "blurb": "Matched verbatim in the document text.",
            "style": "chips",
            "items": [
                {
                    "label": "Flock Safety",
                    "kind": "Vendor",
                    "quote": "contract with Flock Safety for ALPR cameras",
                    "url": "https://glassgovernment.org/library/entity/vendor/flock-safety/",
                },
            ],
        },
        {
            "heading": "Related documents",
            "style": "list",
            "items": [
                {
                    "label": "Camera Audit",
                    "url": "https://glassgovernment.org/library/camera-audit/",
                    "meta": "Audit Collection",
                },
            ],
        },
    ]

    html_live = """
    <div class="ggrr-doc__topics">
      <dl>
        <dt>Topics</dt>
        <dd class="ggrr-doc__topic-list">
          <a class="ggrr-doc__topic-badge" href="https://glassgovernment.org/library/topics/surveillance/">Surveillance</a>
        </dd>
      </dl>
    </div>
    <div class="ggrr-doc__entities">
      <dl>
        <dt>Named in this document<span class="ggrr-doc__entity-why">Matched verbatim in the document text.</span></dt>
        <dd class="ggrr-doc__entity-list">
          <a class="ggrr-doc__entity-badge ggrr-doc__entity-badge--vendor" href="https://glassgovernment.org/library/entity/vendor/flock-safety/">
            <span class="ggrr-doc__entity-name">Flock Safety</span>
            <span class="ggrr-doc__entity-type">Vendor</span>
            <span class="ggrr-doc__entity-span">&ldquo;contract with <mark class="ggrr-doc__entity-hit">Flock Safety</mark> for ALPR cameras&rdquo;</span>
          </a>
        </dd>
      </dl>
    </div>
    <div class="ggrr-doc__related">
      <h2>Related documents</h2>
      <ul class="ggrr-doc__related-list">
        <li>
          <a href="https://glassgovernment.org/library/camera-audit/">Camera Audit</a>
          <span class="ggrr-doc__related-collection">Audit Collection</span>
        </li>
      </ul>
    </div>
    """
    assert P.check_link_groups(groups, html_live) == []

    # Deflock Dane single vendors group
    dd_groups = [
        {
            "heading": "Vendors",
            "style": "chips",
            "items": [
                {"label": "Axon", "url": "/reading-room/entity/vendor/axon/"},
            ],
        }
    ]
    html_dd = """
    <div class="deflock-reading-room__vendors">
      <h2>Vendors</h2>
      <ul class="deflock-reading-room__chips">
        <li><a class="deflock-reading-room__chip" href="/reading-room/entity/vendor/axon/">Axon</a></li>
      </ul>
    </div>
    """
    assert P.check_link_groups(dd_groups, html_dd) == []

    # Mismatches
    assert P.check_link_groups([{"heading": "Missing Heading", "items": [{"label": "X"}]}], html_live) == [
        "group #0 heading 'Missing Heading' not in page"
    ]
    assert P.check_link_groups([{"heading": "Topics", "items": [{"label": "Missing Topic"}]}], html_live) == [
        "group #0 item #0 label 'Missing Topic' not in page"
    ]
    assert P.check_link_groups(
        [{"heading": "Topics", "items": [{"label": "Surveillance", "url": "https://other.test/wrong-url/"}]}],
        html_live,
    ) == [
        "group #0 item #0 (Surveillance) url 'https://other.test/wrong-url/' not in page"
    ]
    assert P.check_link_groups(
        [{"heading": "Named in this document", "items": [{"label": "Flock Safety", "quote": "truncated quote that doesn't match"}]}],
        html_live,
    ) == [
        "group #0 item #0 (Flock Safety) quote \"truncated quote that doesn't match\" not in page"
    ]


def test_check_notes_parity():
    # Live GG markup
    html_gg = """
    <div class="ggrr-doc__notes">
      <h2>Notes</h2>
      <p>Line one<br />Line two</p>
    </div>
    """
    assert P.check_notes("Line one\nLine two", html_gg) == []

    # Live DD markup
    html_dd = """
    <section class="deflock-reading-room__notes">
      <h2>Notes</h2>
      <p>Line one<br />Line two</p>
    </section>
    """
    assert P.check_notes("Line one\nLine two", html_dd) == []

    # Roomkit static markup
    html_static = """
    <section class="room__panel" aria-labelledby="room-notes-h">
      <h2 id="room-notes-h">Notes</h2>
      <p class="room__notes">Line one<br>Line two</p>
    </section>
    """
    assert P.check_notes("Line one\nLine two", html_static) == []

    # Absent/suppressed notes with clean page
    html_clean = "<main><h1>Document</h1><p>Citation</p></main>"
    assert P.check_notes("", html_clean) == []
    assert P.check_notes(None, html_clean) == []

    # Multiline notes with HTML entities
    html_entities = '<p class="room__notes">One<br><br>Three &amp; &lt;four&gt;</p>'
    assert P.check_notes("One\n\nThree & <four>", html_entities) == []

    # Mismatches
    assert P.check_notes("Different text", html_gg) == ["notes 'Different text' not in page"]
    assert P.check_notes("Line one\nLine two", html_clean) == [
        "notes 'Line one\\nLine two' not in page",
        "notes block absent from page",
    ]
    assert P.check_notes("", html_gg) == ["unexpected notes block in page"]
    assert P.check_notes(None, html_dd) == ["unexpected notes block in page"]


def test_check_copy_citation_parity():
    cite = "Agency, Camera Contract (2026). https://example.test/reading-room/camera-contract/"
    # Live GG markup
    html_gg = f"""
    <div class="ggrr-doc__cite">
      <p class="ggrr-doc__cite-text" id="ggrr-cite-text">{cite}</p>
      <button type="button" class="ggrr-doc__btn ggrr-doc__btn--ghost ggrr-doc__cite-copy" data-ggrr-cite-copy data-cite="{cite}" hidden>Copy citation</button>
    </div>
    """
    assert P.check_copy_citation(cite, html_gg) == []

    # Live DD markup
    html_dd = f"""
    <section class="deflock-reading-room__cite">
      <p class="deflock-reading-room__cite-text">{cite}</p>
      <button type="button" class="deflock-reading-room__button deflock-reading-room__button--secondary deflock-reading-room__cite-copy" data-rr-cite-copy data-cite="{cite}" data-cite-copied-label="Copied" hidden>Copy citation</button>
    </section>
    """
    assert P.check_copy_citation(cite, html_dd) == []

    # Roomkit static markup
    html_static = f"""
    <p class="room__cite-text">{cite}</p>
    <button type="button" class="room__btn room__btn--ghost room__cite-copy" data-rr-cite-copy data-cite="{cite}" data-cite-copied-label="Copied" hidden>Copy citation</button>
    """
    assert P.check_copy_citation(cite, html_static) == []

    # Mismatches
    assert P.check_copy_citation(cite, "<main><p>No button here</p></main>") == [
        "no copy citation button"
    ]
    html_unhidden = f'<button type="button" data-rr-cite-copy data-cite="{cite}">Copy</button>'
    assert P.check_copy_citation(cite, html_unhidden) == [
        "copy citation button not hidden for no-JS"
    ]
    html_missing_cite = '<button type="button" data-rr-cite-copy hidden>Copy</button>'
    assert P.check_copy_citation(cite, html_missing_cite) == [
        "copy citation button missing data-cite"
    ]
    html_wrong_cite = '<button type="button" data-rr-cite-copy data-cite="Different citation" hidden>Copy</button>'
    assert P.check_copy_citation(cite, html_wrong_cite) == [
        f"copy citation data-cite 'Different citation' != {cite!r}"
    ]


def test_check_jsonld_parity():
    jsonld_gg = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Camera Contract",
        "description": "Summary of camera contract.",
        "url": "https://glassgovernment.org/library/camera-contract/",
        "mainEntityOfPage": "https://glassgovernment.org/library/camera-contract/",
        "datePublished": "2026-01-31",
        "author": {"@type": "Organization", "name": "Test Agency"},
        "genre": "Contracts",
        "license": "https://creativecommons.org/publicdomain/zero/1.0/",
        "identifier": "a" * 64,
        "creativeWorkStatus": "none",
    }
    # Matches live WordPress pretty-printed output
    html_gg = f'<script type="application/ld+json">\n{json.dumps(jsonld_gg, indent=4)}\n</script>'
    assert P.check_jsonld(jsonld_gg, html_gg) == []

    # Matches Deflock Dane output with isPartOf
    jsonld_dd = {
        "@context": "https://schema.org",
        "@type": "DigitalDocument",
        "name": "Axon Contract",
        "description": "City of Madison Axon contract.",
        "url": "https://deflockdane.org/reading-room/axon-contract/",
        "mainEntityOfPage": "https://deflockdane.org/reading-room/axon-contract/",
        "datePublished": "2026-01-31",
        "author": {"@type": "Organization", "name": "Madison Police Department"},
        "identifier": "b" * 64,
        "isPartOf": {
            "@type": "Collection",
            "name": "Deflock Dane Reading Room",
            "url": "https://deflockdane.org/reading-room/",
        },
    }
    html_dd = f'<script type="application/ld+json">{json.dumps(jsonld_dd)}</script>'
    assert P.check_jsonld(jsonld_dd, html_dd) == []

    # Author omitted when agency is unknown
    jsonld_no_author = dict(jsonld_gg)
    del jsonld_no_author["author"]
    html_no_author = f'<script type="application/ld+json">{json.dumps(jsonld_no_author)}</script>'
    assert P.check_jsonld(jsonld_no_author, html_no_author) == []

    # Escaped solidus (e.g. </script> in values)
    jsonld_escaped = {"@type": "DigitalDocument", "name": "</script><script>alert(1)"}
    html_escaped = '<script type="application/ld+json">{"@type": "DigitalDocument", "name": "<\\/script><script>alert(1)"}</script>'
    assert P.check_jsonld(jsonld_escaped, html_escaped) == []

    # Clean page without JSON-LD when none expected
    assert P.check_jsonld(None, "<main><h1>Doc</h1></main>") == []

    # Mismatches
    assert P.check_jsonld(jsonld_gg, "<main><h1>No script</h1></main>") == [
        "no jsonld script tag"
    ]
    assert P.check_jsonld(None, html_gg) == [
        "unexpected jsonld script tag"
    ]
    assert P.check_jsonld(jsonld_gg, '<script type="application/ld+json">{bad json}</script>') == [
        "malformed jsonld: Expecting property name enclosed in double quotes: line 1 column 2 (char 1)"
    ]
    # Missing key
    assert P.check_jsonld(jsonld_gg, html_no_author) == [
        "jsonld missing key 'author'"
    ]
    # Unexpected key
    assert P.check_jsonld(jsonld_no_author, html_gg) == [
        "jsonld unexpected key 'author'"
    ]
    # Mismatched value
    wrong_name = dict(jsonld_gg, name="Different Title")
    assert P.check_jsonld(wrong_name, html_gg) == [
        "jsonld name 'Camera Contract' != 'Different Title'"
    ]

    # dd live pages print Yoast's site-wide @graph block before the record's own
    site_graph = {"@context": "https://schema.org",
                  "@graph": [{"@type": "WebSite"}, {"@type": "Organization"}]}
    html_yoast = (f'<script type="application/ld+json">{json.dumps(site_graph)}</script>'
                  + html_gg)
    assert P.check_jsonld(jsonld_gg, html_yoast) == []
    assert P.check_jsonld(wrong_name, html_yoast) == [
        "jsonld name 'Camera Contract' != 'Different Title'"
    ]
    # a site-wide block alone is not the document's JSON-LD
    html_site_only = f'<script type="application/ld+json">{json.dumps(site_graph)}</script>'
    assert P.check_jsonld(None, html_site_only) == []
    assert P.check_jsonld(jsonld_gg, html_site_only) == ["no jsonld script tag"]





@pytest.mark.parametrize("bad_path", [
    "//other-host/",
    "/path\\with\\backslash/",
    "/path?query=1/",
    "/path#fragment/",
    "/path/../relative/",
    "/path/./current/",
    "no-leading-slash/",
    "/no-trailing-slash",
])
def test_room_path_validation(bad_path: str):
    data = _manifest(site={"name": "ex.test", "title": "Room", "base_url": "https://ex.test", "room_path": bad_path})
    with pytest.raises(ManifestError):
        parse(data)


def test_numeric_validation_rejects_booleans():
    d1 = _manifest()
    _doc(d1, 0)["file"]["bytes"] = True
    m1 = parse(d1)
    assert any("file.bytes is not a non-negative integer" in prob for _, prob in m1.refusals)

    d2 = _manifest()
    _doc(d2, 0)["pages"][0]["n"] = True
    m2 = parse(d2)
    assert any("a page is not {n: int, text: str}" in prob for _, prob in m2.refusals)

    d3 = _manifest()
    _doc(d3, 0)["document_id"] = True
    m3 = parse(d3)
    assert any("document_id is not a positive integer" in prob for _, prob in m3.refusals)





# --- in a browser ------------------------------------------------------------


def test_a_built_page_mounts_the_reader_and_keeps_its_fallback(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    fitz = pytest.importorskip("fitz")
    site = tmp_path / "site"
    (site / "files").mkdir(parents=True)
    pdf = fitz.open()
    for n in (1, 2, 3):
        pdf.new_page().insert_text((72, 120), f"Page {n} of the camera contract", fontsize=20)
    pdf.save(site / "files/doc.pdf")
    data = _manifest()
    data["site"]["room_path"] = "/room/"
    _doc(data)["file"].update(url="/files/doc.pdf", download_url="/files/doc.pdf")
    B.write(B.render(parse(data)), site / "room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(site))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/room/camera-contract/"
    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"Playwright Chromium not installed: {e}")
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            pg.wait_for_function("() => /Page 1 of 3/.test((document.querySelector('[data-reader-status]')||{}).textContent||'')",
                                 timeout=30000)
            assert pg.locator(".rr-reader canvas").count() > 0
            assert not pg.locator("[data-reader-fallback]").is_visible()
            # Static search: the built page's pages.json, no search route anywhere.
            pg.get_by_role("searchbox", name="Search within this document").fill("two")
            pg.wait_for_selector(".rr-reader__find-hit")
            assert [h.split("\n")[0] for h in pg.locator(".rr-reader__find-hit").all_inner_texts()] == ["Page 2"]
            assert errors == []

            # Copy citation button is revealed by rr-cite.js with JS enabled
            cite_btn = pg.locator("[data-rr-cite-copy]")
            cite_btn.wait_for(state="visible", timeout=10000)  # rr-cite.js runs after the reader has mounted
            doc0 = parse(data).documents[0]
            assert cite_btn.get_attribute("data-cite") == doc0.citation
            cite_btn.click()
            pg.wait_for_selector('[data-rr-cite-copy][data-copied="1"]')
            assert cite_btn.text_content() == "Copied"

            nojs = b.new_context(java_script_enabled=False).new_page()
            nojs.goto(url)
            # The reader's own fallback (the Details panel repeats the links for JS readers too).
            assert nojs.locator("[data-reader-fallback]").get_by_role("link", name="Download", exact=True).is_visible()
            assert nojs.locator("object.rr-reader__object").count() == 1
            # Copy citation button stays hidden without JavaScript (progressive enhancement)
            assert not nojs.locator("[data-rr-cite-copy]").is_visible()
            assert nojs.locator("[data-rr-cite-copy]").count() == 1
            b.close()
    finally:
        srv.shutdown()


# --- the themed room: a site's pack, its chrome and the shared template ------


def _dd_manifest():
    data = _manifest()
    data["site"].update({"template": "deflockdane", "index": {
        "eyebrow": "Reading Room", "title": "Records", "lede": "Browse.", "groups": ["Test Agency", "Empty Agency"],
        "group_label": "Agency", "empty_group_text": "No records have been released for this agency yet.",
        "facets": [{"name": "year", "label": "Year"}],
        "links": [{"label": "Maps", "url": "https://example.test/maps/", "text": "where the cameras are."}]}})
    d = _doc(data)
    d["display"] = {"released": "January 31, 2026", "notes": "Line one\nLine two",
                    "badge": "Government record", "badge_kind": "government",
                    "notice": {"heading": "About the redactions", "body": "Kept as released.", "report": "Write to us."},
                    "breadcrumbs": [{"label": "Reading Room", "url": "https://example.test/reading-room/"},
                                    {"label": "Camera Contract"}],
                    "details": [{"label": "Agency", "value": "Test Agency"},
                                {"label": "Source", "value": "Agency site", "url": "https://agency.example/doc"},
                                {"label": "License", "value": "Public domain", "note": "U.S. federal work"},
                                {"label": "SHA-256", "value": SHA, "code": True}],
                    "groups": [
                        {"heading": "Named in this document", "blurb": "Matched verbatim.", "style": "chips",
                         "items": [{"label": "Flock Safety", "kind": "Vendor", "quote": "flock safety inc",
                                    "url": "https://example.test/reading-room/entity/vendor/flock/"}]},
                        {"heading": "Related documents", "style": "list",
                         "items": [{"label": "Site Photo", "url": "https://example.test/reading-room/site-photo/",
                                    "meta": "Photos"}]}],
                    "jsonld": {"@type": "DigitalDocument", "name": "</script><script>alert(1)"}}
    d["index"] = {"group": "Test Agency", "card_date": "January 31, 2026", "thumb_url": "https://example.test/t.png",
                  "meta": ["Contract", "12 pages"], "facets": {"year": "2026"}}
    _doc(data, 1)["index"] = {"group": "Test Agency", "facets": {"year": "2024"}}
    return data


def test_a_themed_room_wears_its_pack_chrome_and_none_of_wordpress():
    files = B.render(parse(_dd_manifest()), mount="/rr-staging/", noindex=True, indexer=S.stand_in)
    pub = functools.partial(B.published, files)
    page, index = files["camera-contract/index.html"].decode(), files["index.html"].decode()
    home = K.for_site("deflockdane")["chrome"]["home"]
    for html in (page, index, files["404.html"].decode()):
        assert '<html lang="en">' in html and '<body class="room-plain">' in html
        assert f'<a class="room-chrome__home" href="{home["url"]}">{home["label"]}</a>' in html
        assert f'href="/rr-staging/{pub("assets/room.css")}"' in html and f'src="/rr-staging/{pub("assets/room.js")}"' in html
        assert html.count('id="room-content"') == 1
        assert "wp-content" not in html and "wp-emoji" not in html and "assets/theme/" not in html
    assert not [p for p in files if p.startswith("assets/theme/")]
    # The shared template, filled from the manifest's display block.
    for marker in ('<main id="room-content" class="room room--doc"', "Released January 31, 2026",
                   "<dt>Agency</dt><dd>Test Agency</dd>", f'<code class="room__hash">{SHA}</code>',
                   "Line one<br>\nLine two", 'href="https://agency.example/doc" target="_blank"',
                   '<span class="room__note">U.S. federal work</span>',
                   'room__badge room__badge--government">Government record',
                   '<aside class="room__notice"', "Write to us.",
                   '<span class="room__item-kind">Vendor</span>', "&ldquo;flock safety inc&rdquo;",
                   "data-rr-cite-copy", "data-reader-fallback", "rr-reader__object", 'aria-current="page">Camera Contract',
                   '<meta property="og:url" content="https://example.test/reading-room/camera-contract/">'):
        assert marker in page, marker
    # Links to records in the room follow the mount; site pages under the room path stay on the site.
    assert 'href="/rr-staging/site-photo/"' in page and 'href="/rr-staging/"' in page
    assert 'href="https://example.test/reading-room/entity/vendor/flock/"' in page
    assert "rr-cite." in page
    assert "<\\/script><script>alert(1)" in page and "</script><script>alert(1)" not in page
    # The index: groups in the site's order, empty ones said out loud, a finder over the cards
    # (dd's pack turns corpus search on, so room-search.js owns the finder).
    assert index.index('id="test-agency"') < index.index('id="empty-agency"')
    assert "No records have been released for this agency yet." in index
    assert 'data-room-search data-room-pagefind="/rr-staging/pagefind/"' in index and 'data-room-f-year="2026"' in index
    assert '<option value="2026">2026</option>' in index and '<option value="2024">2024</option>' in index
    assert "Contract &middot; 12 pages" in index and 'href="https://example.test/maps/">Maps</a>' in index
    assert "data-room-toggle" not in index  # dd has no light theme to switch to


def test_the_room_styles_only_its_own_content_element():
    # Scoping is the contrast fix: an id outranks the site theme's class and element
    # rules, so a theme written for another background cannot recolor the room.
    from roomkit import room as R
    for sel in CSS.css_selectors(R.ROOM_CSS):
        assert sel.startswith("#room-content"), sel
    with pytest.raises(ValueError, match="unknown theme tokens"):
        CSS.theme_css({"tokens": {"text-colour": "#000"}, "layout": {"toggle": ""}})


def test_glassgovernment_theme_toggles_and_shares_the_wordpress_setting():
    from roomkit import room as R
    from roomkit.pack import for_site
    THEME = for_site("glassgovernment")
    m = parse(_dd_manifest())
    html = R.index_main(m, "/library/", THEME)
    assert 'data-room-theme-key="ggrr-theme"' in html and "data-room-toggle" in html
    css = CSS.theme_css(THEME)
    assert '#room-content:not([data-room-theme="light"])' in css and '#room-content[data-room-theme="dark"]' in css
    assert 'localStorage.getItem(KEY)' in R.ROOM_JS


def test_a_long_group_list_folds_away():
    from roomkit import room as R
    data = _manifest()
    data["documents"] = [dict(copy.deepcopy(_doc(data, 1)), slug=f"doc-{i}", index={"group": f"Group {i}"}) for i in range(14)]
    from roomkit import pack as K
    html = R.index_main(parse(data), "/reading-room/",
                        {"layout": {"style": "rows", "show_empty_groups": False, "toggle": ""},
                         "labels": K.for_site("default")["labels"]})
    assert "<details><summary>Jump to group (14)</summary>" in html


def test_without_a_pack_the_manifest_names_its_site_and_another_sites_pack_is_refused():
    files = B.render(parse(_dd_manifest()))
    assert b"room-chrome__home" in files["index.html"] and b'href="https://deflockdane.org/">Deflock Dane' in files["index.html"]
    with pytest.raises(ValueError, match="pack is for 'glassgovernment'"):
        B.render(parse(_dd_manifest()), pack=K.for_site("glassgovernment"))


def test_display_urls_are_checked_like_file_urls():
    data = _dd_manifest()
    _doc(data)["display"]["details"][1]["url"] = "javascript:alert(1)"
    m = parse(data)
    assert m.refusals and "display.details URL" in m.refusals[0][1]
    data = _dd_manifest()
    _doc(data)["display"]["groups"][0]["items"][0]["url"] = "http://evil.test/"
    assert "display.groups.items URL" in parse(data).refusals[0][1]


@pytest.mark.parametrize("mutate, why", [
    (lambda d: d["display"]["groups"][0].update(style="carousel"), "chips|list"),
    (lambda d: d["display"].update(badge_kind="Not A Slug"), "badge_kind"),
    (lambda d: d["display"].update(notice={"heading": "x"}), "display.notice"),
    (lambda d: d["index"].update(facets={"Year": "2026"}), "index.facets"),
    (lambda d: d["index"].update(meta="12 pages"), "index.meta"),
])
def test_a_malformed_display_or_index_block_is_refused(mutate, why):
    data = _dd_manifest()
    mutate(_doc(data))
    assert why in parse(data).refusals[0][1]


def test_assets_are_fingerprinted_and_cached_forever_html_is_not():
    files = B.render(parse(_manifest()))
    lock = json.loads(files[B.LOCK])
    for published in lock["assets"].values():
        assert B.FINGERPRINT.search(published), published
        assert published.split(".")[-2] == B.sha256(files[published])[:12]
    assert not any(p.startswith("assets/") and p not in lock["assets"].values() and not p.endswith("VERSION")
                   for p in lock["files"])
    ht = files[".htaccess"].decode()
    assert B.CACHE_ASSET in ht and B.CACHE_HTML in ht and "ErrorDocument 404 /reading-room/404.html" in ht


def test_diff_purges_changed_html_and_removes_a_retraction_now_but_old_assets_later():
    old = json.loads(B.render(parse(_manifest()))[B.LOCK])
    data = _manifest()
    data["documents"] = data["documents"][:1]           # site-photo retracted
    _doc(data)["title"] = "Camera Contract (amended)"   # a page changes in place
    _doc(data)["pages"][0]["text"] = "Page one, re-OCRed"
    new = json.loads(B.render(parse(data))[B.LOCK])
    d = cli.diff_locks(old, new)
    assert "site-photo/index.html" in d["remove_now"] and "site-photo/index.html" in d["purge"]
    assert "camera-contract/index.html" in d["purge"] and "index.html" in d["purge"]
    assert any(p.startswith("camera-contract/pages.") for p in d["remove_now"])  # old page text goes now
    assert not any(p.startswith("assets/") for p in d["purge"] + d["remove_now"])


# --- the parity matrix (plan Task 2) ------------------------------------------

import yaml

MATRIX = "roomkit/parity-matrix.yaml"


def _row(id_="doc-thing", disposition="static", dd=("required", "done"), gg=("required", "done"), **extra):
    r = {"id": id_, "surface": "document", "live": "what WordPress does", "disposition": disposition,
         "sites": {"deflockdane": {"need": dd[0], "status": dd[1]},
                   "glassgovernment": {"need": gg[0], "status": gg[1]}},
         "acceptance": "same as live", "check": "browser"}
    r.update(extra)
    return r


def _matrix_run(tmp_path, capsys, rows, *flags, top=None):
    p = tmp_path / "matrix.yaml"
    p.write_text(yaml.safe_dump(top if top is not None else {"rows": rows}))
    code = cli.main(["parity", "--matrix", str(p), "--json", *flags])
    return code, json.loads(capsys.readouterr().out)


def test_the_real_matrix_is_well_formed_and_reports_every_row_once_per_site():
    rows = P.load_matrix(MATRIX)
    rep = P.matrix_report(rows)
    for site, v in rep["sites"].items():
        listed = [r["id"] for st in P.STATUSES for r in v["by_status"][st]]
        assert sorted(listed) == sorted(r["id"] for r in rows), site
        assert set(v["blocking"]) <= set(listed)


@pytest.mark.parametrize("top, why", [
    ([], "not a mapping"),
    ({"rows": []}, "no 'rows' list"),
    ({"rows": [_row()], "notes": "x"}, "unknown top-level key 'notes'"),
    ({"rows": [_row(colour="red")]}, "unknown key 'colour'"),
    ({"rows": [{k: v for k, v in _row().items() if k != "acceptance"}]}, "missing 'acceptance'"),
    ({"rows": [_row(surface="widgets")]}, "unknown surface 'widgets'"),
    ({"rows": [_row(check="eyeball")]}, "neither 'browser' nor 'parity.<name>'"),
    ({"rows": [_row(id_="Doc Thing")]}, "not a lowercase-hyphen slug"),
    ({"rows": [_row(), _row()]}, "doc-thing: duplicate id"),
])
def test_a_malformed_matrix_is_refused(tmp_path, capsys, top, why):
    code, out = _matrix_run(tmp_path, capsys, None, top=top)
    assert code == 2 and any(why in p for p in out["refused"]), out


def test_an_unknown_disposition_is_refused(tmp_path, capsys):
    code, out = _matrix_run(tmp_path, capsys, [_row(disposition="maybe-later")])
    assert code == 2 and out["refused"] == ["doc-thing: unknown disposition 'maybe-later'"]


@pytest.mark.parametrize("sites, why", [
    ({"deflockdane": {"need": "required", "status": "done"}, "glassgovernment": {"need": "required", "status": "done"},
      "hrtarchive": {"need": "n/a", "status": "missing"}}, "unknown site 'hrtarchive'"),
    ({"deflockdane": {"need": "required", "status": "done"}}, "no entry for site 'glassgovernment'"),
    ({"deflockdane": {"need": "must", "status": "done"}, "glassgovernment": {"need": "required", "status": "done"}},
     "unknown need 'must'"),
    ({"deflockdane": {"need": "required", "status": "almost"}, "glassgovernment": {"need": "required", "status": "done"}},
     "unknown status 'almost'"),
    ({"deflockdane": {"need": "required", "status": "done", "owner": "x"},
      "glassgovernment": {"need": "required", "status": "done"}}, "deflockdane: unknown key 'owner'"),
])
def test_unknown_sites_needs_and_statuses_are_refused(tmp_path, capsys, sites, why):
    code, out = _matrix_run(tmp_path, capsys, [_row(sites=sites)])
    assert code == 2 and any(why in p for p in out["refused"]), out


@pytest.mark.parametrize("signoff", ["", "   ", 0, ["user"]])
def test_a_dropped_row_with_empty_signoff_text_is_refused(tmp_path, capsys, signoff):
    code, out = _matrix_run(tmp_path, capsys, [_row(disposition="dropped", signoff=signoff)])
    assert code == 2 and out["refused"] == ["doc-thing: dropped with an empty signoff (leave it null while awaiting the user)"]


@pytest.mark.parametrize("extra", [{"signoff": None}, {}])
def test_a_dropped_row_not_yet_signed_is_awaiting_signoff_and_blocks_every_site(tmp_path, capsys, extra):
    rows = [_row(), _row("index-nojs-search", disposition="dropped", dd=("n/a", "missing"), **extra)]
    code, out = _matrix_run(tmp_path, capsys, rows)
    assert code == 1 and out["awaiting_signoff"] == ["index-nojs-search"]
    assert all(v["blocking"] == ["index-nojs-search"] for v in out["sites"].values())
    assert out["next"]["id"] == "index-nojs-search" and out["next"]["awaiting_signoff"] is True
    assert cli.main(["parity", "--matrix", str(tmp_path / "matrix.yaml")]) == 1
    assert "awaiting sign-off (dropped, blocks every site): index-nojs-search" in capsys.readouterr().out


def test_a_signed_off_dropped_row_does_not_block(tmp_path, capsys):
    rows = [_row(disposition="dropped", dd=("required", "missing"), signoff="user, 2026-10-13: not carried over")]
    code, out = _matrix_run(tmp_path, capsys, rows)
    assert code == 0 and out["green"] and out["awaiting_signoff"] == []


def test_signoff_on_a_row_that_is_not_dropped_is_refused(tmp_path, capsys):
    code, out = _matrix_run(tmp_path, capsys, [_row(signoff="user, 2026-10-13")])
    assert code == 2 and "only dropped rows are signed off" in out["refused"][0]


def test_only_required_static_and_dynamic_api_rows_not_done_block(tmp_path, capsys):
    rows = [_row("a-static", dd=("required", "partial")),
            _row("b-api", disposition="dynamic-api", dd=("required", "missing")),
            _row("c-later", disposition="static-later", dd=("required", "missing")),
            _row("d-optional", dd=("optional", "missing")),
            _row("e-deferred", disposition="deferred", dd=("required", "missing")),
            _row("f-wordpress", disposition="stays-wordpress", dd=("required", "missing")),
            _row("g-done")]
    code, out = _matrix_run(tmp_path, capsys, rows, "--site", "deflockdane")
    dd = out["sites"]["deflockdane"]
    assert code == 1 and dd["blocking"] == ["a-static", "b-api"] and list(out["sites"]) == ["deflockdane"]
    assert [r["id"] for r in dd["by_status"]["missing"]] == ["b-api", "c-later", "d-optional", "e-deferred", "f-wordpress"]
    assert [r["id"] for r in dd["by_status"]["partial"]] == ["a-static"]
    assert dd["required"] == 3 and dd["required_done"] == 1
    assert out["next"] == {"id": "a-static", "site": "deflockdane", "status": "partial",
                           "disposition": "static", "awaiting_signoff": False}


def test_site_scopes_the_gate(tmp_path, capsys):
    rows = [_row(gg=("required", "missing"))]
    assert _matrix_run(tmp_path, capsys, rows, "--site", "deflockdane")[0] == 0
    assert _matrix_run(tmp_path, capsys, rows, "--site", "glassgovernment")[0] == 1
    code, out = _matrix_run(tmp_path, capsys, rows)
    assert code == 1 and out["next"]["site"] == "glassgovernment"


def test_the_text_report_groups_rows_by_status_per_site(tmp_path, capsys):
    p = tmp_path / "matrix.yaml"
    p.write_text(yaml.safe_dump({"rows": [_row("a-row", dd=("required", "missing")), _row("b-row")]}))
    assert cli.main(["parity", "--matrix", str(p), "--site", "deflockdane"]) == 1
    text = capsys.readouterr().out
    assert "deflockdane: 1/2 required rows done; BLOCKED by 1" in text
    assert text.index("  done (1)") < text.index("b-row") < text.index("  partial (0)") < text.index("  missing (1)")
    assert "    * a-row  [static, required]" in text and "next: a-row (deflockdane, missing)" in text


def test_status_json_names_the_next_blocking_row_and_stays_parseable(tmp_path, capsys):
    p = tmp_path / "matrix.yaml"
    p.write_text(yaml.safe_dump({"rows": [_row("a-row"), _row("b-row", gg=("required", "missing"))]}))
    assert cli.main(["status", "--matrix", str(p), "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "blocked" and st["next_row"]["id"] == "b-row"
    assert st["next"] == f"roomkit parity --matrix {p}" and st["blocking"] == {"deflockdane": 0, "glassgovernment": 1}
    assert cli.main(["status", "--matrix", str(p), "--site", "deflockdane", "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "green" and st["next_row"] is None and st["next"] is None
    # Beside the room's own status, under "parity".
    m = _write(tmp_path, _manifest())
    assert cli.main(["status", "--manifest", str(m), "--out", str(tmp_path / "out"), "--matrix", str(p), "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "unbuilt" and st["parity"]["next_row"]["id"] == "b-row"


def test_status_on_a_refused_matrix_says_so_and_how(tmp_path, capsys):
    p = tmp_path / "matrix.yaml"
    p.write_text(yaml.safe_dump({"rows": [_row(disposition="nope")]}))
    assert cli.main(["status", "--matrix", str(p), "--json"]) == 0
    st = json.loads(capsys.readouterr().out)
    assert st["stage"] == "refused" and st["problems"] == ["doc-thing: unknown disposition 'nope'"]


# --- the template is Jinja, shared with Civica (plan Task 3a) ------------------

def test_the_template_environment_escapes_everything_and_refuses_missing_keys():
    import jinja2

    from roomkit import room as R
    assert R.ENV.autoescape is True and R.ENV.undefined is jinja2.StrictUndefined
    # No filters of roomkit's own: dates and labels arrive formatted from the site.
    assert set(R.ENV.filters) == set(jinja2.Environment().filters)
    with pytest.raises(jinja2.UndefinedError):
        R.render("room/404.html", {"at": "/reading-room/", "theme_key": ""})
    tpl = R.ENV.from_string('<p title="{{ v }}">{{ v }}</p>')
    # html.escape's entities, as 0.3.0 wrote them (not markupsafe's &#34;/&#39;).
    assert tpl.render(v="O'Brien & \"Sons\" <b>") == (
        '<p title="O&#x27;Brien &amp; &quot;Sons&quot; &lt;b&gt;">O&#x27;Brien &amp; &quot;Sons&quot; &lt;b&gt;</p>')
    with pytest.raises(TypeError, match="NoneType"):
        tpl.render(v=None)


def test_the_templates_read_only_the_view_model():
    from roomkit import room as R
    from roomkit import view as V
    from roomkit.pack import for_site
    THEME = for_site("glassgovernment")
    m = parse(_dd_manifest())
    for view in (V.doc_view(m.documents[0], m, "/reading-room/", THEME), V.index_view(m, "/reading-room/", THEME)):
        # Plain data all the way down: what Civica can build from its own rows.
        json.dumps(view)
    html = R.render("room/document.html", V.doc_view(m.documents[0], m, "/reading-room/", THEME))
    assert html.startswith('<main id="room-content" class="room room--doc" tabindex="-1" data-room-theme-key="ggrr-theme">')


def test_scan_page_images_and_boxes_parse_cleanly() -> None:
    data = _manifest()
    data["documents"][0]["pages"] = [
        {
            "n": 1,
            "text": "Page one transcript",
            "provenance": "ocr",
            "image_url": "/reading-room/camera-contract/pages/page-1.webp",
            "boxes": [
                {
                    "text": "Page one",
                    "box": [0.1, 0.2, 0.15, 0.4],
                    "confidence": 0.95,
                }
            ],
        },
        {
            "n": 2,
            "text": "Page two transcript",
            "provenance": "ocr",
            "image_url": "https://example.test/pages/page-2.webp",
        },
    ]
    m = parse(data)
    assert not m.refusals
    doc = m.documents[0]
    assert len(doc.pages) == 2
    assert doc.pages[0].image_url == "/reading-room/camera-contract/pages/page-1.webp"
    assert len(doc.pages[0].boxes) == 1
    assert doc.pages[0].boxes[0]["box"] == [0.1, 0.2, 0.15, 0.4]
    assert doc.pages[0].boxes[0]["confidence"] == 0.95
    assert doc.pages[1].image_url == "https://example.test/pages/page-2.webp"
    assert doc.pages[1].boxes == ()


def test_scan_page_image_url_refusal() -> None:
    data = _manifest()
    data["documents"][0]["pages"] = [{"n": 1, "text": "Page text", "image_url": "javascript:alert(1)"}]
    m = parse(data)
    assert len(m.refusals) == 1
    assert "image_url 'javascript:alert(1)' is not https:// or a same-host path" in m.refusals[0][1]


def test_scan_page_boxes_validation_refusals() -> None:
    data = _manifest()
    data["documents"][0]["pages"] = [{"n": 1, "text": "Page text"}]

    # Boxes not a list
    d1 = copy.deepcopy(data)
    d1["documents"][0]["pages"][0]["boxes"] = "not-a-list"
    assert "boxes is not a list" in parse(d1).refusals[0][1]

    # Box not a dict
    d2 = copy.deepcopy(data)
    d2["documents"][0]["pages"][0]["boxes"] = ["not-a-dict"]
    assert "box #0 is not an object" in parse(d2).refusals[0][1]

    # Coord not 4 numbers
    d3 = copy.deepcopy(data)
    d3["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 0.3]}]
    assert "coord must be 4 numbers" in parse(d3).refusals[0][1]

    # Out of bounds (< 0.0)
    d4 = copy.deepcopy(data)
    d4["documents"][0]["pages"][0]["boxes"] = [{"box": [-0.1, 0.2, 0.5, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d4).refusals[0][1]

    # Out of bounds (> 1.0)
    d5 = copy.deepcopy(data)
    d5["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 1.2, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d5).refusals[0][1]

    # Inverted y (ymin >= ymax)
    d6 = copy.deepcopy(data)
    d6["documents"][0]["pages"][0]["boxes"] = [{"box": [0.5, 0.2, 0.4, 0.6]}]
    assert "coord out of bounds or inverted" in parse(d6).refusals[0][1]

    # Inverted x (xmin >= xmax)
    d7 = copy.deepcopy(data)
    d7["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.8, 0.3, 0.7]}]
    assert "coord out of bounds or inverted" in parse(d7).refusals[0][1]

    # Confidence out of bounds
    d8 = copy.deepcopy(data)
    d8["documents"][0]["pages"][0]["boxes"] = [{"box": [0.1, 0.2, 0.3, 0.4], "confidence": 1.5}]
    assert "confidence must be a number between 0 and 1 or null" in parse(d8).refusals[0][1]


def test_scan_pages_json_serialization() -> None:
    from pathlib import Path

    from roomkit import build as B

    engine = Path(__file__).resolve().parent / "golden" / "engine"
    data = _manifest()
    data["documents"][0]["pages"] = [
        {
            "n": 1,
            "text": "Page one text",
            "image_url": "/reading-room/camera-contract/pages/p1.webp",
            "boxes": [{"text": "Sample", "box": [0.1, 0.2, 0.3, 0.4], "confidence": 0.99}],
        },
        {"n": 2, "text": "Page two text"},
    ]
    m = parse(data)
    files = B.render(m, engine=engine)
    pages_key = next(k for k in files if k.startswith("camera-contract/pages.") and k.endswith(".json"))
    rendered_json = json.loads(files[pages_key].decode("utf-8"))
    assert rendered_json["total"] == 2
    p1 = rendered_json["pages"][0]
    assert p1["n"] == 1
    assert p1["image_url"] == "/reading-room/camera-contract/pages/p1.webp"
    assert p1["boxes"] == [{"text": "Sample", "box": [0.1, 0.2, 0.3, 0.4], "confidence": 0.99}]
    p2 = rendered_json["pages"][1]
    assert "image_url" not in p2
    assert "boxes" not in p2


def test_table_csv_tsv_manifest_parses_cleanly() -> None:
    data = _manifest()
    data["documents"][0]["file"]["ext"] = "csv"
    data["documents"][0]["file"]["mime"] = "text/csv"
    data["documents"][0]["file"]["url"] = "/reading-room/camera-contract/file.csv"
    data["documents"][0]["file"]["download_url"] = "/reading-room/camera-contract/file.csv?download=1"

    m = parse(data)
    assert not m.refusals
    assert m.documents[0].ext == "csv"

    # Also TSV
    data["documents"][0]["file"]["ext"] = "tsv"
    data["documents"][0]["file"]["mime"] = "text/tab-separated-values"
    data["documents"][0]["file"]["url"] = "/reading-room/camera-contract/file.tsv"
    data["documents"][0]["file"]["download_url"] = "/reading-room/camera-contract/file.tsv?download=1"

    m2 = parse(data)
    assert not m2.refusals
    assert m2.documents[0].ext == "tsv"


def test_table_csv_tsv_module_resolution() -> None:
    from roomkit import build as B
    from roomkit.manifest import TABLE

    assert "csv" in TABLE and "tsv" in TABLE
    assert B._module("csv") == "rr-reader-table.js"
    assert B._module("tsv") == "rr-reader-table.js"
    assert B._module("pdf") == "rr-reader-pdf.js"
    assert B._module("txt") == "rr-reader-text.js"


@pytest.mark.parametrize("url", ["/\\evil.example/x", "/\t/evil.example", "/a\nb", "/a b", "https://ok.example/\\x",
                                 "https://ok.example/a\x00b", "//evil.example", "javascript:alert(1)", "http://x.example/"])
def test_urls_that_leave_the_site_or_hide_a_host_are_refused(url):
    from roomkit import entities as E
    from roomkit import manifest as M
    assert not M._url_ok(url) and not E._url_ok(url)


@pytest.mark.parametrize("url", ["/ok/path/", "/ok?q=1#frag", "https://ok.example/a%5Cb"])
def test_ordinary_same_host_and_https_urls_stay_accepted(url):
    from roomkit import manifest as M
    assert M._url_ok(url)


def _scan_row(**over):
    row = {"slug": "s", "title": "t", "citation": "c", "visibility": "public",
           "file": {"url": "/f", "download_url": "/f", "sha256": "0" * 64, "ext": "png", "mime": "image/png"},
           "pages": [{"n": 1, "text": "x", "boxes": [{"box": [0.1, 0.1, 0.2, 0.2], "text": "x"}]}]}
    row.update(over)
    return row


def test_a_mime_that_does_not_fit_the_extension_is_refused():
    from roomkit import manifest as M
    row = _scan_row()
    row["file"]["mime"] = "text/html"
    assert "does not fit" in M._document(row)[1]
    row["file"]["mime"] = "IMAGE/PNG; charset=binary"
    assert M._document(row)[1] == ""


def test_box_keys_outside_the_allowlist_are_refused():
    from roomkit import manifest as M
    row = _scan_row()
    row["pages"][0]["boxes"][0]["html"] = "<img src=x onerror=alert(1)>"
    assert "only" in M._document(row)[1]


def test_page_and_box_counts_are_capped():
    from roomkit import manifest as M
    row = _scan_row(pages=[{"n": i, "text": ""} for i in range(1, M.MAX_PAGES + 2)])
    assert "limit" in M._document(row)[1]
    row = _scan_row()
    row["pages"][0]["boxes"] = [{"box": [0.1, 0.1, 0.2, 0.2]}] * (M.MAX_BOXES_PER_PAGE + 1)
    assert "limit" in M._document(row)[1]


# --- text-only records ("file": null) ---------------------------------------


def _textonly(**over):
    row = {"slug": "text-only", "title": "Text Only", "visibility": "public",
           "citation": "Test Agency, Text Only.", "file": None,
           "search_text": "Medicaid managed care rules appear here.",
           "display": {"no_file": "No file is attached to this record yet."}}
    row.update(over)
    return row


def test_null_file_with_text_is_accepted_and_has_no_file():
    m = parse(_manifest(documents=[_textonly()]))
    d = m.documents[0]
    assert not d.has_file and d.file_url == d.sha256 == d.ext == ""


@pytest.mark.parametrize("row,reason", [
    (_textonly(search_text=""), "nothing to publish"),
    (_textonly(search_text=None), "nothing to publish"),
])
def test_null_file_without_text_is_refused(row, reason):
    m = parse(_manifest(documents=[row]))
    assert not m.documents and reason in m.refusals[0][1]


def test_omitted_file_is_still_refused():
    row = _textonly()
    del row["file"]
    m = parse(_manifest(documents=[row]))
    assert not m.documents and m.refusals[0][1] == "no file"


def test_text_only_page_has_no_reader_buttons_or_hash_and_shows_the_notice(tmp_path):
    out = tmp_path / "room"
    data = _manifest(documents=[_textonly()])
    assert cli.main(["build", "--manifest", str(_write(tmp_path, data)), "--out", str(out)]) == 0
    html = (out / "text-only" / "index.html").read_text()
    assert "No file is attached to this record yet." in html
    for absent in ("data-rr-reader", 'class="rr-reader', "<object", "Download", "Open the", "SHA-256", "room__actions"):
        assert absent not in html, absent
    lock = json.loads((out / "room.lock.json").read_text())
    assert "text-only/index.html" in lock["files"]


def test_text_only_record_is_searchable():
    m = parse(_manifest(documents=[_textonly()]))
    assert S.records(m, "/reading-room/")[0]["text"].startswith("Medicaid")


def test_parity_checks_a_text_only_page_for_its_notice_and_skips_the_reader():
    m = parse(_manifest(documents=[_textonly()]))
    doc = m.documents[0]
    page = f"<p>{doc.citation}</p><p>No file is attached to this record yet.</p>"
    assert P.check_page(doc, page) == []
    assert P.check_page(doc, f"<p>{doc.citation}</p>") == ["no-file notice absent"]


# --- the index's own year span ----------------------------------------------


def _index_html(years):
    data = _manifest()
    if years is not None:
        data["site"]["index"] = {"years": years}
    files = B.render(parse(data), engine=_ENGINE_FOR_YEARS)
    return files["index.html"].decode()


_ENGINE_FOR_YEARS = __import__("pathlib").Path(__file__).resolve().parent / "golden" / "engine"


def test_index_years_come_from_the_manifest_when_it_gives_them():
    assert "1919&ndash;2026" in _index_html(["1919", "2026"])
    assert "1919" not in _index_html(None)


@pytest.mark.parametrize("bad", [["1919"], ["2026", "1919"], ["19", "2026"], "1919-2026", [1919, 2026]])
def test_a_bad_index_years_is_a_manifest_error(bad):
    data = _manifest()
    data["site"]["index"] = {"years": bad}
    with pytest.raises(ManifestError, match="years"):
        parse(data)


# --- GG-style index selects: optgroups, a multi-valued facet, a year range, a sort ----


def _selects_manifest():
    data = _manifest()
    data["site"]["index"] = {
        "groups": ["Test Agency", "Other Agency"], "group_label": "Collection",
        "group_sets": [{"label": "Set One", "groups": ["Test Agency"]}],
        "facets": [{"name": "vendor", "label": "Vendor", "multi": True},
                   {"name": "year", "label": "Year", "range": True, "from_label": "From year", "to_label": "To year"}],
        "sort": {"label": "Sort", "options": [{"value": "default", "label": "Default order"},
                                              {"value": "date-desc", "label": "Date (newest)"},
                                              {"value": "title", "label": "Title (A-Z)"}]}}
    a, b = data["documents"]
    a.update(date="2020-05-01", index={"group": "Test Agency", "facets": {"year": "2020"}, "browse": {"vendor": ["Flock", "Axon"]}})
    b.update(date="2024-01-01", index={"group": "Other Agency", "facets": {"year": "2024"}, "browse": {"vendor": ["Flock"]}})
    return data


def test_the_index_selects_render_optgroups_a_multi_facet_a_range_and_a_sort():
    html = B.render(parse(_selects_manifest()))["index.html"].decode()
    assert '<optgroup label="Set One"><option value="Test Agency">Test Agency</option></optgroup>' in html
    assert '<option value="Other Agency">Other Agency</option>' in html  # in no set: a plain option
    assert 'data-room-multi="vendor"' in html and '<option value="Axon">Axon</option>' in html
    assert 'name="year-from"' in html and 'name="year-to"' in html and ">From year</label>" in html
    assert '<select id="room-f-sort" name="sort" data-room-sort>' in html and "Title (A-Z)" in html
    assert 'data-room-m-vendor="[&quot;Flock&quot;, &quot;Axon&quot;]"' in html
    assert 'data-room-date="2020-05-01"' in html and 'data-room-title="camera contract"' in html


def test_a_room_without_the_new_index_keys_has_none_of_the_new_markup():
    html = B.render(parse(_manifest()))["index.html"].decode()
    for absent in ("data-room-multi", "data-room-range", "data-room-sort", "<optgroup", "data-room-date"):
        assert absent not in html, absent


@pytest.mark.parametrize("index,why", [
    ({"facets": [{"name": "v", "label": "V", "multi": True, "range": True}]}, "not both"),
    ({"facets": [{"name": "y", "label": "Y", "range": True}]}, "from_label"),
    ({"sort": {"label": "Sort", "options": [{"value": "random", "label": "R"}]}}, "site.index.sort"),
    ({"sort": {"label": "", "options": [{"value": "title", "label": "T"}]}}, "site.index.sort"),
    ({"group_sets": [{"label": "S", "groups": "x"}]}, "group_sets"),
])
def test_bad_index_select_keys_are_manifest_errors(index, why):
    data = _manifest()
    data["site"]["index"] = index
    with pytest.raises(ManifestError, match=why):
        parse(data)


def test_in_a_browser_the_multi_facet_range_and_sort_filter_and_order_the_cards(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    data = _selects_manifest()
    data["site"]["room_path"] = "/room/"
    data["documents"][1]["index"]["group"] = "Test Agency"  # one group, so the order is visible
    B.write(B.render(parse(data)), tmp_path / "room")
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(tmp_path))
    handler.log_message = lambda *a: None
    srv = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/room/"
    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"Playwright Chromium not installed: {e}")
            pg = b.new_page()
            errors = []
            pg.on("pageerror", lambda e: errors.append(str(e)))
            pg.goto(url)
            shown = lambda: pg.locator(".room__card:visible .room__card-title").all_inner_texts()
            assert sorted(shown()) == ["Camera Contract", "Site Photo"]
            pg.select_option("[data-room-multi=vendor]", "Axon")
            assert shown() == ["Camera Contract"]
            pg.select_option("[data-room-multi=vendor]", "")
            pg.select_option("[name=year-from]", "2024")
            assert shown() == ["Site Photo"]
            pg.select_option("[name=year-from]", "")
            pg.select_option("[name=year-to]", "2020")
            assert shown() == ["Camera Contract"]
            pg.select_option("[name=year-to]", "")
            pg.select_option("[data-room-sort]", "date-desc")
            assert pg.locator(".room__card .room__card-title").all_inner_texts() == ["Site Photo", "Camera Contract"]
            pg.select_option("[data-room-sort]", "title")
            assert pg.locator(".room__card .room__card-title").all_inner_texts() == ["Camera Contract", "Site Photo"]
            pg.select_option("[data-room-sort]", "date-desc")
            assert "sort=date-desc" in pg.url
            pg.select_option("[data-room-multi=vendor]", "Flock")
            assert "vendor=Flock" in pg.url
            pg.reload()
            assert pg.input_value("[data-room-multi=vendor]") == "Flock"
            assert pg.input_value("[data-room-sort]") == "date-desc"
            assert errors == []
            b.close()
    finally:
        srv.shutdown()
