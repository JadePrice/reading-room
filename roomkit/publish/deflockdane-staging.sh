#!/usr/bin/env bash
# Publish the static dd reading room to https://deflockdane.org/rr-staging/ (noindex).
#
# Run on the Mac AS YOURSELF, from anywhere:  bash ~/LLM_WIKI/scripts/roomkit/publish/deflockdane-staging.sh
# A human decision every time (roomkit has no publish verb on purpose).
#
# Plain static files in the dd docroot: same origin as the PDFs (no CORS), no
# PHP. Touches only public_html/rr-staging/. Everything it reads from the site
# goes through the origin, because Cloudflare rate-limits deflockdane.org.
# Remove staging with:  ssh gg-shared 'rm -r ~/domains/deflockdane.org/public_html/rr-staging'
#
# The room draws its own header, navigation and footer from the dd site pack
# (scripts/roomkit/packs/deflockdane/). Nothing is captured from WordPress any
# more: plan D7 (the captured shell) was superseded on 2026-10-14, because a
# standalone room cannot depend on WordPress output.
#
# Caching (scripts/roomkit/build.py docstring): assets carry a content hash and
# are cached for a year, HTML revalidates. So the upload never deletes blindly:
#   - pages and page text of records that left the room go at once (a retraction);
#   - old assets stay one more generation, for HTML an edge may still hold;
#   - the URLs to purge are printed at the end. Staging HTML is not edge-cached
#     today, so nothing needs purging yet; at cutover the purge is a step, not advice.
set -euo pipefail
REPO_DIR="${REPO_DIR:-$HOME/LLM_WIKI}"
cd "$REPO_DIR"
PY="${PYTHON:-python3}"
RK="${ROOMKIT_CMD:-$PY -m roomkit.cli}"
W=$(mktemp -d)
DOCROOT='domains/deflockdane.org/public_html'
MOUNT=/rr-staging/
PACK=roomkit/packs/deflockdane/
[ -d "$PACK" ] || PACK=scripts/roomkit/packs/deflockdane/

echo "== 1/6 export the manifest (read-only)"
ssh gg-shared "ROOMKIT_ALLOW_EXCLUDED=1 ~/bin/wp --path=\$HOME/$DOCROOT eval-file -" \
  < $([ -f roomkit/exporters/deflockdane.php ] && echo roomkit/exporters/deflockdane.php || echo scripts/roomkit/exporters/deflockdane.php) > "$W/manifest.json"

echo "== 2/6 build + check, in the dd site pack"
ROOM=(--manifest "$W/manifest.json" --out "$W/room" --mount "$MOUNT" --noindex --site-pack "$PACK")
$RK build "${ROOM[@]}"
$RK check "${ROOM[@]}" >/dev/null

echo "== 3/6 parity: every citation, file URL and card thumbnail against the live WordPress pages (via the origin)"
FETCH_SCRIPT=$([ -f roomkit/exporters/deflockdane-fetch-pages.sh ] && echo roomkit/exporters/deflockdane-fetch-pages.sh || echo scripts/roomkit/exporters/deflockdane-fetch-pages.sh)
ssh gg-shared bash -s -- $($PY -c "import json,sys;print(' '.join(d['slug'] for d in json.load(open(sys.argv[1]))['documents']))" "$W/manifest.json") \
  < "$FETCH_SCRIPT" > "$W/live-pages.tsv"
$RK parity --manifest "$W/manifest.json" --pages "$W/live-pages.tsv"
# Card thumbnails: the room's own copies against the bytes each live card shows.
THUMBS_SCRIPT=$([ -f roomkit/exporters/deflockdane-fetch-thumbs.sh ] && echo roomkit/exporters/deflockdane-fetch-thumbs.sh || echo scripts/roomkit/exporters/deflockdane-fetch-thumbs.sh)
ssh gg-shared bash -s < "$THUMBS_SCRIPT" > "$W/live-thumbs.tsv"
$RK parity --thumbs "$W/live-thumbs.tsv" --out "$W/room"

echo "== 4/6 what changes: the served lock against this build"
ssh gg-shared "cat $DOCROOT${MOUNT}room.lock.json 2>/dev/null || echo '{}'" > "$W/served-lock.json"
$RK diff --old "$W/served-lock.json" --new "$W/room/room.lock.json" --json > "$W/diff.json"
$PY -c "import json,sys;d=json.load(open(sys.argv[1]));print('   ' + ', '.join(f'{k} {len(v)}' for k,v in d.items()))" "$W/diff.json"

echo "== 5/6 upload, then remove what left the room"
rsync -rlt --chmod=D755,F644 "$W/room/" "gg-shared:$DOCROOT$MOUNT"
# Delete: records that left the room (now), and assets two generations old
# (in neither the served lock nor this one). Paths come from roomkit's own
# locks; each is checked to stay inside the mount before rm sees it.
$PY - "$W/diff.json" "$W/served-lock.json" "$W/room/room.lock.json" <<'PY' > "$W/remove.txt"
import json, re, sys
diff, old, new = (json.load(open(p)) for p in sys.argv[1:4])
for p in diff["remove_now"]:
    print(p)
print("#ASSETS-KEEP " + " ".join(sorted(set(old.get("files", {})) | set(new["files"]))))
PY
ssh gg-shared "cd $DOCROOT$MOUNT && $(cat <<'SH'
keep=""; while IFS= read -r line; do
  case "$line" in
    "#ASSETS-KEEP "*) keep=" ${line#\#ASSETS-KEEP } " ;;
    *) [[ ! "$line" =~ \.\. ]] && [[ $line =~ ^([a-zA-Z0-9._-]+/)*[a-zA-Z0-9._-]+$ ]] && rm -f -- "$line" && echo "   removed $line" ;;
  esac
done
find assets -type f | while IFS= read -r f; do
  case "$keep" in *" $f "*) ;; *) rm -f -- "$f" && echo "   removed old asset $f" ;; esac
done
find . -mindepth 1 -type d -empty -delete
SH
)" < "$W/remove.txt"

echo "== 6/6 verify: every served file hashes to the build's lock (via the origin)"
$PY - "$W/room/room.lock.json" "$MOUNT" <<'PY' | ssh gg-shared bash -s > "$W/served.txt"
import json, sys
mount = sys.argv[2]
print('IP=$(curl -s -m 10 https://api.ipify.org)')
for p in json.load(open(sys.argv[1]))["files"]:
    print(f'printf "%s " "{p}"; curl -s -m 60 --resolve deflockdane.org:443:$IP "https://deflockdane.org{mount}{p}" | sha256sum | cut -c1-64')
PY
$PY - "$W/room/room.lock.json" "$W/served.txt" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))["files"]
served = dict(l.split() for l in open(sys.argv[2]) if l.strip())
bad = [p for p, h in lock.items() if served.get(p) != h]
print(f"   {len(lock) - len(bad)}/{len(lock)} served files match the lock")
for p in bad[:10]: print("   DIFFERS:", p)
sys.exit(1 if bad else 0)
PY
echo
$PY -c "
import json,sys
d=json.load(open(sys.argv[1])); urls=['https://deflockdane.org'+sys.argv[2]+p.replace('index.html','') for p in d['purge']]
print(f'URLs whose content changed ({len(urls)}); purge these at the edge if HTML is cached there:')
print('\n'.join('   '+u for u in urls[:20]) + ('\n   ...' if len(urls)>20 else ''))" "$W/diff.json" "$MOUNT"
echo "Staging is up: https://deflockdane.org$MOUNT   (manifest and room kept in $W)"
