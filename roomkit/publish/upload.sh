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
#   upload_room SRC_DIR/ DEST    (DEST as rsync takes it, e.g. host:path/)
upload_room() {
  local src=$1 dest=$2
  # -c: compare by checksum, not size and time, so a changed file is never skipped.
  local opts=(-rltc --chmod=D755,F644)
  rsync "${opts[@]}" --exclude='*.html' --exclude='/.htaccess' --exclude='/sitemap.xml' \
    --exclude='/room.lock.json' "$src" "$dest"
  rsync "${opts[@]}" --exclude='/room.lock.json' "$src" "$dest"
  rsync "${opts[@]}" --include='/room.lock.json' --exclude='*' "$src" "$dest"
}

# Every file a lock lists, fetched from the served site through its origin (the
# CDN rate-limits bursts), must hash to the lock. Exit 1 on any difference.
#   verify_served LOCK SSH_HOST DOMAIN MOUNT PYTHON
verify_served() {
  local lock=$1 host=$2 domain=$3 mount=$4 py=$5 out
  out=$(mktemp)
  "$py" - "$lock" "$domain" "$mount" <<'PY' | ssh "$host" bash -s > "$out"
import json, sys
lock, domain, mount = sys.argv[1:4]
print('IP=$(curl -s -m 10 https://api.ipify.org)')
for p in json.load(open(lock))["files"]:
    print(f'printf "%s " "{p}"; curl -s -m 60 --resolve {domain}:443:$IP "https://{domain}{mount}{p}" | sha256sum | cut -c1-64')
PY
  "$py" - "$lock" "$out" <<'PY'
import json, sys
lock = json.load(open(sys.argv[1]))["files"]
served = dict(l.split() for l in open(sys.argv[2]) if l.strip())
bad = [p for p, h in lock.items() if served.get(p) != h]
print(f"   {len(lock) - len(bad)}/{len(lock)} served files match the lock")
for p in bad[:10]: print("   DIFFERS:", p)
sys.exit(1 if bad else 0)
PY
}
