# Reading Room

An independent, local-first digital reading room engine for public records, transparency archives, and document libraries.

Reading Room provides:
- **Standards-Compliant Document Reader**: Built-in zero-dependency reader engine (`reading-room-reader`) supporting PDF, multi-page image sets, OCR sidecar text, deep passage citations, and client-side in-document search.
- **Static & Dynamic Generation (`roomkit`)**: Generates fully self-contained, cacheable HTML rooms from JSON manifests, with strict HTML escaping and byte-for-byte reproducibility.
- **Search & Ingestion**: Pluggable full-text search (Pagefind client-side search or Postgres / Meilisearch server-side search) and PDF/A OCR ingestion with Tesseract.
- **Zero Cloud Tracking & Data Privacy**: 100% local processing; document text is never sent to third-party language models or external telemetry.

---

## Architecture

```
reading-room/
├── roomkit/              # Python static generator, manifest parser, and parity verifier
│   ├── build.py          # Builds static room files with content-addressed fingerprints
│   ├── manifest.py       # Validates document metadata, citation models, and file hashes
│   ├── ocr.py            # ocrmypdf + tesseract PDF/A viewing copy and sidecar pipeline
│   ├── pack.py           # Site pack token and layout validator
│   ├── router.py         # Local deterministic decision and query intent routing
│   ├── view.py           # Strict view models
│   └── templates/        # Jinja templates (shared across static and live engines)
├── reading-room-reader/  # Vanilla JS in-browser reader
│   ├── src/              # Core reader controller and rendering modules
│   └── vendor/pdfjs/     # Bundled PDF.js rendering worker
├── tests/                # Hermetic test suite (golden, packs, manifest, router, ocr)
├── tools/                # Release gates, sanitization, and verification scripts
└── pyproject.toml        # Standard Python package configuration
```

---

## Quickstart

### 1. Installation

```bash
# Clone the repository
git clone https://github.com/JadePrice/reading-room.git
cd reading-room

# Install with pip or uv
pip install -e ".[dev]"
```

### 2. Validating a Manifest

Validate your archive manifest against the formal JSON schema:

```bash
roomkit manifest path/to/manifest.json
```

### 3. Building a Static Reading Room

Build the entire reading room into static, immutable HTML and assets:

```bash
roomkit build path/to/manifest.json --out ./dist/room/
```

### 4. Running Tests

```bash
pytest tests/
```

---

## Documentation

- [Expanded Document-Type Architecture & Scope](docs/EXPANDED_FORMATS.md): Comprehensive roadmap and specification for multi-page scans, OCR-to-image verification, tabular data (CSV/TSV), audio/video evidence, and web captures.

---

## License

This project is licensed under the [GNU Affero General Public License v3.0 or later](LICENSE).
