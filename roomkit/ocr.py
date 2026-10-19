"""OCR and PDF/A viewing copy pipeline using ocrmypdf and tesseract.

Transforms raw or scanned PDFs into compliant, searchable PDF/A viewing copies
with embedded text layers and sidecar text.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

OCRMYPDF_BIN = shutil.which("ocrmypdf") or "/usr/bin/ocrmypdf"


class OcrError(RuntimeError):
    """Raised when ocrmypdf fails to process the input PDF."""


def is_ocrmypdf_available() -> bool:
    """Return True if ocrmypdf binary is present and executable."""
    return bool(shutil.which("ocrmypdf")) or os.path.exists("/usr/bin/ocrmypdf")


def run_ocrmypdf(
    input_pdf: Path,
    output_pdf: Path,
    sidecar_txt: Path | None = None,
    *,
    skip_text: bool = True,
    clean: bool = True,
    deskew: bool = True,
    output_type: str = "pdfa",
    timeout: float = 300.0,
) -> dict[str, Any]:
    """Execute ocrmypdf on input_pdf generating output_pdf and optional sidecar.

    Parameters:
      input_pdf: Source PDF file.
      output_pdf: Destination for searchable PDF/A.
      sidecar_txt: Optional path for sidecar extracted text.
      skip_text: If True, skips pages that already have text (--skip-text).
      clean: If True, cleans unpaper artifacts (--clean).
      deskew: If True, straightens rotated scans (--deskew).
      output_type: PDF format ('pdfa', 'pdf', 'pdfa-2').
      timeout: Wall-clock execution timeout in seconds.

    Returns dict with file metrics: input_bytes, output_bytes, compression_ratio, pages.
    """
    if not input_pdf.is_file():
        raise FileNotFoundError(f"Input PDF not found: {input_pdf}")

    cmd = [
        OCRMYPDF_BIN,
        f"--output-type={output_type}",
    ]
    if skip_text:
        cmd.append("--skip-text")
    if clean:
        cmd.append("--clean")
    if deskew:
        cmd.append("--deskew")
    if sidecar_txt is not None:
        cmd.append(f"--sidecar={sidecar_txt}")

    cmd.extend([str(input_pdf), str(output_pdf)])

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise OcrError(f"ocrmypdf timed out after {timeout}s on {input_pdf}") from exc

    if proc.returncode != 0:
        raise OcrError(f"ocrmypdf failed with exit {proc.returncode}: {proc.stderr.strip()}")

    in_size = input_pdf.stat().st_size
    out_size = output_pdf.stat().st_size if output_pdf.exists() else 0
    ratio = (out_size / in_size) if in_size > 0 else 1.0

    return {
        "input_path": str(input_pdf),
        "output_path": str(output_pdf),
        "sidecar_path": str(sidecar_txt) if sidecar_txt else None,
        "input_bytes": in_size,
        "output_bytes": out_size,
        "ratio": round(ratio, 4),
        "returncode": proc.returncode,
    }


def process_pdf_bytes(
    pdf_bytes: bytes,
    *,
    skip_text: bool = True,
    clean: bool = True,
    deskew: bool = True,
    timeout: float = 300.0,
) -> tuple[bytes, str, dict[str, Any]]:
    """Process in-memory PDF bytes with ocrmypdf, returning (searchable_pdf_bytes, sidecar_text, stats)."""
    with tempfile.TemporaryDirectory(prefix="room_ocr_") as tmpdir:
        tmp_in = Path(tmpdir) / "input.pdf"
        tmp_out = Path(tmpdir) / "output.pdf"
        tmp_sidecar = Path(tmpdir) / "sidecar.txt"
        tmp_in.write_bytes(pdf_bytes)

        stats = run_ocrmypdf(
            tmp_in,
            tmp_out,
            tmp_sidecar,
            skip_text=skip_text,
            clean=clean,
            deskew=deskew,
            timeout=timeout,
        )

        out_bytes = tmp_out.read_bytes() if tmp_out.exists() else b""
        sidecar_text = (
            tmp_sidecar.read_text(encoding="utf-8", errors="replace")
            if tmp_sidecar.exists()
            else ""
        )
        return out_bytes, sidecar_text, stats
