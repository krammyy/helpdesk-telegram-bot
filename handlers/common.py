"""Общие команды и регистрация пользователя."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import APP_VERSION, is_admin
from keyboards import main_menu, queue_button_text
from texts import welcome

router = Router(name="common")


async def _register_user(message: Message, db) -> bool:
    """Обновляет профиль и закрепляет username-админа за Telegram ID."""
    user = message.from_user
    await db.upsert_user(
        user.id,
        user.username,
        user.full_name or user.first_name or "Пользователь",
    )
    return is_admin(user.id)


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext, db) -> None:
    await state.clear()
    user = message.from_user
    admin = await _register_user(message, db)
    await message.answer(
        welcome(user.first_name or "коллега", admin),
        reply_markup=main_menu(user.id),
    )
    if admin:
        await message.answer(
            "🔔 Вы подписаны на уведомления о новых заявках.\n"
            "Входящие заявки коллег смотрите в "
            f"<b>{queue_button_text(user.id)}</b> "
            "(не в «Мои заявки» — там только ваши личные)."
        )


@router.message(Command("menu"))
@router.message(F.text.casefold() == "меню")
async def cmd_menu(message: Message, state: FSMContext, db) -> None:
    """Восстанавливает актуальную клавиатуру без повторного /start."""
    await state.clear()
    admin = await _register_user(message, db)
    user = message.from_user
    title = "Панель администратора восстановлена." if admin else "Главное меню восстановлено."
    await message.answer(
        f"🏠 {title}",
        reply_markup=main_menu(user.id),
    )


@router.message(Command("help"))
@router.message(F.text == "ℹ️ Помощь")
async def cmd_help(message: Message) -> None:
    admin_extra = ""
    u = message.from_user
    if is_admin(u.id):
        admin_extra = (
            "\n\n<b>Для администраторов:</b>\n"
            f"• <b>{queue_button_text(u.id)}</b> — активные заявки "
            "вашего направления\n"
            "• кнопки статуса: взять / ждать / готово\n"
            "• <b>📈 Статистика</b> и <b>🔎 Поиск</b> по номеру или тексту\n"
            "• ваш Telegram ID уже в ADMIN_IDS"
        )
    await message.answer(
        "ℹ️ <b>Как работать с ботом</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "1. Нажмите <b>📝 Новая заявка</b>\n"
        "2. Выберите категорию\n"
        "3. Кратко опишите проблему\n"
        "4. Приложите скриншоты — по желанию\n"
        "5. Укажите место (кабинет/адрес) — по желанию\n"
        "6. Выберите срочность\n\n"
        "Вы получите <b>номер заявки</b> и <b>место в очереди</b>.\n"
        "В «Мои заявки» можно поменять срочность, добавить комментарий "
        "или отменить заявку."
        f"{admin_extra}",
        reply_markup=main_menu(u.id),
    )


@router.message(Command("cancel"))
@router.message(F.text == "❌ Отмена")
async def cmd_cancel(message: Message, state: FSMContext) -> None:
    await state.clear()
    u = message.from_user
    await message.answer(
        "Действие отменено.",
        reply_markup=main_menu(u.id),
    )


@router.callback_query(F.data == "cancel")
async def cb_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await callback.message.edit_text("Действие отменено.")
    await callback.message.answer(
        "Главное меню ниже 👇",
        reply_markup=main_menu(callback.from_user.id),
    )
    await callback.answer()


@router.message(Command("id"))
async def cmd_id(message: Message) -> None:
    await message.answer(
        f"Ваш Telegram ID: <code>{message.from_user.id}</code>\n"
        "Передайте его администратору, чтобы выдать права администратора."
    )


@router.message(Command("version"))
async def cmd_version(message: Message) -> None:
    await message.answer(
        f"🤖 Helpdesk\nВерсия: <code>{APP_VERSION}</code>"
    )
