#!/usr/bin/env bash
# Fetch dd's live reading-room pages from the ORIGIN, for `roomkit parity --pages`.
#
# READ-ONLY, writes nothing on the host. Run from the Mac, slugs as arguments:
#
#   ssh $DD_HOST bash -s -- $(jq -r '.documents[].slug' M.json) \
#     < roomkit/exporters/deflockdane-fetch-pages.sh > pages.tsv
#   python -m roomkit.cli parity --manifest M.json --pages pages.tsv
#
# Why the origin: Cloudflare rate-limits deflockdane.org (a 429 from the edge
# after a few dozen paced requests, 2026-10-08). On the host, --resolve pins the
# site name to the host's own public address, so the request skips Cloudflare
# and hits WordPress directly, uncached: the page as the site renders it now.
#
# Output: one line per slug, "<slug>\t<http code>\t<base64 html>".
set -euo pipefail
IP=$(curl -s -m 10 https://api.ipify.org)
[[ $IP =~ ^[0-9.]+$ ]] || { echo "cannot find this host's public address" >&2; exit 1; }
for slug in "$@"; do
  [[ $slug =~ ^[a-z0-9-]+$ ]] || { echo "bad slug: $slug" >&2; exit 1; }
  html=$(curl -s -m 60 --resolve "deflockdane.org:443:$IP" -A "roomkit-parity/0.1 (origin)" \
           -w '\n%{http_code}' "https://deflockdane.org/reading-room/$slug/" || true)
  code=${html##*$'\n'}
  printf '%s\t%s\t%s\n' "$slug" "$code" "$(printf '%s' "${html%$'\n'*}" | base64 -w0)"
  sleep 0.5
done
