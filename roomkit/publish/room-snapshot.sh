# Runs ON THE HOST (ssh HOST bash -s -- CMD LIVE PREV < room-snapshot.sh), or locally in tests.
# Roadmap P3: keep the served room one generation back, and put it back in one command.
#
#   snapshot LIVE PREV   hard-link copy of LIVE at PREV (instant, no extra space). The
#                        upload writes new files by rename and removal unlinks, so the
#                        copy keeps the old bytes. No LIVE yet: nothing to keep.
#   restore  LIVE PREV   PREV back into LIVE in publish order (assets and data, HTML,
#                        then the lock), then remove what PREV does not have. By
#                        checksum: a page rebuilt within the same second at the same
#                        size would pass rsync's size-and-time check unrestored.
# PREV must sit outside the web root, so the old room is never served from it.
set -euo pipefail
cmd=$1 live=${2%/} prev=${3%/}
case "$cmd" in
  snapshot)
    [ -d "$live" ] || { echo "   no served room at $live: nothing to snapshot"; exit 0; }
    mkdir -p "$(dirname "$prev")"
    rm -rf "$prev.new"
    cp -al "$live" "$prev.new"
    rm -rf "$prev"
    mv "$prev.new" "$prev"
    echo "   snapshot of $live at $prev ($(find "$prev" -type f | wc -l | tr -d ' ') files)"
    ;;
  restore)
    [ -f "$prev/room.lock.json" ] || { echo "no snapshot with a lock at $prev" >&2; exit 1; }
    mkdir -p "$live"
    rsync -rltc --exclude='*.html' --exclude='/.htaccess' --exclude='/sitemap.xml' --exclude='/room.lock.json' "$prev/" "$live/"
    rsync -rltc --exclude='/room.lock.json' "$prev/" "$live/"
    rsync -rltc --delete "$prev/" "$live/"
    echo "   restored $live from $prev"
    ;;
  *) echo "usage: snapshot|restore LIVE PREV" >&2; exit 2 ;;
esac
