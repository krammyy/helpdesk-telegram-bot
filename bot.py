"""Точка входа Helpdesk Telegram-бота."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import (
    ADMIN_IDS,
    ADMIN_USERNAMES,
    BOT_TOKEN,
    DATA_RETENTION_DAYS,
    DEPARTMENT_ADMINS,
    PROXY_URL,
    all_admin_identity_sets,
)
from database import Database
from crm_client import CrmClient
from handlers import admin, client, common

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
)
log = logging.getLogger("sysadmin_bot")


async def main() -> None:
    if not BOT_TOKEN:
        log.error(
            "Не задан токен. Создайте .env с SYSADMIN_BOT_TOKEN=..."
        )
        sys.exit(1)
    configured_admin_ids, configured_admin_usernames = all_admin_identity_sets()
    if not configured_admin_ids and not configured_admin_usernames:
        log.warning(
            "Списки администраторов пусты — админ-меню никто не увидит. "
            "Узнайте ID командой /id и добавьте роль в .env"
        )

    db = Database()
    await db.connect()
    # Большинство админов исторически настроены по username. После первого
    # обращения их Telegram ID уже есть в users; поднимаем эти ID в память,
    # чтобы права и клавиатура не зависели от наличия username в каждом update.
    ADMIN_IDS.update(await db.admin_recipient_ids(ADMIN_IDS, ADMIN_USERNAMES))
    for dept_ids, dept_usernames in DEPARTMENT_ADMINS.values():
        dept_ids.update(await db.admin_recipient_ids(dept_ids, dept_usernames))
    all_admin_ids, all_admin_usernames = all_admin_identity_sets()
    deleted_tickets, deleted_users = await db.cleanup_expired(
        DATA_RETENTION_DAYS, all_admin_usernames, all_admin_ids
    )
    log.info(
        "Политика хранения %s дней: удалено заявок %s, пользователей %s",
        DATA_RETENTION_DAYS,
        deleted_tickets,
        deleted_users,
    )

    session = AiohttpSession(proxy=PROXY_URL) if PROXY_URL else None
    if PROXY_URL:
        log.info("Telegram API через прокси")
    bot = Bot(
        token=BOT_TOKEN,
        session=session,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp["db"] = db
    dp["crm_client"] = CrmClient()

    dp.include_router(common.router)
    dp.include_router(admin.router)
    dp.include_router(client.router)

    me = await bot.get_me()
    try:
        await bot.set_my_commands(
            [
                BotCommand(command="menu", description="Восстановить главное меню"),
                BotCommand(command="new", description="Создать заявку"),
                BotCommand(command="my", description="Мои активные заявки"),
                BotCommand(command="queue", description="Общая очередь (для админов)"),
                BotCommand(command="help", description="Помощь"),
                BotCommand(command="version", description="Версия бота"),
            ]
        )
        await bot.set_my_name(name="Helpdesk")
        await bot.set_my_description(
            description=(
                "Служба поддержки. Создавайте заявки, следите за очередью "
                "и статусом обращений."
            )
        )
        await bot.set_my_short_description(
            short_description="Helpdesk — заявки в службу поддержки"
        )
    except Exception as exc:
        log.warning("Не удалось обновить имя/описание бота: %s", exc)
    all_admin_ids, all_admin_usernames = all_admin_identity_sets()
    log.info("Бот @%s запущен. Админов: %s", me.username, len(all_admin_ids))
    missing = await db.unresolved_admin_usernames(
        all_admin_ids, all_admin_usernames
    )
    if missing:
        log.warning(
            "Админы ещё не писали боту (/start) — пуши им не дойдут: %s",
            ", ".join(sorted("@" + m for m in missing)),
        )

    try:
        await dp.start_polling(bot, db=db)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
