#!/bin/sh
# One-time cutover: add the stopped Mac workspace to an existing DS918+ export.
set -eu
umask 077
out=$(cd "${1:-$HOME/Downloads/screenit-ds918-1.1.8}" && pwd -P)
[ -s "$out/screenit-amd64.tar" ] || { echo 'Run build-ds918.sh first.' >&2; exit 1; }
if [ -e "$out/data" ] || [ -L "$out/data" ]; then
  echo 'The export already contains data. Nothing was changed.' >&2; exit 1
fi
command -v sqlite3 >/dev/null || { echo 'sqlite3 is required to verify the copy.' >&2; exit 1; }
cd "$HOME/Docker/screenit"
cid=$(docker compose ps --all --quiet screenit)
[ -n "$cid" ] || { echo 'No existing Screenit container found in ~/Docker/screenit.' >&2; exit 1; }
stage=$(mktemp -d "$out/.workspace.XXXXXX")
trap 'rm -rf "$stage"' 0
echo 'Stopping Screenit on the Mac. To resume on the Mac, use docker compose start screenit from the app folder.'
docker compose stop -t 45 screenit
[ "$(docker inspect --format '{{.State.Status}}' "$cid")" = exited ] || { echo 'Container is not stopped; export cancelled.' >&2; exit 1; }
docker cp "$cid:/data/." "$stage/"
[ -s "$stage/screenit.sqlite3" ] || { echo 'No workspace database in the copy. The original is still on the Mac.' >&2; exit 1; }
for db in "$stage"/*.sqlite3; do
  [ "$(sqlite3 -readonly "$db" 'PRAGMA quick_check;')" = ok ] || { echo "Database check failed: ${db##*/}" >&2; exit 1; }
done
sqlite3 -readonly "$stage/screenit.sqlite3" "SELECT 'Workspace revision: ' || revision || ', alerts: ' || (SELECT count(*) FROM rules) || ', history entries: ' || (SELECT count(*) FROM events) FROM workspace WHERE id=1;"
mv "$stage" "$out/data"
echo "Verified workspace copied to $out/data. Leave the Mac container stopped when starting the NAS."
