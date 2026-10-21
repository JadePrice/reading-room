"""Structural promises of the shared reader engine. No browser needed.

These are the things that drifted silently before: a version stamped in one
place and not another, a module shipped but never documented, markup built
from strings, and vendored copies nobody could compare to the source.
"""

from __future__ import annotations

import hashlib
import re
import subprocess

from tests.reading_room_reader.conftest import ENGINE

SRC = ENGINE / "src"
MODULES = sorted(p.name for p in (SRC / "modules").glob("*.js"))


def test_version_file_matches_the_loader():
    version = (ENGINE / "VERSION").read_text().strip()
    m = re.search(r"var VERSION = '([^']+)'", (SRC / "rr-reader.js").read_text())
    assert m and m.group(1) == version


def test_every_module_is_documented():
    readme = (ENGINE / "README.md").read_text()
    missing = [name for name in MODULES if name not in readme]
    assert missing == []


def test_no_markup_is_built_from_strings():
    # Server strings (snippets, citations, OCR text) reach the reader; they go
    # in as text nodes only. The 0.3.0 snippet highlighter used innerHTML.
    # The read-aloud prototype is site code beside the engine; it is scanned
    # here too so there is one markup check, not one per file.
    offenders = [
        f"{p.name}:{i}"
        for p in [SRC / "rr-reader.js", *(SRC / "modules").glob("*.js"),
                  ENGINE / "read-aloud" / "rr-read-aloud.js"]
        for i, line in enumerate(p.read_text().splitlines(), 1)
        if re.search(r"\.(innerHTML|outerHTML)\s*=|insertAdjacentHTML", line)
    ]
    assert offenders == []


def test_every_module_that_moves_stops_for_reduced_motion():
    # Roadmap T6: a transition or a smooth scroll ships with its
    # prefers-reduced-motion opt-out in the same file.
    moving = [p for p in [SRC / "rr-reader.js", *(SRC / "modules").glob("*.js")]
              if re.search(r"transition:(?!none)|animation:|behavior: *'smooth'", p.read_text())]
    assert moving, "the scan found nothing; the pattern is stale"
    assert [p.name for p in moving if "prefers-reduced-motion" not in p.read_text()] == []


def test_the_reader_promises_a_fallback_contract():
    readme = (ENGINE / "README.md").read_text()
    assert "data-reader-fallback" in readme


def test_vendored_pdfjs_is_the_pinned_upstream_build():
    # Roadmap P4: the hashes the README records, which are upstream's
    # (pdfjs-dist 3.11.174). A re-vendor changes the README table and this
    # together, or fails here.
    readme = (ENGINE / "README.md").read_text()
    recorded = dict(re.findall(r"^\| `(pdf[\w.]+\.js)` \| `([0-9a-f]{64})` \|$", readme, re.MULTILINE))
    vendored = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                for p in (ENGINE / "vendor" / "pdfjs").glob("*.js")}
    assert recorded and recorded == vendored


def test_sync_writes_a_manifest_that_verifies(tmp_path):
    assets = tmp_path / "assets"
    assets.mkdir()
    subprocess.run(["bash", str(ENGINE / "sync.sh"), str(assets)], check=True, capture_output=True)
    out = assets / "vendor" / "rr-reader"
    manifest = (out / "MANIFEST.sha256").read_text()
    for name in ["rr-reader.js", "VERSION", *(f"modules/{m}" for m in MODULES)]:
        assert f"  {name}\n" in manifest
    assert (assets / "vendor" / "pdfjs" / "pdf.min.js").is_file()
    check = subprocess.run(
        "sha256sum -c MANIFEST.sha256 2>/dev/null || shasum -a 256 -c MANIFEST.sha256",
        shell=True, cwd=out, capture_output=True, text=True, check=False,
    )
    assert check.returncode == 0, check.stdout + check.stderr
