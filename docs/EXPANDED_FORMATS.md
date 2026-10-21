# Expanded Document-Type Architecture & Scope Specification

## 1. Executive Summary

Reading Room provides a local-first, zero-telemetry reading room engine designed for transparency archives, public records repositories, and civic document collections. While the initial release focused on PDF reading and in-browser search, investigative and civic archives routinely encounter evidence formats beyond single or multi-page PDFs, including:
- High-resolution document scans and photographic evidence (JPEG, PNG, WebP; TIFF is download-only, see 2.1).
- Structured tabular data (CSV, TSV) from open-data disclosures and FOIA releases.
- Timestamped audio/video records (body cameras, depositions, city council hearings).
- Historical web captures (WARC/WACZ files).

This document establishes the architecture, representation model, and phased roadmap for expanding Reading Room into a multi-format evidence platform.

### Core Architectural Invariants
All format extensions must strictly satisfy these foundational principles:
1. **Authentic Source Preservation:** The original evidence file (`file.url` and `file.download_url`) must remain verbatim and untouched. Derivatives generated for fast web viewing never replace or alter original evidence.
2. **Deterministic & Static Publication:** Generation pipelines must remain reproducible. The published output is 100% static, cacheable, and hostable on any static web server or CDN without runtime application servers.
3. **No-JS Progressive Enhancement:** When client JavaScript is disabled or fails to execute, standard semantic HTML (`<noscript>`, `<object>`, direct download links) must provide full access to original files and metadata.
4. **Zero-Dependency Vanilla Client:** The front-end reader engine (`reading-room-reader`) remains pure vanilla JavaScript and CSS, adhering to standard DOM and web APIs without heavy front-end frameworks (React, Vue) or bundler bloat.
5. **Fail-Closed Privacy & Safety:** PII masking (e.g. SSNs), manifest schema validation, and coordinate bounds checking fail closed. Verification copies and search indexes must never leak unredacted sensitive values.

### Status (engine 0.8.0, 2026-10-21)

What this specification describes against what the code does today. LLM_WIKI is
canonical; this repo is its mirror.

| Item | Status | Where |
| :--- | :--- | :--- |
| Box validation: `[ymin, xmin, ymax, xmax]` in 0..1, inversions refused | Done | `roomkit/manifest.py`; `reading-room-reader/contract/pages.schema.json` |
| `image_url` and `boxes` in `pages.json` | Done | `roomkit/build.py` |
| Multi-page scans: prev/next, page jump, zoom, 90° rotation, fullscreen | Done | `rr-reader-image.js` |
| Transcript pane, box overlays, `#page=N&box=…` deep links, in-document search | Done | `rr-reader-image.js` |
| Thumbnail ribbon | Not built | |
| CSV/TSV grid: sort, filter, pagination, `#row=N&col=M` links, citation copy, 5 MB cap | Done | `rr-reader-table.js` |
| Virtualized scrolling for large tables | Not built (pagination instead; over 5 MB falls back to download) | |
| TIFF | Download only: browsers other than Safari cannot draw it, so `manifest.py` lists it in `DOWNLOAD_ONLY` and no reader mounts | |
| Audio/video, WARC/WACZ | Not scheduled | see the conditions under section 3 |

---

## 2. Inventory of Format Families & Scope Audit

### 2.1 Multi-Page Scans & High-Resolution Image Sets
* **Use Case:** Historical public records, hand-signed resolutions, deeds, and unsearchable document image sets.
* **Format Scope:** JPEG, PNG, WebP, GIF, SVG. TIFF stays download-only: most browsers cannot render it, so a scan set ships WebP page images (`pages[].image_url`) beside the original TIFF.
* **Existing Foundation:** `rr-reader-image.js` provides single images and multi-page scan sets with page controls, zoom, 90° rotation and fullscreen.
* **Gaps:** Thumbnail ribbon; deep zoom tiles for very large scans.

### 2.2 OCR-to-Image Verification
* **Use Case:** Archival accountability and transcript auditing. Enables researchers to cross-verify OCR transcription against original scans.
* **Existing Foundation:** `roomkit/ocr.py` runs Tesseract OCR and PDF/A compilation. `manifest.py` validates normalized boxes; `rr-reader-image.js` draws the transcript pane, box overlays and `#page=N&box=ymin,xmin,ymax,xmax` deep links. The data contract is `reading-room-reader/contract/pages.schema.json`.
* **Gaps:** None in this phase.

### 2.3 Tabular Data (CSV/TSV)
* **Use Case:** Campaign finance ledgers, vendor payment registries, municipal salary lists, and police incident data.
* **Format Scope:** CSV, TSV.
* **Existing Foundation:** `rr-reader-table.js` renders an accessible grid with RFC 4180 parsing, sortable columns, filtering, pagination, `#row=42&col=3` anchors and citation copy. Cells are text nodes, never HTML. Files over 5 MB fall back to the download link.
* **Gaps:** Virtualized scrolling, if pagination proves too slow on real datasets.

### 2.4 Audio & Video Evidence
* **Use Case:** Police body-worn cameras, public hearings, depositions, and 911 calls.
* **Format Scope:** MP4 (H.264), WebM (VP9/AV1), MP3, AAC, WAV, paired with WebVTT transcripts.
* **Existing Foundation:** None (categorized as download-only).
* **Gaps:** Needs an accessible HTML5 media player module (`rr-reader-media.js`), synchronized transcript scrolling, and timestamp-based citations (`#t=01:23`).

### 2.5 Archived Web Captures (WARC / WACZ)
* **Use Case:** Preserved government agency websites, official statements, and deleted online postings.
* **Format Scope:** WARC, WACZ.
* **Evaluation:** Full replay requires heavy WASM service workers (e.g., ReplayWeb.page). Archived pages are hostile content, so replay must run on a separate origin: `sandbox="allow-scripts allow-same-origin"` on a same-origin iframe is no sandbox at all, because the framed script can reach its parent and remove the attribute. Use `allow-scripts` without `allow-same-origin`, or a dedicated replay domain. Not scheduled.

---

## 3. Comparison & Prioritization Matrix

| Format Family | Research Value | Implementation Effort | Maintenance Burden | Technical & Privacy Risks | Recommended Phase |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Multi-Page Image Sets** | High | Low | Low | Low (standard browser image rendering) | **Phase 1** |
| **OCR-to-Image Verification** | Very High | Low-Medium | Low | Low (static coordinate overlays) | **Phase 1** |
| **Tabular Data (CSV/TSV)** | High | Medium | Low | Low (sanitize cell HTML injection) | **Phase 2** |
| **Audio / Video Records** | High | Medium | Medium | Medium (large file streaming, codecs) | **Phase 3** |
| **Web Archives (WARC/WACZ)** | Medium-High | High | High | High (WASM footprint, XSS attack surface) | **Phase 4** |

Phases 1 and 2 are built. Phases 3 and 4 are not scheduled; each new reader needs, before it is proposed: a written data contract, an adversarial test fixture and an accessibility test, all before any code.

---

## 4. Evidence Record Representation Model

To support multi-format evidence without schema fragmentation, documents utilize a unified data model decoupling authentic files, viewing derivatives, and page-level coordinate maps:

```json
{
  "slug": "police-commission-scan-1994",
  "title": "Police Commission Resolution 94-01",
  "visibility": "public",
  "citation": "City Police Commission, Resolution 94-01 (Jan. 12, 1994).",
  "file": {
    "url": "/reading-room/police-commission-scan-1994/file/?v=hash",
    "download_url": "/reading-room/police-commission-scan-1994/file/?download=1",
    "sha256": "4a1b2c...",
    "bytes": 5242880,
    "ext": "tiff",
    "mime": "image/tiff"
  },
  "pages": [
    {
      "n": 1,
      "provenance": "ocr",
      "text": "RESOLVED by the Board of Police Commissioners...",
      "image_url": "/reading-room/police-commission-scan-1994/pages/page-1.webp",
      "boxes": [
        {
          "text": "RESOLVED",
          "box": [0.125, 0.082, 0.145, 0.220],
          "confidence": 0.98
        }
      ]
    }
  ]
}
```

### Coordinate Normalization Rules
1. Coordinates are represented as 4-element arrays: `[ymin, xmin, ymax, xmax]`.
2. All values are normalized floats between `0.0` and `1.0` relative to the page dimensions.
3. Coordinates must satisfy `0.0 <= ymin < ymax <= 1.0` and `0.0 <= xmin < xmax <= 1.0`. Any inversion or out-of-bounds value fails closed in `manifest.py`.

---

## 5. Phase 1 Technical Specification: Scan Viewer & OCR Verification (built; kept as the record of intent)

### 5.1 Python Generator (`roomkit`)
- **`manifest.py`**:
  - Extend `Page` dataclass with `image_url: str = ""` and `boxes: tuple[dict, ...] = ()`.
  - Validate image URLs against safe URI policies (`_url_ok`).
  - Validate box coordinates against normalized bounding box constraints.
- **`build.py`**:
  - Serialize `image_url` and `boxes` into `pages.json` when present.
  - Maintain byte-for-byte reproducibility for existing single-image and PDF manifests.

### 5.2 Browser Reader Module (`rr-reader-image.js`)
- **Multi-Page Navigation:**
  - `Prev` / `Next` paging controls.
  - Numeric page jump input (`<input class="rr-reader__page-input">`).
  - Total page indicator (`/ N`).
- **Scan Manipulation:**
  - Zoom controls: In (`+`), Out (`−`), and Reset to fit.
  - Rotate control: 90° clockwise rotation (`0°`, `90°`, `180°`, `270°`) via CSS transform.
  - Fullscreen toggle.
- **OCR Verification & Side-by-Side Mode:**
  - Toggle between Image-only, Side-by-Side (Scan + Transcript), and Transcript-only.
  - SVG/DOM bounding box overlays rendered over the scan image.
  - Bidirectional focus: clicking a transcript passage highlights the box on the scan; clicking a box jumps to and highlights the text in the transcript.
  - Deep linking via URL hash: `#page=N` and `#page=N&box=ymin,xmin,ymax,xmax`.
- **In-Document Search:**
  - Integrates with `RRReader.searchPages(pages, query)` to offer instantaneous client-side search across scan transcripts.
