#!/usr/bin/env bash
# Fetch a site's live entity pages, for `roomkit parity --entities-from` (parity.entities),
# its collection pages, for `roomkit parity --collections-from` (parity.collections),
# or its topic pages, for `roomkit parity --topics-from` (parity.topics).
#
# READ-ONLY GETs, one a second, normal browser UA, writes nothing on the host.
#
#   fetch-entity-pages.sh [--origin|--origin-http] HOST PATH...
#
# PATH is relative to https://HOST/ (library/entities/, reading-room/entity/vendor/axon/,
# deflock_rr_entity-sitemap.xml). --origin is for running ON the site's host: --resolve
# pins HOST to the host's own public address, so each request skips Cloudflare and
# reaches WordPress uncached, as exporters/deflockdane-fetch-pages.sh does (dd's edge
# answers 429 after a few dozen paced requests). --origin-http does the same over
# plain HTTP on :80, for glassgovernment.org: Cloudflare reaches the GG host's apex on
# :80 only, and a --resolve to :443 lands on a different server. Through the edge,
# Cloudflare's email obfuscation rewrites every address in the HTML to
# "[email protected]", so parity against an edge fetch reports differences the
# room does not have (2026-10-21: 1 collection page, 6 topic pages).
#
# glassgovernment.org, from the Mac (public pages, no login):
#   jq -r '.entities.index.url, .entities.pages[].url' gg-manifest.json \
#     | sed 's#^https://glassgovernment.org/##' > gg-entity-paths.txt
#   bash roomkit/exporters/fetch-entity-pages.sh glassgovernment.org $(cat gg-entity-paths.txt) > gg-entity-pages.tsv
#
# glassgovernment.org collections (the index for its table, the collections page, each collection):
#   jq -r '"https://glassgovernment.org/library/", .collections.index.url, .collections.pages[].url' gg-manifest.json \
#     | sed 's#^https://glassgovernment.org/##' > gg-collection-paths.txt
#   bash roomkit/exporters/fetch-entity-pages.sh glassgovernment.org $(cat gg-collection-paths.txt) > gg-collection-pages.tsv
#
# glassgovernment.org topics (the topics page and every page of every topic):
#   jq -r '.topics.index.url, .topics.pages[].url' gg-manifest.json \
#     | sed 's#^https://glassgovernment.org/##' > gg-topic-paths.txt
#   ssh $GG_HOST bash -s -- --origin-http glassgovernment.org $(cat gg-topic-paths.txt) \
#     < roomkit/exporters/fetch-entity-pages.sh > gg-topic-pages.tsv
#
# deflockdane.org, through the origin (the same ssh route as the dd export):
#   ssh $DD_HOST bash -s -- --origin deflockdane.org deflock_rr_entity-sitemap.xml \
#     $(jq -r '.entities.pages[].url | sub("^https://deflockdane.org/"; "")' dd-manifest.json) \
#     < roomkit/exporters/fetch-entity-pages.sh > dd-entity-pages.tsv
#
# Output: "# fetched <UTC time> <how>", then one "<path>\t<http code>\t<base64 html>" per path.
# Runs under the Mac's bash 3.2 and BSD base64 as well as on Linux.
set -euo pipefail
ORIGIN=0 SCHEME=https PORT=443
if [[ ${1:-} == --origin ]]; then ORIGIN=1; shift
elif [[ ${1:-} == --origin-http ]]; then ORIGIN=1 SCHEME=http PORT=80; shift; fi
HOST=${1:?usage: fetch-entity-pages.sh [--origin|--origin-http] HOST PATH...}; shift
[[ $HOST =~ ^[a-z0-9.-]+$ ]] || { echo "bad host: $HOST" >&2; exit 1; }
RESOLVE=()
HOW="GET $SCHEME://$HOST/<path>"
if (( ORIGIN )); then
  IP=$(curl -s -m 10 https://api.ipify.org)
  [[ $IP =~ ^[0-9.]+$ ]] || { echo "cannot find this host's public address" >&2; exit 1; }
  RESOLVE=(--resolve "$HOST:$PORT:$IP")
  HOW="$HOW via the origin (--resolve to the host's own address)"
fi
UA='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36'
printf '# fetched %s %s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$HOW"
for path in "$@"; do
  [[ $path =~ ^[a-z0-9_][a-z0-9_./-]*$ && $path != *..* ]] || { echo "bad path: $path" >&2; exit 1; }
  html=$(curl -s -m 60 ${RESOLVE[@]+"${RESOLVE[@]}"} -A "$UA" -w '\n%{http_code}' "$SCHEME://$HOST/$path" || true)
  code=${html##*$'\n'}
  printf '%s\t%s\t%s\n' "$path" "$code" "$(printf '%s' "${html%$'\n'*}" | base64 | tr -d '\n')"
  sleep 1
done
