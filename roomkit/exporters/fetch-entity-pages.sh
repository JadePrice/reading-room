#!/usr/bin/env bash
# Fetch a site's live entity pages, for `roomkit parity --entities-from` (parity.entities).
#
# READ-ONLY GETs, one a second, normal browser UA, writes nothing on the host.
#
#   fetch-entity-pages.sh [--origin] HOST PATH...
#
# PATH is relative to https://HOST/ (library/entities/, reading-room/entity/vendor/axon/,
# deflock_rr_entity-sitemap.xml). --origin is for running ON the site's host: --resolve
# pins HOST to the host's own public address, so each request skips Cloudflare and
# reaches WordPress uncached, as exporters/deflockdane-fetch-pages.sh does (dd's edge
# answers 429 after a few dozen paced requests).
#
# glassgovernment.org, from the Mac (public pages, no login):
#   jq -r '.entities.index.url, .entities.pages[].url' gg-manifest.json \
#     | sed 's#^https://glassgovernment.org/##' > gg-entity-paths.txt
#   bash roomkit/exporters/fetch-entity-pages.sh glassgovernment.org $(cat gg-entity-paths.txt) > gg-entity-pages.tsv
#
# deflockdane.org, through the origin (the same ssh route as the dd export):
#   ssh gg-shared bash -s -- --origin deflockdane.org deflock_rr_entity-sitemap.xml \
#     $(jq -r '.entities.pages[].url | sub("^https://deflockdane.org/"; "")' dd-manifest.json) \
#     < roomkit/exporters/fetch-entity-pages.sh > dd-entity-pages.tsv
#
# Output: "# fetched <UTC time> <how>", then one "<path>\t<http code>\t<base64 html>" per path.
# Runs under the Mac's bash 3.2 and BSD base64 as well as on Linux.
set -euo pipefail
ORIGIN=0
if [[ ${1:-} == --origin ]]; then ORIGIN=1; shift; fi
HOST=${1:?usage: fetch-entity-pages.sh [--origin] HOST PATH...}; shift
[[ $HOST =~ ^[a-z0-9.-]+$ ]] || { echo "bad host: $HOST" >&2; exit 1; }
RESOLVE=()
HOW="GET https://$HOST/<path>"
if (( ORIGIN )); then
  IP=$(curl -s -m 10 https://api.ipify.org)
  [[ $IP =~ ^[0-9.]+$ ]] || { echo "cannot find this host's public address" >&2; exit 1; }
  RESOLVE=(--resolve "$HOST:443:$IP")
  HOW="$HOW via the origin (--resolve to the host's own address)"
fi
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'
printf '# fetched %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HOW"
for path in "$@"; do
  [[ $path =~ ^[a-z0-9_][a-z0-9_./-]*$ && $path != *..* ]] || { echo "bad path: $path" >&2; exit 1; }
  html=$(curl -s -m 60 ${RESOLVE[@]+"${RESOLVE[@]}"} -A "$UA" -w '\n%{http_code}' "https://$HOST/$path" || true)
  code=${html##*$'\n'}
  printf '%s\t%s\t%s\n' "$path" "$code" "$(printf '%s' "${html%$'\n'*}" | base64 | tr -d '\n')"
  sleep 1
done
