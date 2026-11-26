#!/bin/sh
# Run on the Mac. Build a separate local amd64 image without replacing the Mac tag.
set -eu
umask 077
cd "$(dirname "$0")/.."
out=${1:-"$HOME/Downloads/screenit-ds918-1.1.6"}
[ ! -e "$out" ] || { echo "Already exists: $out. Choose a new output folder." >&2; exit 1; }
mkdir -p "$(dirname "$out")"
stage=$(mktemp -d "$(dirname "$out")/.screenit-export.XXXXXX")
trap 'rm -rf "$stage"' 0
tag=$(awk '$1=="image:" {print $2;exit}' deploy/ds918/compose.yaml)
docker buildx build --platform linux/amd64 --build-arg RUNTIME_USER=0:0 --load --tag "$tag" .
[ "$(docker image inspect --format '{{.Config.User}}' "$tag")" = '0:0' ] || { echo 'Expected container user 0:0' >&2; exit 1; }
[ "$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$tag")" = linux/amd64 ] || { echo 'Expected linux/amd64' >&2; exit 1; }
docker run --rm --platform linux/amd64 --network none --read-only --tmpfs /tmp --entrypoint python "$tag" -c 'import tempfile; from src.markets import MarketFeed; from src.server import Store; from pathlib import Path; d=tempfile.TemporaryDirectory(); Store(Path(d.name)/"workspace.sqlite3"); MarketFeed(d.name).close(); print("PASS amd64 runtime and SQLite")'
docker image save -o "$stage/screenit-amd64.tar" "$tag"
cp deploy/ds918/compose.yaml deploy/ds918/INSTALL.md "$stage/"
(cd "$stage" && shasum -a 256 screenit-amd64.tar > SHA256SUMS)
mv "$stage" "$out"
echo "Synology package: $out"
