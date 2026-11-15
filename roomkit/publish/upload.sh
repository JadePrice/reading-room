# Sourced by the publish scripts: upload a built room in the order that keeps
# every served page whole while it lands (roadmap P2).
#
#   1. assets and data (content-hashed names, pages.json, thumbnails, pagefind/):
#      new names, so nothing served yet refers to them;
#   2. HTML, .htaccess and the rest, which now find every asset they name;
#   3. room.lock.json last, so the served lock never describes files that have
#      not arrived (step 4's diff and step 6's check read it).
#
# Nothing is deleted here; removal is the publish script's next step.
# Each pass draws a bar (bar.py) from rsync's own files-left counter, so a long upload
# shows where it is; the caller's $PY (python3 if unset) draws it. An rsync without
# --info (macOS's /usr/bin/rsync is openrsync) uploads the same, without a bar.
# An upload cut off midway is rerun whole: -c skips every file that already landed.
#   upload_room SRC_DIR/ DEST    (DEST as rsync takes it, e.g. host:path/)
BAR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/bar.py"

_rsync_pass() {
  local label=$1; shift
  if rsync --info=progress2 --version >/dev/null 2>&1; then
    rsync --info=progress2 --no-inc-recursive "$@" | "${PY:-python3}" "$BAR" rsync "$label"
    return "${PIPESTATUS[0]}"
  fi
  rsync "$@"
}

upload_room() {
  local src=$1 dest=$2
  # -c: compare by checksum, not size and time, so a changed file is never skipped.
  local opts=(-rltc --chmod=D755,F644)
  _rsync_pass "1/3 assets" "${opts[@]}" --exclude='*.html' --exclude='/.htaccess' --exclude='/sitemap.xml' \
    --exclude='/room.lock.json' "$src" "$dest"
  _rsync_pass "2/3 pages" "${opts[@]}" --exclude='/room.lock.json' "$src" "$dest"
  _rsync_pass "3/3 lock" "${opts[@]}" --include='/room.lock.json' --exclude='*' "$src" "$dest"
}

# Every file a lock lists, fetched from the served site through its origin (the
# CDN rate-limits bursts), must hash to the lock. Exit 1 on any difference.
#   verify_served LOCK SSH_HOST DOMAIN MOUNT PYTHON [SCHEME]
# SCHEME is https (default) or http: Cloudflare reaches site A's origin on :80 only,
# and a --resolve to :443 there lands on a different server.
# The fetches run VERIFY_CHUNK files to an ssh session (default 250) with a bar across
# them, so a dropped connection costs one chunk, which is tried once more, not the run.
verify_served() {
  local lock=$1 host=$2 domain=$3 mount=$4 py=$5 scheme=${6:-https} out cmds total n=0 i
  local chunk=${VERIFY_CHUNK:-250}
  out=$(mktemp); cmds=$(mktemp -d)
  "$py" - "$lock" "$domain" "$mount" "$scheme" "$chunk" "$cmds" <<'PY'
import json, sys
lock, domain, mount, scheme, chunk, cmds = sys.argv[1:7]
port = 80 if scheme == "http" else 443
files = list(json.load(open(lock))["files"])
for i in range(0, len(files), int(chunk)):
    with open(f"{cmds}/{i // int(chunk):05d}.sh", "w") as f:
        f.write('IP=$(curl -s -m 10 https://api.ipify.org)\n')
        for p in files[i:i + int(chunk)]:
            f.write(f'printf "%s " "{p}"; curl -s -m 60 --resolve {domain}:{port}:$IP "{scheme}://{domain}{mount}{p}" | (sha256sum 2>/dev/null || shasum -a 256) | cut -c1-64\n')
PY
  total=$("$py" -c "import json,sys;print(len(json.load(open(sys.argv[1]))['files']))" "$lock")
  for i in "$cmds"/*.sh; do
    local part; part=$(mktemp)
    if ! ssh "$host" bash -s < "$i" | "$py" "$BAR" count "verify" "$total" --start "$n" --tee "$part" \
        || [ "$(wc -l < "$part")" -ne "$(grep -c '^printf' "$i")" ]; then
      echo; echo "   chunk $(basename "$i" .sh) came back short; trying it once more"
      : > "$part"
      ssh "$host" bash -s < "$i" | "$py" "$BAR" count "verify" "$total" --start "$n" --tee "$part" || true
    fi
    cat "$part" >> "$out"
    n=$(( n + $(grep -c '^printf' "$i") ))
    rm -f "$part"
  done
  rm -rf "$cmds"
  "$py" - "$lock" "$out" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))["files"]
served = dict(l.split() for l in open(sys.argv[2]) if len(l.split()) == 2)
bad = [p for p, h in lock.items() if served.get(p) != h]
print(f"   {len(lock) - len(bad)}/{len(lock)} served files match the lock")
for p in bad[:10]: print("   DIFFERS:", p)
sys.exit(1 if bad else 0)
PY
}
