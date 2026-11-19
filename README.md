# Helpdesk Telegram Bot

Telegram-бот для заявок в службу поддержки. Пользователь описывает проблему, прикладывает скриншоты и следит за статусом. Администраторы работают с очередями по направлениям, назначают исполнителя и отвечают в заявке. Данные хранятся в локальной SQLite.

## Быстрый старт

Нужен Python 3.10 или новее. В Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Запишите токен своего Telegram-бота в `SYSADMIN_BOT_TOKEN` в файле `.env`. Укажите Telegram ID администраторов через запятую в `SYSADMIN_ADMIN_IDS` или используйте отдельные списки для системного администрирования, 1С и CRM. Если ранее использовались списки Telegram-имён, перенесите администраторов в списки числовых ID. Доступные параметры перечислены в [`.env.example`](.env.example).

```powershell
.\.venv\Scripts\python.exe bot.py
```

В Linux и macOS используйте `.venv/bin/python` и `cp .env.example .env`.

Бот принимает сообщения и команды в личном чате. Откройте бота в Telegram, отправьте `/start` и создайте пробную заявку через `/new`. Команда `/id` показывает ваш Telegram ID. После изменения администраторов в `.env` перезапустите бота и проверьте очередь через `/queue`.

## Данные и интеграции

- `SYSADMIN_DB_PATH` задаёт путь к SQLite. По умолчанию база `tickets.db` создаётся автоматически.
- `SYSADMIN_TIMEZONE` задаёт часовой пояс для отметок времени. `SYSADMIN_RETENTION_DAYS` управляет сроком хранения.
- Интеграция с CRM отключена по умолчанию. Для совместимого API с действительным TLS-сертификатом заполните `SYSADMIN_CRM_API_URL`, `SYSADMIN_CRM_API_SECRET` и список `SYSADMIN_CRM_TELEGRAM_IDS`, затем включите `SYSADMIN_CRM_EXPORT_ENABLED`.

Токены и рабочую SQLite-базу храните вне Git.
