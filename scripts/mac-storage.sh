#!/bin/sh
# One-time migration for an existing Docker Desktop installation.
set -eu
cd "$HOME/Docker/screenit"
umask 077
dest="$PWD/data"
override=compose.override.yaml
for file in "$dest" compose.override.yaml compose.override.yml docker-compose.override.yml docker-compose.override.yaml; do
  if [ -e "$file" ] || [ -L "$file" ]; then echo "Already exists: $file. Nothing changed." >&2; exit 1; fi
done
cid=$(docker compose ps --all --quiet screenit)
[ -n "$cid" ] || { echo 'Start the existing Screenit installation first.' >&2; exit 1; }
[ "$(docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Type}}{{end}}{{end}}' "$cid")" = volume ] || { echo 'Expected a Docker volume at /data.' >&2; exit 1; }
stage=$(mktemp -d "$HOME/Docker/.screenit-migration.XXXXXX")
docker compose stop -t 30 screenit
if ! docker cp "$cid:/data/." "$stage/" || [ ! -s "$stage/screenit.sqlite3" ]; then
  docker compose start screenit
  echo 'Copy failed. The original volume is still in use.' >&2; exit 1
fi
chmod u+rwx "$stage"
chmod -R u+rw "$stage"
mv "$stage" "$dest"
cat > "$override" <<EOF
services:
  screenit:
    user: "$(id -u):$(id -g)"
    volumes:
      - type: bind
        source: ./data
        target: /data
        bind:
          create_host_path: false
EOF
if ! docker compose up -d --wait screenit; then
  mv "$override" "$dest/failed-compose-override.yaml"
  docker compose up -d --wait screenit
  echo 'Migration failed. The original volume is back in use.' >&2; exit 1
fi
echo "Screenit now stores its workspace in $dest. Keep $override when updating."
