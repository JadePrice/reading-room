#!/usr/bin/env bash
# Fetch dd's live index cards and their thumbnails from the ORIGIN, for
# `roomkit parity --thumbs`.
#
# READ-ONLY, writes nothing on the host but a temp file it removes. Run from the Mac:
#
#   ssh $DD_HOST bash -s < roomkit/exporters/deflockdane-fetch-thumbs.sh > thumbs.tsv
#   python -m roomkit.cli parity --thumbs thumbs.tsv --out ROOM
#
# Why the origin: deflockdane-fetch-pages.sh. The cards are read from the live
# index (/reading-room/) as the shortcode renders it, so a card counts as
# showing a thumbnail exactly when its markup has one; each <img> is then
# fetched and hashed as a browser would get it (the lazy-load plugin's data-src,
# which its script swaps in, when there is one).
#
# Output: a "#fetched\t<ISO time>" line, then one line per card,
# "<slug>\t<img src or ->\t<http code or ->\t<content type or ->\t<sha256 or ->".
set -euo pipefail
IP=$(curl -s -m 10 https://api.ipify.org)
[[ $IP =~ ^[0-9.]+$ ]] || { echo "cannot find this host's public address" >&2; exit 1; }
get() { curl -s -m 60 --resolve "deflockdane.org:443:$IP" -A "roomkit-parity/0.1 (origin)" "$@"; }
T=$(mktemp); trap 'rm -f "$T"' EXIT
printf '#fetched\t%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
get "https://deflockdane.org/reading-room/" | php -r '
  libxml_use_internal_errors(true);
  $d = new DOMDocument(); $d->loadHTML(stream_get_contents(STDIN));
  $x = new DOMXPath($d);
  foreach ($x->query("//article[contains(concat(\" \", @class, \" \"), \" deflock-reading-room__card \")]") as $card) {
    $a = $x->query(".//h4/a", $card)->item(0);
    $img = $x->query(".//*[contains(@class, \"deflock-reading-room__thumbnail\")]//img", $card)->item(0);
    if (!$a) { continue; }
    $parts = array_values(array_filter(explode("/", parse_url($a->getAttribute("href"), PHP_URL_PATH))));
    // EWWW lazy-load puts a placeholder in src and the real URL in data-src.
    $src = $img ? ($img->getAttribute("data-src") ?: $img->getAttribute("src")) : "-";
    echo end($parts), "\t", $src, "\n";
  }' | while IFS=$'\t' read -r slug src; do
  [[ $slug =~ ^[a-z0-9-]+$ ]] || { echo "bad slug: $slug" >&2; exit 1; }
  if [[ $src == - ]]; then printf '%s\t-\t-\t-\t-\n' "$slug"; continue; fi
  [[ $src == https://deflockdane.org/* ]] || { echo "$slug: thumbnail off the site: $src" >&2; exit 1; }
  meta=$(get -o "$T" -w '%{http_code}\t%{content_type}' "$src" || true)
  printf '%s\t%s\t%s\t%s\n' "$slug" "$src" "$meta" "$(sha256sum "$T" | cut -c1-64)"
  sleep 0.3
done
