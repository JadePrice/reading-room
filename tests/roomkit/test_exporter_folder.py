"""exporters/folder.py: a folder of PDFs and its documents.json in, a manifest roomkit builds out.

The PDFs are written here, a few hundred bytes each, with real text on each page, so the
export runs the real pdftotext and pdfinfo (skipped where poppler is not installed).
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from roomkit import manifest as M
from roomkit.exporters import folder as F

REPO = Path(__file__).resolve().parents[2]
PACKS = REPO / "roomkit" / "packs"
POPPLER = shutil.which("pdftotext") and shutil.which("pdfinfo")
needs_poppler = pytest.mark.skipif(not POPPLER, reason="no pdftotext/pdfinfo (poppler) here")


def pdf(*pages: str) -> bytes:
    """A minimal PDF with one line of Helvetica text per page."""
    n = len(pages)
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(n))
    objs = ["<< /Type /Catalog /Pages 2 0 R >>",
            f"<< /Type /Pages /Kids [{kids}] /Count {n} >>"]
    font = 3 + 2 * n
    for i, text in enumerate(pages):
        stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode()
        objs.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
                    f"/Resources << /Font << /F1 {font} 0 R >> >> /Contents {4 + 2 * i} 0 R >>")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode()}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def folder(tmp_path: Path, **row_changes) -> Path:
    root = tmp_path / "records"
    (root / "council").mkdir(parents=True)
    a, b = pdf("Minutes page one", "Minutes page two"), pdf("Budget summary")
    (root / "council" / "Minutes 2024-03.pdf").write_bytes(a)
    (root / "budget.pdf").write_bytes(b)
    rows = [
        {"file": "council/Minutes 2024-03.pdf", "title": "Council minutes, March 2024",
         "sha256": hashlib.sha256(a).hexdigest(), "date": "2024-03-12", "group": "Council",
         "source_url": "https://records.example.org/originals/minutes-2024-03.pdf"},
        {"file": "budget.pdf", "title": "Budget summary", "sha256": hashlib.sha256(b).hexdigest(),
         "summary": "The adopted budget, in brief."},
    ]
    rows[0].update(row_changes)
    (root / "documents.json").write_text(json.dumps({
        "site": {"name": "records.example.org", "title": "Reading Room",
                 "base_url": "https://records.example.org", "lede": "Every record we hold."},
        "documents": rows}), encoding="utf-8")
    return root


@needs_poppler
def test_the_export_is_a_manifest_roomkit_accepts(tmp_path):
    out = F.export(str(folder(tmp_path)))
    m = M.parse(out)
    assert not m.refusals, m.refusals
    first, second = out["documents"]
    assert first["slug"] == "council-minutes-2024-03"
    assert first["file"]["url"] == "/files/council/Minutes%202024-03.pdf"
    assert [p["text"].strip() for p in first["pages"]] == ["Minutes page one", "Minutes page two"]
    assert first["index"]["facets"] == {"year": "2024"} and second["index"]["facets"] == {}
    assert first["citation"].endswith("Source: https://records.example.org/originals/minutes-2024-03.pdf.")
    assert out["site"]["room_path"] == "/documents/" and out["site"]["index"]["groups"] == ["Council"]
    assert second["summary"] == "The adopted budget, in brief."


@needs_poppler
@pytest.mark.parametrize("change, why", [
    ({"sha256": "0" * 64}, "do not hash"),
    ({"title": ""}, "needs file, title and sha256"),
    ({"file": "../outside.pdf"}, "not a file under the folder"),
    ({"source_url": "ftp://x"}, "source_url"),
])
def test_a_bad_row_is_refused(tmp_path, change, why):
    root = folder(tmp_path, **change)
    (tmp_path / "outside.pdf").write_bytes(pdf("outside"))
    with pytest.raises(F.ExportError, match=why):
        F.export(str(root))


def test_a_page_count_mismatch_is_refused(tmp_path, monkeypatch):
    calls = iter(["Pages: 3\n", "one\ftwo\f"])
    monkeypatch.setattr(F.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout=next(calls)))
    with pytest.raises(F.ExportError, match="pdftotext gave 2 pages, pdfinfo says 3"):
        F.pdf_pages("x.pdf")


def test_two_files_making_one_slug_are_refused(tmp_path):
    root = folder(tmp_path)
    data = json.loads((root / "documents.json").read_text())
    (root / "Budget.PDF").write_bytes((root / "budget.pdf").read_bytes())
    data["documents"].append(dict(data["documents"][1], file="Budget.PDF"))
    (root / "documents.json").write_text(json.dumps(data))
    with pytest.raises(F.ExportError, match="same slug: budget"):
        F.export(str(root), extract=lambda p: ["text"])


@needs_poppler
@pytest.mark.parametrize("pack", ["default", "example"])
def test_the_cli_exports_and_roomkit_builds_it_with_each_shipped_pack(tmp_path, pack):
    root = folder(tmp_path)
    r = subprocess.run([sys.executable, "-m", "roomkit.exporters.folder", str(root)], cwd=REPO,
                       capture_output=True, text=True, check=False, timeout=120)
    assert r.returncode == 0, r.stderr
    manifest = tmp_path / "manifest.json"
    manifest.write_text(r.stdout, encoding="utf-8")
    room = tmp_path / "room"
    b = subprocess.run([sys.executable, "-m", "roomkit.cli", "build", "--manifest", str(manifest),
                        "--out", str(room), "--site-pack", str(PACKS / pack), "--json"], cwd=REPO,
                       capture_output=True, text=True, check=False, timeout=300)
    assert b.returncode == 0, b.stderr
    assert json.loads(b.stdout)["built"] is True
    assert (room / "council-minutes-2024-03" / "index.html").is_file()
    assert "Council minutes, March 2024" in (room / "index.html").read_text(encoding="utf-8")


def test_a_refused_export_prints_nothing_and_exits_1(tmp_path, capsys):
    root = folder(tmp_path, sha256="1" * 64)
    assert F.main([str(root)]) == 1
    out = capsys.readouterr()
    assert out.out == "" and "folder export refused" in out.err
