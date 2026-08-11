#!/usr/bin/env bash
set -Eeuo pipefail

release_id="${1:?release id is required}"
artifact="${2:?artifact path is required}"
app_root="${APEX_APP_ROOT:-/opt/apex-crm}"
releases_dir="$app_root/releases"
release_dir="$releases_dir/$release_id"

if [[ ! "$release_id" =~ ^[A-Za-z0-9._-]{7,64}$ ]]; then
  echo "Invalid release id" >&2
  exit 2
fi
if [[ ! -f "$artifact" ]]; then
  echo "Release artifact is missing" >&2
  exit 2
fi

rm -rf "$release_dir"
mkdir -p "$release_dir"
tar -xzf "$artifact" -C "$release_dir"

python3 -m venv "$release_dir/.venv"
"$release_dir/.venv/bin/pip" install --disable-pip-version-check -r "$release_dir/requirements.txt"

sudo /usr/local/sbin/apex-crm-activate "$release_id"
rm -f "$artifact" /tmp/deploy_release.sh
echo "Release $release_id deployed successfully"
