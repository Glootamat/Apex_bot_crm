# Переход Apex CRM на PostgreSQL

Перенос выполняется один раз. Исходный `workshop.sqlite3` не удаляется и остаётся резервной копией.

## 1. Подготовить PostgreSQL

Для локального запуска можно использовать:

```bash
docker compose up -d postgres
```

На рабочем сервере рекомендуется PostgreSQL 16 или 17 с отдельной базой и пользователем CRM.

## 2. Остановить приложение

```bash
sudo systemctl stop apex-crm-pwa apex-crm-bot
```

Создайте проверенную копию текущей SQLite-базы до переключения.

## 3. Перенести данные

Не добавляйте `DATABASE_URL` в `.env` до создания резервной копии. Затем выполните:

```bash
export DATABASE_URL='postgresql://apex_crm:СЛОЖНЫЙ_ПАРОЛЬ@127.0.0.1:5432/apex_crm'
.venv/bin/python deployment/migrate_sqlite_to_postgres.py
```

Скрипт создаёт актуальную схему, переносит записи с исходными ID, восстанавливает последовательности и не удаляет SQLite-файл. Повторный запуск не создаёт дубликаты.

## 4. Переключить CRM

Добавьте тот же `DATABASE_URL` в `/opt/apex-crm/.env`, затем:

```bash
sudo systemctl start apex-crm-bot apex-crm-pwa
sudo systemctl status apex-crm-bot apex-crm-pwa
```

После проверки клиентов, автомобилей, заказов, финансов и диагностики сохраните SQLite-файл как архив миграции.

## Резервные копии

При наличии `DATABASE_URL` приложение автоматически использует `pg_dump` и проверяет архив через `pg_restore --list`. На сервере должны быть установлены PostgreSQL client tools. Пути можно переопределить через `PG_DUMP_BIN` и `PG_RESTORE_BIN`.
