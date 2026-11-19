"""Конфигурация бота сисадмина."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

APP_VERSION = "2026.10.30"
DATA_RETENTION_DAYS = max(30, int(os.getenv("SYSADMIN_RETENTION_DAYS", "180")))

TIMEZONE_NAME = os.getenv("SYSADMIN_TIMEZONE", "UTC")

BOT_TOKEN = os.getenv("SYSADMIN_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")

PROXY_URL = os.getenv("SYSADMIN_PROXY", "").strip()
ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in (os.getenv("SYSADMIN_ADMIN_IDS") or os.getenv("ADMIN_IDS") or "").split(",")
    if x.strip().isdigit()
}
SYSTEM_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_SYSTEM_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
ONEC_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_ONEC_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
CRM_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_CRM_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
DB_PATH = Path(os.getenv("SYSADMIN_DB_PATH", str(BASE_DIR / "tickets.db")))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}




CRM_EXPORT_ENABLED = _env_bool("SYSADMIN_CRM_EXPORT_ENABLED")
CRM_PILOT_TELEGRAM_ID = int(
    os.getenv("SYSADMIN_CRM_PILOT_TELEGRAM_ID", "0")
)
CRM_TELEGRAM_IDS: set[int] = {
    int(value.strip())
    for value in os.getenv(
        "SYSADMIN_CRM_TELEGRAM_IDS", str(CRM_PILOT_TELEGRAM_ID)
    ).split(",")
    if value.strip().isdigit() and int(value.strip()) > 0
}
CRM_API_URL = os.getenv("SYSADMIN_CRM_API_URL", "").strip()
CRM_API_SECRET = os.getenv("SYSADMIN_CRM_API_SECRET", "").strip()
CRM_API_TIMEOUT_SECONDS = max(
    5, int(os.getenv("SYSADMIN_CRM_API_TIMEOUT_SECONDS", "20"))
)

DEPARTMENT = {
    "system": {
        "label": "Системный администратор",
        "emoji": "🛠",
        "queue_button": "🛠 Очередь сисадмина",
        "queue_title": "Очередь системных администраторов",
    },
    "onec": {
        "label": "Программист / специалист 1С",
        "emoji": "🧑‍💻",
        "queue_button": "🧑‍💻 Очередь 1С",
        "queue_title": "Очередь программистов / специалистов 1С",
    },
    "crm": {
        "label": "Программист CRM / Сайт",
        "emoji": "💻",
        "queue_button": "💻 Очередь CRM / Сайт",
        "queue_title": "Очередь программистов CRM / сайта",
    },
}


DEPARTMENT_ADMINS: dict[str, set[int]] = {
    "system": SYSTEM_ADMIN_IDS,
    "onec": ONEC_ADMIN_IDS,
    "crm": CRM_ADMIN_IDS,
}


PRIORITY = {
    "low": {"label": "Низкий", "emoji": "🟢", "weight": 1},
    "normal": {"label": "Обычный", "emoji": "🟡", "weight": 2},
    "high": {"label": "Высокий", "emoji": "🟠", "weight": 3},
    "critical": {"label": "Критический", "emoji": "🔴", "weight": 4},
}

STATUS = {
    "new": {"label": "Новая", "emoji": "🆕"},
    "in_progress": {"label": "В работе", "emoji": "🔧"},
    "waiting": {"label": "Ожидает ответа", "emoji": "⏳"},
    "done": {"label": "Выполнена", "emoji": "✅"},
    "cancelled": {"label": "Отменена", "emoji": "❎"},
}

CATEGORY = {
    "pc": {"label": "ПК / ноутбук", "emoji": "💻", "department": "system"},
    "network": {"label": "Сеть / интернет", "emoji": "🌐", "department": "system"},
    "printer": {"label": "Принтер / МФУ", "emoji": "🖨️", "department": "system"},
    "software": {"label": "ПО / офис", "emoji": "📦", "department": "system"},
    "access": {"label": "Доступы / учётки", "emoji": "🔑", "department": "system"},
    "phone": {"label": "Телефония", "emoji": "📞", "department": "system"},
    "other": {"label": "Другое", "emoji": "📌", "department": "system"},
    "onec": {"label": "1С", "emoji": "🟨", "department": "onec"},
    "crm": {"label": "CRM", "emoji": "📇", "department": "crm"},
    "site": {"label": "Сайт", "emoji": "🌍", "department": "crm"},
    "development": {
        "label": "Разработка / доработка",
        "emoji": "🧩",
        "department": "onec",
    },
}


def is_admin(user_id: int) -> bool:
    return bool(admin_allowed_categories(user_id))


def admin_departments(user_id: int) -> set[str]:
    if user_id in ADMIN_IDS:
        return set(DEPARTMENT)
    return {department for department, ids in DEPARTMENT_ADMINS.items() if user_id in ids}


def admin_allowed_categories(user_id: int) -> set[str]:
    departments = admin_departments(user_id)
    return {category for category, data in CATEGORY.items() if data["department"] in departments}


def can_access_ticket(user_id: int, category: str) -> bool:
    return category in admin_allowed_categories(user_id)


def admin_ids_for_ticket(department: str, category: str) -> set[int]:
    known = CATEGORY.get(category)
    target = known["department"] if known else department
    return ADMIN_IDS | DEPARTMENT_ADMINS.get(target, set())


def all_admin_ids() -> set[int]:
    return ADMIN_IDS.union(*DEPARTMENT_ADMINS.values())
