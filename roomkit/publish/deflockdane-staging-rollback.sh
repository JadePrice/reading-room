#!/usr/bin/env bash
# Put https://deflockdane.org/rr-staging/ back to what it served before the last
# publish (roadmap P3). Run on the Mac AS YOURSELF:
#   bash roomkit/publish/deflockdane-staging-rollback.sh
# The publish keeps the served room at ~/roomkit-prev/deflockdane/rr-staging on
# $DD_HOST (outside the web root) before it uploads; this restores it in publish
# order and checks every served file against the restored lock. One generation
# only: rolling back twice restores the same room.
set -euo pipefail
DD_HOST="${DD_HOST:?set DD_HOST to the ssh host that serves deflockdane.org}"
cd "$(dirname "$0")/../.."
PY="${PYTHON:-python3}"
DOCROOT='domains/deflockdane.org/public_html'
MOUNT=/rr-staging/
PREV='roomkit-prev/deflockdane/rr-staging'
W=$(mktemp -d)

echo "== 1/2 restore the previous room"
ssh $DD_HOST bash -s -- restore "$DOCROOT$MOUNT" "$PREV" < roomkit/publish/room-snapshot.sh
ssh $DD_HOST "cat $PREV/room.lock.json" > "$W/prev-lock.json"

echo "== 2/2 verify: every served file hashes to the restored lock (via the origin)"
source roomkit/publish/upload.sh
verify_served "$W/prev-lock.json" $DD_HOST deflockdane.org "$MOUNT" "$PY"
echo "Rolled back: https://deflockdane.org$MOUNT now serves the room locked in $PREV/room.lock.json"
echo "HTML may sit at the edge for up to an hour; purge if it is cached there."
