"""Точка входа Helpdesk Telegram-бота."""

from __future__ import annotations

import asyncio
import logging
import sys

from aiogram import F, Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.enums import ChatType, ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand

from config import (
    BOT_TOKEN,
    DATA_RETENTION_DAYS,
    PROXY_URL,
    all_admin_ids,
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
    configured_admin_ids = all_admin_ids()
    if not configured_admin_ids:
        log.warning(
            "Списки администраторов пусты — админ-меню никто не увидит. "
            "Узнайте ID командой /id и добавьте роль в .env"
        )

    db = Database()
    await db.connect()
    deleted_tickets, deleted_users = await db.cleanup_expired(
        DATA_RETENTION_DAYS, configured_admin_ids
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
    dp.message.filter(F.chat.type == ChatType.PRIVATE)
    dp.callback_query.filter(F.message.chat.type == ChatType.PRIVATE)
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
    log.info("Бот @%s запущен. Админов: %s", me.username, len(configured_admin_ids))

    try:
        await dp.start_polling(bot, db=db)
    finally:
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
