#!/usr/bin/env bash
# Run dd's live search from the ORIGIN for a query list, for `roomkit parity --search`.
#
# READ-ONLY, writes nothing on the host but a temp file it removes. Run from the Mac,
# each query base64-encoded as an argument (stdin carries the script), here the
# queries of an earlier live file:
#
#   ssh gg-shared bash -s -- $(jq -r '.queries | keys_unsorted[] | @base64' OLD.json) \
#     < roomkit/exporters/deflockdane-fetch-search.sh > LIVE.json
#   python -m roomkit.cli parity --search LIVE.json --out ROOM
#
# Why the origin: deflockdane-fetch-pages.sh. The search is the public form on
# /reading-room/ (?rr_search=<query>): Deflock_Reading_Room_Storage::get_docs,
# MySQL FULLTEXT in boolean mode, results grouped by agency, so the order is
# the page's section order, not relevance (recall is what parity compares).
# The hits are the result page's cards, in page order.
#
# Output: the live file search_parity.py documents (JSON on stdout).
set -euo pipefail
IP=$(curl -s -m 10 https://api.ipify.org)
[[ $IP =~ ^[0-9.]+$ ]] || { echo "cannot find this host's public address" >&2; exit 1; }
T=$(mktemp); trap 'rm -f "$T"' EXIT
FETCHED=$(date -u +%Y-%m-%dT%H:%M:%SZ)
for b64 in "$@"; do
  q=$(printf '%s' "$b64" | base64 -d)
  code=$(curl -s -m 60 --resolve "deflockdane.org:443:$IP" -A "roomkit-parity/0.1 (origin)" -o "$T" -w '%{http_code}' \
           -G --data-urlencode "rr_search=$q" "https://deflockdane.org/reading-room/" || true)
  [[ $code == 200 ]] || { echo "query $q: HTTP $code" >&2; exit 1; }
  # One line per query: base64(query) TAB space-separated slugs.
  printf '%s\t%s\n' "$b64" "$(php -r '
    libxml_use_internal_errors(true);
    $d = new DOMDocument(); $d->loadHTML(file_get_contents($argv[1]));
    $x = new DOMXPath($d); $out = [];
    foreach ($x->query("//article[contains(concat(\" \", @class, \" \"), \" deflock-reading-room__card \")]//h4/a") as $a) {
      $p = array_values(array_filter(explode("/", parse_url($a->getAttribute("href"), PHP_URL_PATH))));
      $out[] = end($p);
    }
    echo implode(" ", $out);' "$T")"
  sleep 0.5
done | php -r '
  $q = [];
  while (($line = fgets(STDIN)) !== false) {
    [$b64, $slugs] = array_pad(explode("\t", rtrim($line, "\n"), 2), 2, "");
    $q[base64_decode($b64)] = $slugs === "" ? [] : explode(" ", $slugs);
  }
  echo json_encode([
    "site" => "deflockdane", "fetched" => $argv[1],
    "source" => "GET https://deflockdane.org/reading-room/?rr_search=<query> (the public search form on /reading-room/, read via the origin with --resolve, so Cloudflare never saw it; exporters/deflockdane-fetch-search.sh)",
    "notes" => "Deflock_Reading_Room_Storage::get_docs: MySQL FULLTEXT boolean prefix matching (+token* for tokens of 3+ characters, the first 8), at most 200 public documents, grouped by agency section on the page, so the order is section order.",
    "queries" => $q,
  ], JSON_PRETTY_PRINT | JSON_UNESCAPED_SLASHES | JSON_UNESCAPED_UNICODE), "\n";' "$FETCHED"
