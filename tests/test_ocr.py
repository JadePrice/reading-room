"""Unit and integration tests for ocrmypdf pipeline."""

from __future__ import annotations

from pathlib import Path

import pytest

from roomkit.ocr import is_ocrmypdf_available, process_pdf_bytes, run_ocrmypdf

FIXTURE_PDF = Path(__file__).resolve().parent / "fixtures" / "sample_scan.pdf"


def test_ocrmypdf_is_available() -> None:
    assert is_ocrmypdf_available() is True


@pytest.mark.skipif(not is_ocrmypdf_available(), reason="ocrmypdf binary not installed")
def test_run_ocrmypdf_on_sample_scan(tmp_path: Path) -> None:
    if not FIXTURE_PDF.is_file():
        pytest.skip("sample scan fixture not found")

    out_pdf = tmp_path / "searchable.pdf"
    sidecar = tmp_path / "sidecar.txt"

    stats = run_ocrmypdf(
        FIXTURE_PDF,
        out_pdf,
        sidecar,
        skip_text=True,
        clean=True,
        deskew=True,
        timeout=60.0,
    )

    assert out_pdf.is_file()
    assert out_pdf.stat().st_size > 0
    assert sidecar.is_file()
    text = sidecar.read_text(encoding="utf-8")
    assert len(text) > 50
    assert stats["returncode"] == 0
    assert stats["output_bytes"] > 0


@pytest.mark.skipif(not is_ocrmypdf_available(), reason="ocrmypdf binary not installed")
def test_process_pdf_bytes(tmp_path: Path) -> None:
    if not FIXTURE_PDF.is_file():
        pytest.skip("sample scan fixture not found")

    pdf_bytes = FIXTURE_PDF.read_bytes()
    out_bytes, sidecar_text, stats = process_pdf_bytes(
        pdf_bytes,
        skip_text=True,
        clean=True,
        deskew=True,
        timeout=60.0,
    )

    assert len(out_bytes) > 0
    assert len(sidecar_text) > 50
    assert stats["output_bytes"] == len(out_bytes)


def test_run_ocrmypdf_fails_when_output_missing(tmp_path: Path, monkeypatch) -> None:
    import subprocess
    from roomkit.ocr import OcrError

    dummy_in = tmp_path / "in.pdf"
    dummy_in.write_bytes(b"%PDF-1.4 dummy")
    dummy_out = tmp_path / "out.pdf"

    class DummyProc:
        returncode = 0
        stderr = ""

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: DummyProc())

    with pytest.raises(OcrError, match="output PDF is missing or empty"):
        run_ocrmypdf(dummy_in, dummy_out)

