#!/usr/bin/env bash
set -Eeuo pipefail

release_id="${1:?release id is required}"
app_root="/opt/apex-crm"
release_dir="$app_root/releases/$release_id"
current_link="$app_root/current"
shared_dir="$app_root/shared"
previous_release=""

if [[ ! "$release_id" =~ ^[A-Fa-f0-9]{40}$ ]] || [[ ! -d "$release_dir" ]]; then
  echo "Invalid or missing release" >&2
  exit 2
fi
if [[ ! -f "$shared_dir/.env" ]]; then
  echo "Production environment is missing" >&2
  exit 2
fi
if [[ -L "$current_link" ]]; then
  previous_release="$(readlink -f "$current_link")"
fi

ln -sfn "$shared_dir/.env" "$release_dir/.env"
ln -sfn "$shared_dir/uploads" "$release_dir/uploads"
ln -sfn "$shared_dir/backups" "$release_dir/backups"
if [[ -f "$shared_dir/workshop.sqlite3" ]]; then
  ln -sfn "$shared_dir/workshop.sqlite3" "$release_dir/workshop.sqlite3"
fi

if [[ -x "$current_link/.venv/bin/python" ]]; then
  sudo -u apexcrm "$current_link/.venv/bin/python" "$current_link/deployment/backup_now.py"
fi

rollback() {
  if [[ -n "$previous_release" && -d "$previous_release" ]]; then
    ln -sfn "$previous_release" "$current_link"
    systemctl restart apex-crm-pwa apex-crm-bot || true
  fi
}
trap rollback ERR

ln -sfn "$release_dir" "$current_link"
install -m 644 /usr/local/share/apex-crm/apex-crm-pwa.service /etc/systemd/system/apex-crm-pwa.service
install -m 644 /usr/local/share/apex-crm/apex-crm-bot.service /etc/systemd/system/apex-crm-bot.service
systemctl daemon-reload
systemctl restart apex-crm-pwa apex-crm-bot
for attempt in {1..30}; do
  if curl --fail --silent --show-error --max-time 3 http://127.0.0.1:8000/health >/dev/null; then
    trap - ERR
    find "$app_root/releases" -mindepth 1 -maxdepth 1 -type d -printf '%T@ %p\n' \
      | sort -nr | tail -n +6 | cut -d' ' -f2- | xargs -r rm -rf
    exit 0
  fi
  sleep 2
done

echo "Health check failed" >&2
exit 1
