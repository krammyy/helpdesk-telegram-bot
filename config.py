"""Конфигурация бота сисадмина."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")
load_dotenv()  # также из корня репозитория

APP_VERSION = "2026.10.30"
DATA_RETENTION_DAYS = max(30, int(os.getenv("SYSADMIN_RETENTION_DAYS", "180")))
# Часовой пояс для меток заявок
TIMEZONE_NAME = os.getenv("SYSADMIN_TIMEZONE", "UTC")

BOT_TOKEN = os.getenv("SYSADMIN_BOT_TOKEN") or os.getenv("BOT_TOKEN", "")
# Прокси до api.telegram.org (например http://127.0.0.1:1080), пусто — напрямую
PROXY_URL = os.getenv("SYSADMIN_PROXY", "").strip()
ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in (os.getenv("SYSADMIN_ADMIN_IDS") or os.getenv("ADMIN_IDS") or "").split(",")
    if x.strip().isdigit()
}
ADMIN_USERNAMES: set[str] = {
    x.strip().lstrip("@").lower()
    for x in (os.getenv("SYSADMIN_ADMIN_USERNAMES") or "").split(",")
    if x.strip()
}
SYSTEM_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_SYSTEM_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
SYSTEM_ADMIN_USERNAMES: set[str] = {
    x.strip().lstrip("@").lower()
    for x in os.getenv("SYSADMIN_SYSTEM_ADMIN_USERNAMES", "").split(",")
    if x.strip()
}
ONEC_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_ONEC_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
ONEC_ADMIN_USERNAMES: set[str] = {
    x.strip().lstrip("@").lower()
    for x in os.getenv("SYSADMIN_ONEC_ADMIN_USERNAMES", "").split(",")
    if x.strip()
}
CRM_ADMIN_IDS: set[int] = {
    int(x.strip())
    for x in os.getenv("SYSADMIN_CRM_ADMIN_IDS", "").split(",")
    if x.strip().isdigit()
}
CRM_ADMIN_USERNAMES: set[str] = {
    x.strip().lstrip("@").lower()
    for x in os.getenv("SYSADMIN_CRM_ADMIN_USERNAMES", "").split(",")
    if x.strip()
}
DB_PATH = Path(os.getenv("SYSADMIN_DB_PATH", str(BASE_DIR / "tickets.db")))


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# Пилотная интеграция HelpDesk -> тестовая CRM. Доступ определяется только
# стабильным Telegram ID, поэтому смена username не расширит пилот случайно.
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
CRM_API_VERIFY_SSL = _env_bool("SYSADMIN_CRM_API_VERIFY_SSL", True)
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

# Профильные администраторы каждого направления
DEPARTMENT_ADMINS: dict[str, tuple[set[int], set[str]]] = {
    "system": (SYSTEM_ADMIN_IDS, SYSTEM_ADMIN_USERNAMES),
    "onec": (ONEC_ADMIN_IDS, ONEC_ADMIN_USERNAMES),
    "crm": (CRM_ADMIN_IDS, CRM_ADMIN_USERNAMES),
}

# Приоритеты: чем выше число — тем срочнее
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


def is_admin(user_id: int, username: str | None = None) -> bool:
    return bool(admin_allowed_categories(user_id, username))


def admin_departments(user_id: int, username: str | None = None) -> set[str]:
    """Направления, доступные администратору; полный админ видит все."""
    name = username.lower() if username else None
    if user_id in ADMIN_IDS or (name and name in ADMIN_USERNAMES):
        return set(DEPARTMENT)
    return {
        department
        for department, (ids, usernames) in DEPARTMENT_ADMINS.items()
        if user_id in ids or (name and name in usernames)
    }


def admin_allowed_categories(user_id: int, username: str | None = None) -> set[str]:
    """Категории, доступные администратору согласно его роли."""
    departments = admin_departments(user_id, username)
    if not departments:
        return set()
    return {k for k, v in CATEGORY.items() if v["department"] in departments}


def can_access_ticket(
    user_id: int,
    username: str | None,
    department: str,
    category: str,
) -> bool:
    del department  # направление хранится для маршрутизации; права точнее по категории
    return category in admin_allowed_categories(user_id, username)


def admin_identity_sets_for_ticket(
    department: str,
    category: str,
) -> tuple[set[int], set[str]]:
    """Полные админы плюс профильные админы направления заявки.

    Направление берём по категории: права проверяются именно по ней, поэтому
    старая заявка с неактуальным полем department не уйдёт «не тем» админам.
    """
    ids = set(ADMIN_IDS)
    usernames = set(ADMIN_USERNAMES)
    known = CATEGORY.get(category)
    target = known["department"] if known else department
    dept_ids, dept_usernames = DEPARTMENT_ADMINS.get(target, (set(), set()))
    ids.update(dept_ids)
    usernames.update(dept_usernames)
    return ids, usernames


def all_admin_identity_sets() -> tuple[set[int], set[str]]:
    ids = set(ADMIN_IDS)
    usernames = set(ADMIN_USERNAMES)
    for dept_ids, dept_usernames in DEPARTMENT_ADMINS.values():
        ids.update(dept_ids)
        usernames.update(dept_usernames)
    return ids, usernames


def promote_admin_identity(user_id: int, username: str | None) -> None:
    """Закрепляет настроенный username за стабильным Telegram ID в памяти."""
    if not username:
        return
    name = username.lower()
    if name in ADMIN_USERNAMES:
        ADMIN_IDS.add(user_id)
    for dept_ids, dept_usernames in DEPARTMENT_ADMINS.values():
        if name in dept_usernames:
            dept_ids.add(user_id)
