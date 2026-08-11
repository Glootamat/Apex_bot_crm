# Production CI/CD

## Что автоматизировано

- `.github/workflows/ci.yml` проверяет backend, frontend, сборку и зависимости.
- `.github/workflows/deploy-production.yml` запускается после успешного CI в `master`
  либо вручную для выбранного ref.
- GitHub Environment `production` должен требовать ручного подтверждения.
- Релизы сохраняются в `/opt/apex-crm/releases/<commit>`.
- `/opt/apex-crm/current` атомарно переключается на проверяемый релиз.
- До переключения создаётся проверенная резервная копия БД.
- При неуспешном `/health` symlink возвращается на предыдущий релиз.

## GitHub Environment и secrets

Создайте Environment `production`, включите required reviewers и добавьте:

- `DEPLOY_HOST` — DNS/IP production-сервера;
- `DEPLOY_USER` — отдельный непривилегированный deployment user;
- `DEPLOY_SSH_KEY` — закрытый ключ этого пользователя;
- `DEPLOY_HOST_KEY` — строка known_hosts, заранее сверенная администратором.

Не используйте `ssh-keyscan` внутри workflow: это не проверяет подлинность сервера.

## Подготовка сервера

На сервере должны быть Python 3, PostgreSQL client, Caddy, curl и systemd. Создайте:

```bash
sudo install -d -o apexcrm -g apexcrm -m 750 /opt/apex-crm/releases
sudo install -d -o apexcrm -g apexcrm -m 750 /opt/apex-crm/shared/uploads
sudo install -d -o apexcrm -g apexcrm -m 750 /opt/apex-crm/shared/backups
sudo install -o apexcrm -g apexcrm -m 600 /dev/null /opt/apex-crm/shared/.env
```

Перенесите production `.env` в `/opt/apex-crm/shared/.env`. Для SQLite перенесите
`workshop.sqlite3` в `/opt/apex-crm/shared/`; PostgreSQL рекомендуется для production.

Deployment user должен иметь запись только в `/opt/apex-crm/releases`, `/tmp` и
необходимые shared-каталоги. В `sudoers` разрешите без пароля только:

- `systemctl daemon-reload`;
- restart `apex-crm-pwa` и `apex-crm-bot`;
- reload `caddy`;
- `caddy validate`;
- установку трёх конкретных конфигурационных файлов из release-каталога.

Не выдавайте deployment user общий `NOPASSWD: ALL`.

## Первый запуск

Первый deploy установит systemd units, Caddyfile, зависимости release и переключит
`current`. После него проверьте:

```bash
systemctl status apex-crm-pwa apex-crm-bot caddy
curl --fail http://127.0.0.1:8000/health
readlink -f /opt/apex-crm/current
```

Секреты, uploads, backup и БД не входят в release artifact и не удаляются при rollback.
Хранятся пять последних релизов.
