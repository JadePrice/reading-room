#!/usr/bin/env bash
# sync.sh — vendor the common reading-room reader engine into a plugin.
#
# Usage: ./sync.sh /path/to/plugin/assets
#   Copies src/ verbatim into <assets>/vendor/rr-reader/, stamps VERSION, and
#   writes MANIFEST.sha256 so drift between a site's copy and this engine is
#   checkable (driftkit, or `sha256sum -c MANIFEST.sha256` in the vendor dir).
#   No build/minify — both consuming sites serve raw ES5 (js_min off).
#
# After syncing, the plugin must enqueue:
#   <assets>/vendor/rr-reader/rr-reader.js               (loader; localize window.rrReaderConfig onto it)
#   <assets>/vendor/rr-reader/modules/rr-reader-pdf.js   (pdf; depends on the loader + pdf.js 3.x)
#   <assets>/vendor/rr-reader/modules/rr-reader-image.js (optional; images)
#   <assets>/vendor/rr-reader/modules/rr-reader-text.js  (optional; txt/md/csv/json/xml/html)
#   <assets>/vendor/rr-reader/modules/rr-reader-table.js (optional; csv/tsv as a grid; loaded before text wins csv)
#   <assets>/vendor/rr-reader/modules/rr-cite.js         (optional; self-wires [data-rr-cite-copy] buttons)
# and emit a .rr-reader[data-file-url] mount container per document.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
DEST="${1:?usage: sync.sh <plugin-assets-dir>}"

[ -d "$DEST" ] || { echo "sync.sh: target assets dir not found: $DEST" >&2; exit 1; }

OUT="$DEST/vendor/rr-reader"
mkdir -p "$OUT/modules"
cp "$HERE/src/rr-reader.js" "$OUT/rr-reader.js"
for m in "$HERE"/src/modules/*.js; do
    cp "$m" "$OUT/modules/$(basename "$m")"
done
cp "$HERE/VERSION" "$OUT/VERSION"

# pdf.js is pinned here (3.11.174; the text layer needs the 3.x renderTextLayer
# API) and lands at the path both plugins already enqueue: <assets>/vendor/pdfjs/.
mkdir -p "$DEST/vendor/pdfjs"
cp "$HERE/vendor/pdfjs/pdf.min.js" "$HERE/vendor/pdfjs/pdf.worker.min.js" "$DEST/vendor/pdfjs/"

# Manifest of what was vendored, relative to the vendor dir. shasum ships on
# macOS, sha256sum on Linux; both emit the same "<hash>  <path>" format.
if command -v sha256sum >/dev/null 2>&1; then SHA="sha256sum"; else SHA="shasum -a 256"; fi
( cd "$OUT" && $SHA rr-reader.js modules/*.js VERSION ../pdfjs/pdf.min.js ../pdfjs/pdf.worker.min.js > MANIFEST.sha256 )

echo "rr-reader synced -> $OUT (version $(cat "$HERE/VERSION"))"
