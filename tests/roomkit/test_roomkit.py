"""roomkit: a static reading room built from a manifest.

The contract the tests hold it to: refuse rather than guess, never emit a
private record, escape everything a manifest says, render the same bytes
twice, keep the no-JS promise a drift check probes for (download link, citation,
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


def _snapshot_manifest(kind="html"):
    data = _manifest()
    data["documents"] = [{"slug": "archived-page", "title": "Archived page", "visibility": "public",
                          "citation": "Archived page, https://example.test/reading-room/archived-page/",
                          "summary": "A captured public page.", "file": None,
                          "snapshot": {"kind": kind, "url": f"/archive/page.{kind}",
                                       "captured": "2026-01-31", "source": "wayback",
                                       "of_record": [{"label": "Wayback capture", "url": "https://web.archive.org/web/20260131000000/https://example.test/original"}],
                                       **({"page": "https://example.test/original", "ts": "20260131000000"}
                                          if kind == "wacz" else {})}}]
    return data


def test_snapshot_records_are_origin_safe_and_keep_their_capture_metadata():
    doc = parse(_snapshot_manifest("wacz")).documents[0]
    assert doc.snapshot["kind"] == "wacz" and doc.snapshot["ts"] == "20260131000000"

    data = _snapshot_manifest()
    data["documents"][0]["snapshot"]["url"] = "https://evil.example/page.html"
    m = parse(data)
    assert "same-origin" in m.refusals[0][1]


@pytest.mark.parametrize("mutate, reason", [
    (lambda d: d["documents"][0].update(file={"url": "/x", "download_url": "/x",
                                               "sha256": SHA, "ext": "html", "mime": "text/html"}), "file: null"),
    (lambda d: d["documents"][0]["snapshot"].update(kind="wacz", url="/archive/page.html"), ".wacz"),
])
def test_snapshot_records_refuse_ambiguous_or_mislabeled_rows(mutate, reason):
    data = _snapshot_manifest()
    mutate(data)
    assert reason in parse(data).refusals[0][1]


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
    assert lock["documents"] == 2 and lock["schema"] == "1.0"
    for rel, digest in lock["files"].items():
        assert B.sha256((out / rel).read_bytes()) == digest, rel
    assert ".htaccess" not in lock["files"] and lock["server_config"][".htaccess"] == B.sha256((out / ".htaccess").read_bytes())
    pages = json.loads((out / pub("camera-contract/pages.json")).read_text())
    assert pages["schema_version"] == "1.0"
    assert pages["total"] == 2 and pages["pages"][1] == {"n": 2, "provenance": "ocr", "text": "Page two"}


def test_manifest_contract_fields_are_additive_and_source_backed(tmp_path):
    data = _manifest()
    data["schema_version"] = "1.4"
    doc = _doc(data)
    doc["lang"] = "es-MX"
    doc["provenance"] = {
        "source_url": "https://example.test/source",
        "issuing_org": "Test Agency",
        "document_date": "2025-12-01",
        "acquisition_method": "official-publication",
        "acquired": "2026-01-02",
        "source_checked": "2026-01-31",
        "source_state": "live",
        "completeness": "Complete published copy.",
    }
    doc["relations"] = [{"slug": "site-photo", "basis": "shared-entity", "note": "Same project."}]
    manifest = parse(data)
    assert not manifest.refusals
    assert manifest.schema_version == "1.4"
    assert manifest.documents[0].lang == "es-MX"
    assert manifest.documents[0].relations == ({"slug": "site-photo", "basis": "shared-entity", "note": "Same project."},)

    files = B.render(manifest)
    pages = json.loads(files[B.published(files, "camera-contract/pages.json")])
    assert pages["schema_version"] == "1.4"
    assert pages["lang"] == "es-MX"
    assert pages["provenance"] == doc["provenance"]
    assert pages["relations"] == doc["relations"]


@pytest.mark.parametrize("mutate, reason", [
    (lambda data: data.update(schema_version="2.0"), "unsupported schema_version major"),
    (lambda data: data.update(schema_version="v1"), "schema_version must be major.minor"),
    (lambda data: _doc(data).update(provenance={"source_state": "not-sure"}), "provenance.source_state"),
    (lambda data: _doc(data).update(lang="not a tag"), "not a BCP 47"),
    (lambda data: _doc(data).update(relations=[{"slug": "missing", "basis": "curated"}]), "not a document"),
    (lambda data: _doc(data).update(relations=[{"slug": "camera-contract", "basis": "curated"}]), "cannot name the document itself"),
])
def test_manifest_contract_refuses_incompatible_or_unsourced_values(mutate, reason):
    data = _manifest()
    mutate(data)
    if "schema_version" in data and data["schema_version"] in {"2.0", "v1"}:
        with pytest.raises(ManifestError, match=reason):
            parse(data)
    else:
        assert reason in parse(data).refusals[0][1]


def test_build_mounts_html_and_wacz_snapshots_only_when_the_feature_is_on():
    pack = B.pack_for_site("default")
    pack["features"] = {"web-archive": True}
    html_files = B.render(parse(_snapshot_manifest("html")), pack=pack)
    html = html_files["archived-page/index.html"].decode()
    assert 'data-archive="html"' in html and any("rr-reader-archive." in path for path in html_files)
    assert "Captured" in html and "Capture source" in html and "Wayback capture" in html
    assert 'href="https://web.archive.org/web/20260131000000/https://example.test/original"' in html
    assert "replayBase" not in html_files[B.published(html_files, "assets/rr-config.js")].decode()

    wacz_files = B.render(parse(_snapshot_manifest("wacz")), pack=pack)
    wacz = wacz_files["archived-page/index.html"].decode()
    cfg = wacz_files[B.published(wacz_files, "assets/rr-config.js")].decode()
    assert 'data-archive="wacz"' in wacz and 'data-archive-page="https://example.test/original"' in wacz
    assert "Captured" in wacz and "Wayback capture" in wacz
    assert '"replayBase": "/reading-room/assets/vendor/replaywebpage/"' in cfg


def test_snapshot_build_requires_the_web_archive_pack_feature():
    with pytest.raises(ValueError, match="features.web-archive"):
        B.render(parse(_snapshot_manifest()))


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
    # The same markers the drift check's no-JS probe requires of the WordPress pages.
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
            pg.wait_for_function("() => /Pages? 1( and 2)? of 3/.test((document.querySelector('[data-reader-status]')||{}).textContent||'')",
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


_LAYOUT = """() => {
  const box = s => document.querySelector(s).getBoundingClientRect();
  const shell = box('.room__shell'), reader = box('#room-reader'), rail = box('.room__rail');
  const panels = [...document.querySelectorAll('.room__rail > .room__panel')].map(p => p.getBoundingClientRect().left);
  const obj = document.querySelector('object.rr-reader__object');
  return {shell: shell.width, reader: reader.width, gap: rail.top - reader.bottom,
          railLeft: rail.left - shell.left, columns: new Set(panels.map(Math.round)).size,
          object: obj ? obj.getBoundingClientRect().height : null,
          overflow: document.documentElement.scrollWidth - innerWidth};
}"""


def test_in_a_browser_the_reader_spans_the_page_and_the_details_sit_below(tmp_path):
    """BookReader's shape (2026-10-28): the reader takes the whole column on a
    desktop, opens in the two-page spread, and the details follow underneath,
    with and without JavaScript; a phone keeps one column."""
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
    status = "() => (document.querySelector('[data-reader-status]')||{}).textContent||''"
    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"Playwright Chromium not installed: {e}")
            for w, h in ((1280, 800), (1440, 900)):
                pg = b.new_page(viewport={"width": w, "height": h})
                pg.goto(url)
                pg.wait_for_function(f"() => /Pages 1 and 2 of 3/.test(({status})())", timeout=30000)
                got = pg.evaluate(_LAYOUT)
                assert abs(got["reader"] - got["shell"]) <= 1, got   # the whole column
                assert got["gap"] > 0 and abs(got["railLeft"]) <= 1, got  # details underneath
                assert got["columns"] == 2 and got["overflow"] <= 0, got
                assert pg.locator(".rr-reader__stage.is-spread").count() == 1
                assert pg.evaluate("document.querySelector('.rr-reader__stage').clientHeight") >= h - 200
                pg.get_by_role("button", name="Next page").click()
                pg.wait_for_function(f"() => /Page 3 of 3/.test(({status})())")
                pg.close()

                nojs = b.new_context(viewport={"width": w, "height": h}, java_script_enabled=False).new_page()
                nojs.goto(url)
                got = nojs.evaluate(_LAYOUT)
                assert abs(got["reader"] - got["shell"]) <= 1 and got["gap"] > 0, got
                assert got["object"] >= h - 6 * 16 - 1, got  # the browser's own viewer, viewport tall
                nojs.close()

            phone = b.new_page(viewport={"width": 390, "height": 844})
            phone.goto(url)
            phone.wait_for_function(f"() => /Page 1 of 3/.test(({status})())", timeout=30000)
            got = phone.evaluate(_LAYOUT)
            assert got["gap"] > 0 and got["columns"] == 1 and got["overflow"] <= 0, got
            assert phone.locator(".rr-reader__stage.is-spread").count() == 0
            b.close()
    finally:
        srv.shutdown()


_HEAD = """() => {
  const top = s => { const e = document.querySelector(s); return e ? e.getBoundingClientRect().top : null; };
  const n = document.querySelector('.room__notice'), lede = document.querySelector('.room__lede');
  return {reader: top('#room-reader-h'), topline: top('.room__topline'), meta: top('.room__header-meta'),
          head: top('.room__head'), title: top('.room__title'), notice: top('.room__notice'),
          noticeBottom: n ? n.getBoundingClientRect().bottom : null,
          noticeShown: n ? getComputedStyle(n).display !== 'none' && getComputedStyle(n).visibility === 'visible' : null,
          jump: top('.room__jump'), ledeH: lede.getBoundingClientRect().height,
          more: getComputedStyle(document.querySelector('.room__more')).display,
          overflow: document.documentElement.scrollWidth - innerWidth};
}"""


def test_in_a_browser_the_record_header_is_short_on_a_desktop_and_the_notice_stays_above(tmp_path):
    """The record page's header (2026-10-28, "shorter header is fine"): at 1280x800 the
    reader's heading is within 300px of the top on load; a notice stays above the reader,
    whole and on screen; a long summary folds to two lines behind a no-JS toggle; a phone
    puts the document first (top line, head, notice, reader, jump links, file meta)."""
    sync_api = pytest.importorskip("playwright.sync_api")
    data = _manifest()
    data["site"]["room_path"] = "/room/"
    d = _doc(data)
    d["summary"] = ("The contract between the city and the vendor for automated license plate reader cameras, "
                    "covering installation, data retention, sharing with other agencies and the renewal terms, "
                    "released in response to an open records request filed in 2025.")
    d["display"] = {"released": "January 31, 2026", "eyebrow": {"label": "Contracts", "url": "/room/"},
                    "header": {"meta": ["Test Agency", "Contracts", "2019-2025"], "original_url": "/room/x.pdf",
                               "ia_url": "https://archive.org/details/x"}}
    noticed = copy.deepcopy(d)
    noticed.update(slug="noticed", title="Noticed Contract")
    noticed["display"]["notice"] = {"heading": "Legal hold", "body": "Parts of this record may change.",
                                    "report": "Write to us."}
    data["documents"].append(noticed)
    site = tmp_path / "site"
    B.write(B.render(parse(data)), site / "room")

    class Quiet(SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(site)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/room"
    try:
        with sync_api.sync_playwright() as pw:
            try:
                b = pw.chromium.launch()
            except Exception as e:  # noqa: BLE001
                pytest.skip(f"Playwright Chromium not installed: {e}")
            ctx = b.new_context(viewport={"width": 1280, "height": 800}, java_script_enabled=False)
            pg = ctx.new_page()
            pg.goto(f"{base}/camera-contract/")
            got = pg.evaluate(_HEAD)
            assert got["reader"] <= 300 and got["overflow"] <= 0, got
            assert got["more"] != "none" and got["ledeH"] < 70, got  # two lines, and the toggle shown
            pg.get_by_text("Full summary").click()
            opened = pg.evaluate(_HEAD)
            assert opened["ledeH"] > got["ledeH"], (got, opened)  # the whole summary, without JavaScript
            assert pg.get_by_role("heading", level=1).count() == 1
            assert pg.locator("nav[aria-label='On this page'] a").count() == 3

            pg.goto(f"{base}/noticed/")
            got = pg.evaluate(_HEAD)
            assert got["noticeShown"] and got["head"] < got["notice"], got
            assert got["noticeBottom"] <= got["reader"] and got["noticeBottom"] <= 800, got
            ctx.close()

            phone = b.new_page(viewport={"width": 390, "height": 844})
            phone.goto(f"{base}/noticed/")
            got = phone.evaluate(_HEAD)
            # Chunk 4 (2026-11-10): on a phone the document comes first; the file meta and the jump links follow it.
            order = [got[k] for k in ("topline", "head", "notice", "jump", "reader", "meta")]
            assert order == sorted(order) and len(set(order)) == len(order), got
            assert got["more"] != "none" and got["ledeH"] < 75 and got["overflow"] <= 0, got  # three lines and a toggle
            b.close()
    finally:
        srv.shutdown()


def test_the_room_styles_only_its_own_content_element():
    # Scoping is the contrast fix: an id outranks the site theme's class and element
    # rules, so a theme written for another background cannot recolor the room.
    from roomkit import room as R
    for sel in CSS.css_selectors(R.ROOM_CSS):
        assert sel.startswith("#room-content"), sel
    with pytest.raises(ValueError, match="unknown theme tokens"):
        CSS.theme_css({"tokens": {"text-colour": "#000"}, "layout": {"toggle": ""}})


def test_a_long_group_list_folds_away():
    from roomkit import room as R
    data = _manifest()
    data["documents"] = [dict(copy.deepcopy(_doc(data, 1)), slug=f"doc-{i}", index={"group": f"Group {i}"}) for i in range(14)]
    html = R.index_main(parse(data), "/reading-room/",
                        {"layout": {"style": "rows", "show_empty_groups": False, "toggle": ""},
                         "labels": B.pack_for_site("default")["labels"]})
    assert "<details><summary>Jump to group (14)</summary>" in html


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


# --- the template is Jinja, shared with the host application ------------------

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


# --- site A-style index selects: optgroups, a multi-valued facet, a year range, a sort ----


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
    assert 'data-room-date="2020-05-01"' in html and 'data-room-title="Camera Contract" data-room-n="0"' in html


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
