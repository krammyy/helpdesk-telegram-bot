"""Клиентские сценарии: создание и просмотр заявок."""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InputMediaPhoto, Message

from config import (
    CATEGORY,
    DEPARTMENT,
    PRIORITY,
    admin_ids_for_ticket,
    can_access_ticket,
    is_admin,
)
from keyboards import (
    PAGE_SIZE,
    cancel_kb,
    categories_kb,
    client_ticket_kb,
    confirm_cancel_kb,
    department_kb,
    main_menu,
    priority_for_ticket_kb,
    priority_kb,
    screenshots_kb,
    skip_location_kb,
    user_tickets_kb,
)
from states import CommentTicket, CreateTicket
from texts import ticket_card, ticket_created

router = Router(name="client")
log = logging.getLogger("sysadmin_bot.client")


async def _notify_admins(
    bot,
    db,
    text: str,
    department: str,
    category: str,
    screenshot_ids: list[str] | None = None,
) -> None:
    recipients = admin_ids_for_ticket(
        department, category
    )
    if not recipients:
        log.error("Нет получателей для админ-уведомления")
        return
    for aid in recipients:
        try:
            await bot.send_message(aid, text)
            if screenshot_ids:
                if len(screenshot_ids) == 1:
                    await bot.send_photo(
                        aid, screenshot_ids[0], caption="📎 Скриншот к заявке"
                    )
                else:
                    await bot.send_media_group(
                        aid,
                        [
                            InputMediaPhoto(
                                media=file_id,
                                caption="📎 Скриншоты к заявке" if i == 0 else None,
                            )
                            for i, file_id in enumerate(screenshot_ids)
                        ],
                    )
        except Exception as exc:
            log.warning("Не удалось уведомить админа %s: %s", aid, exc)


async def _notify_ticket_specialist(bot, db, ticket: dict, text: str) -> None:
    """Отправляет ответ назначенному специалисту или профильной очереди."""
    admin_id = ticket.get("admin_id")
    if not admin_id or not can_access_ticket(int(admin_id), ticket["category"]):
        await _notify_admins(
            bot,
            db,
            text,
            ticket["department"],
            ticket["category"],
        )
        return

    try:
        await bot.send_message(int(admin_id), text)
    except Exception as exc:
        log.warning(
            "Не удалось доставить ответ по заявке #%s специалисту %s: %s",
            ticket["id"],
            admin_id,
            exc,
        )


def _admin_can_access(user, ticket: dict) -> bool:
    return can_access_ticket(user.id, ticket.get("category") or "other")

async def _ask_location(message, state: FSMContext) -> None:
    await state.set_state(CreateTicket.location)
    await message.answer(
        "📍 Укажите место (кабинет, склад, ФИО компьютера) или пропустите:",
        reply_markup=skip_location_kb(),
    )


@router.message(Command("new"))
@router.message(F.text == "📝 Новая заявка")
@router.callback_query(F.data == "new")
async def start_create(event: Message | CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(CreateTicket.department)
    text = (
        "📝 <b>Новая заявка</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "Кому адресована заявка?"
    )
    if isinstance(event, CallbackQuery):
        await event.message.answer(text, reply_markup=department_kb())
        await event.answer()
    else:
        await event.answer(text, reply_markup=department_kb())


@router.callback_query(CreateTicket.department, F.data.startswith("dept:"))
async def choose_department(callback: CallbackQuery, state: FSMContext) -> None:
    department = callback.data.split(":", 1)[1]
    if department not in DEPARTMENT:
        await callback.answer("Неизвестное направление", show_alert=True)
        return
    await state.update_data(department=department)
    await state.set_state(CreateTicket.category)
    item = DEPARTMENT[department]
    await callback.message.edit_text(
        f"{item['emoji']} Направление: <b>{item['label']}</b>\n\n"
        "Выберите категорию проблемы:",
        reply_markup=categories_kb(department),
    )
    await callback.answer()


@router.callback_query(CreateTicket.category, F.data.startswith("cat:"))
async def choose_category(callback: CallbackQuery, state: FSMContext) -> None:
    key = callback.data.split(":", 1)[1]
    data = await state.get_data()
    department = data.get("department")
    if key not in CATEGORY or CATEGORY[key]["department"] != department:
        await callback.answer("Неизвестная категория", show_alert=True)
        return
    await state.update_data(category=key)
    await state.set_state(CreateTicket.title)
    cat = CATEGORY[key]
    await callback.message.edit_text(
        f"{cat['emoji']} Категория: <b>{cat['label']}</b>\n\n"
        "Кратко сформулируйте тему (одной строкой):\n"
        "<i>Например: «Не печатает МФУ в кабинете 12»</i>"
    )
    await callback.message.answer("Жду тему заявки…", reply_markup=cancel_kb())
    await callback.answer()


@router.message(CreateTicket.title, F.text)
async def set_title(message: Message, state: FSMContext) -> None:
    u = message.from_user
    title = (message.text or "").strip()
    if title == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id))
        return
    if len(title) < 3:
        await message.answer("Слишком коротко. Напишите тему от 3 символов.")
        return
    if len(title) > 120:
        await message.answer("Укоротите тему до 120 символов.")
        return
    await state.update_data(title=title)
    await state.set_state(CreateTicket.description)
    await message.answer(
        "Опишите проблему подробнее:\n"
        "• что происходит\n"
        "• когда началось\n"
        "• что уже пробовали",
        reply_markup=cancel_kb(),
    )


@router.message(CreateTicket.description, F.text)
async def set_description(message: Message, state: FSMContext) -> None:
    u = message.from_user
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id))
        return
    if len(text) < 5:
        await message.answer("Добавьте чуть больше деталей (от 5 символов).")
        return
    if len(text) > 2000:
        await message.answer("Сократите описание до 2000 символов.")
        return
    await state.update_data(description=text, screenshots=[])
    await state.set_state(CreateTicket.screenshots)
    await message.answer(
        "📸 <b>Приложите скриншоты проблемы</b> — они помогут решить заявку быстрее.\n\n"
        "Можно отправить до 5 изображений по одному. После загрузки нажмите «Готово».\n"
        "Если скриншотов нет, нажмите «Без скриншотов».",
        reply_markup=screenshots_kb(),
    )


@router.message(CreateTicket.screenshots, F.photo)
async def add_screenshot(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    screenshots = list(data.get("screenshots", []))
    if len(screenshots) >= 5:
        await message.answer(
            "Можно приложить не более 5 скриншотов. Нажмите «Готово».",
            reply_markup=screenshots_kb(has_screenshots=True),
        )
        return
    screenshots.append(message.photo[-1].file_id)
    await state.update_data(screenshots=screenshots)
    await message.answer(
        f"📎 Скриншот добавлен: <b>{len(screenshots)}/5</b>.\n"
        "Отправьте следующий или нажмите «Готово».",
        reply_markup=screenshots_kb(has_screenshots=True),
    )


@router.callback_query(CreateTicket.screenshots, F.data.in_({"screens:skip", "screens:done"}))
async def finish_screenshots(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    screenshots = list(data.get("screenshots", []))
    if callback.data == "screens:done" and not screenshots:
        await callback.answer("Сначала отправьте скриншот или нажмите «Без скриншотов»", show_alert=True)
        return
    await callback.message.edit_text(
        f"📎 Добавлено скриншотов: <b>{len(screenshots)}</b>"
        if screenshots
        else "Продолжаем без скриншотов."
    )
    await _ask_location(callback.message, state)
    await callback.answer()


@router.message(CreateTicket.screenshots)
async def screenshot_expected(message: Message) -> None:
    await message.answer(
        "Отправьте изображение как фото или нажмите «Без скриншотов».",
        reply_markup=screenshots_kb(),
    )


@router.callback_query(CreateTicket.location, F.data == "loc:skip")
async def skip_location(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(location=None)
    await state.set_state(CreateTicket.priority)
    await callback.message.edit_text(
        "⚡ Выберите <b>срочность</b> заявки:",
        reply_markup=priority_kb(),
    )
    await callback.answer()


@router.message(CreateTicket.location, F.text)
async def set_location(message: Message, state: FSMContext) -> None:
    u = message.from_user
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id))
        return
    await state.update_data(location=text[:200])
    await state.set_state(CreateTicket.priority)
    await message.answer(
        "⚡ Выберите <b>срочность</b> заявки:",
        reply_markup=priority_kb(),
    )


@router.callback_query(CreateTicket.priority, F.data.startswith("prio:"))
async def set_priority_and_create(
    callback: CallbackQuery, state: FSMContext, db, bot
) -> None:
    key = callback.data.split(":", 1)[1]
    if key not in PRIORITY:
        await callback.answer("Неизвестная срочность", show_alert=True)
        return

    data = await state.get_data()
    user = callback.from_user
    await db.upsert_user(
        user.id, user.username, user.full_name or user.first_name or "Пользователь"
    )

    ticket_id = await db.create_ticket(
        user_id=user.id,
        department=data["department"],
        category=data["category"],
        title=data["title"],
        description=data["description"],
        priority=key,
        location=data.get("location"),
    )
    screenshot_ids = list(data.get("screenshots", []))
    await db.add_attachments(ticket_id, screenshot_ids)
    position = await db.queue_position(ticket_id)
    await state.clear()

    await callback.message.edit_text(ticket_created(ticket_id, position, key))
    await callback.message.answer(
        "Что дальше?",
        reply_markup=main_menu(user.id),
    )
    await callback.answer("Заявка создана!")

    ticket = await db.get_ticket(ticket_id)
    notify = (
        "🚨 <b>Новая заявка в очереди</b>\n\n"
        + ticket_card(ticket, position=position, show_user=True)
    )
    await _notify_admins(
        bot,
        db,
        notify,
        ticket["department"],
        ticket["category"],
        screenshot_ids,
    )


@router.message(F.text == "📂 Мои заявки")
@router.message(Command("my"))
async def my_tickets(message: Message, db) -> None:
    u = message.from_user
    tickets = await db.list_user_tickets(u.id, active_only=True)
    tip = ""
    if is_admin(u.id):
        tip = (
            "\n\n🛠 Входящие заявки сотрудников — в <b>Общая очередь</b> "
            "или <b>На мне</b>."
        )
    if not tickets:
        await message.answer(
            "У вас нет активных заявок.\n"
            "Нажмите <b>📝 Новая заявка</b>, чтобы создать новую."
            f"{tip}",
            reply_markup=main_menu(u.id),
        )
        return
    header = (
        f"📂 <b>Ваши активные заявки</b>\n"
        f"Всего: <b>{len(tickets)}</b>"
        f"{tip}"
    )
    page_tickets = tickets[:PAGE_SIZE]
    await message.answer(
        header,
        reply_markup=user_tickets_kb(page_tickets, page=0, total=len(tickets)),
    )


@router.callback_query(F.data.startswith("my_page:"))
async def my_tickets_page(callback: CallbackQuery, db) -> None:
    page = max(0, int(callback.data.split(":", 1)[1]))
    tickets = await db.list_user_tickets(callback.from_user.id, active_only=True)
    pages = max(1, (len(tickets) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, pages - 1)
    start = page * PAGE_SIZE
    current = tickets[start : start + PAGE_SIZE]
    await callback.message.edit_text(
        f"📂 <b>Ваши активные заявки</b>\n"
        f"Всего: <b>{len(tickets)}</b> · страница <b>{page + 1}/{pages}</b>",
        reply_markup=user_tickets_kb(current, page=page, total=len(tickets)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("ticket:"))
async def show_ticket(callback: CallbackQuery, db) -> None:
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Заявка не найдена", show_alert=True)
        return

    uid = callback.from_user.id
    uname = callback.from_user.username
    admin_access = _admin_can_access(callback.from_user, ticket)
    if ticket["user_id"] != uid and not admin_access:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if ticket["status"] in ("done", "cancelled") and not admin_access:
        await callback.answer("Заявка перемещена в архив", show_alert=True)
        return

    position = await db.queue_position(ticket_id)
    comments = await db.get_comments(ticket_id)
    text = ticket_card(
        ticket,
        position=position,
        show_user=admin_access,
        comments=comments,
    )

    from keyboards import admin_ticket_kb

    kb = (
        admin_ticket_kb(
            ticket_id,
            ticket["status"],
            viewer_id=uid,
            assignee_id=ticket.get("admin_id"),
        )
        if admin_access
        else client_ticket_kb(ticket_id, ticket["status"])
    )
    await callback.message.edit_text(text, reply_markup=kb)
    await callback.answer()


@router.callback_query(F.data.startswith("attachments:"))
async def show_attachments(callback: CallbackQuery, db, bot) -> None:
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Заявка не найдена", show_alert=True)
        return
    uid = callback.from_user.id
    if ticket["user_id"] != uid and not _admin_can_access(callback.from_user, ticket):
        await callback.answer("Нет доступа", show_alert=True)
        return
    attachments = await db.get_attachments(ticket_id)
    if not attachments:
        await callback.answer("К заявке скриншоты не приложены", show_alert=True)
        return
    if len(attachments) == 1:
        await bot.send_photo(uid, attachments[0], caption=f"📎 Скриншот к заявке #{ticket_id}")
    else:
        await bot.send_media_group(
            uid,
            [
                InputMediaPhoto(media=file_id, caption=f"📎 Скриншоты к заявке #{ticket_id}" if i == 0 else None)
                for i, file_id in enumerate(attachments)
            ],
        )
    await callback.answer()


@router.callback_query(F.data.startswith("prio_menu:"))
async def priority_menu(callback: CallbackQuery, db) -> None:
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Не найдено", show_alert=True)
        return
    uid = callback.from_user.id
    uname = callback.from_user.username
    admin_access = _admin_can_access(callback.from_user, ticket)
    if ticket["user_id"] != uid and not admin_access:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if ticket["status"] in ("done", "cancelled") and not admin_access:
        await callback.answer("Заявка уже закрыта", show_alert=True)
        return
    await callback.message.edit_text(
        f"⚡ Срочность для заявки <b>#{ticket_id}</b>:",
        reply_markup=priority_for_ticket_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("setprio:"))
async def change_priority(callback: CallbackQuery, db, bot) -> None:
    _, tid, key = callback.data.split(":", 2)
    ticket_id = int(tid)
    if key not in PRIORITY:
        await callback.answer("Ошибка", show_alert=True)
        return

    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Не найдено", show_alert=True)
        return
    uid = callback.from_user.id
    uname = callback.from_user.username
    admin_access = _admin_can_access(callback.from_user, ticket)
    if ticket["user_id"] != uid and not admin_access:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if ticket["status"] in ("done", "cancelled") and not admin_access:
        await callback.answer("Заявка перемещена в архив", show_alert=True)
        return

    await db.set_priority(ticket_id, key)
    ticket = await db.get_ticket(ticket_id)
    position = await db.queue_position(ticket_id)
    pri = PRIORITY[key]

    if not admin_access:
        await _notify_admins(
            bot,
            db,
            f"⚡ Клиент изменил срочность #{ticket_id} → {pri['emoji']} {pri['label']}",
            ticket["department"],
            ticket["category"],
        )
    elif ticket["user_id"] != uid:
        try:
            await bot.send_message(
                ticket["user_id"],
                f"⚡ Срочность вашей заявки <b>#{ticket_id}</b> "
                f"изменена на {pri['emoji']} <b>{pri['label']}</b>",
            )
        except Exception:
            pass

    from keyboards import admin_ticket_kb

    kb = (
        admin_ticket_kb(
            ticket_id,
            ticket["status"],
            viewer_id=uid,
            assignee_id=ticket.get("admin_id"),
        )
        if admin_access
        else client_ticket_kb(ticket_id, ticket["status"])
    )
    await callback.message.edit_text(
        ticket_card(ticket, position=position, show_user=admin_access),
        reply_markup=kb,
    )
    await callback.answer(f"Срочность: {pri['label']}")


@router.callback_query(F.data.startswith("cancel_ticket:"))
async def ask_cancel(callback: CallbackQuery, db) -> None:
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if ticket["status"] in ("done", "cancelled"):
        await callback.answer("Заявка уже закрыта", show_alert=True)
        return
    await callback.message.edit_text(
        f"Отменить заявку <b>#{ticket_id}</b>?",
        reply_markup=confirm_cancel_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("confirm_cancel:"))
async def do_cancel(callback: CallbackQuery, db, bot) -> None:
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Нет доступа", show_alert=True)
        return
    await db.set_status(ticket_id, "cancelled")
    await callback.message.edit_text(f"❎ Заявка <b>#{ticket_id}</b> отменена.")
    await callback.answer()
    await _notify_admins(
        bot,
        db,
        f"❎ Клиент отменил заявку <b>#{ticket_id}</b>",
        ticket["department"],
        ticket["category"],
    )


@router.callback_query(F.data.startswith("ccomment:"))
async def start_client_comment(
    callback: CallbackQuery, state: FSMContext, db
) -> None:
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != callback.from_user.id:
        await callback.answer("Нет доступа", show_alert=True)
        return
    if ticket["status"] in ("done", "cancelled"):
        await callback.answer("Заявка закрыта", show_alert=True)
        return
    await state.set_state(CommentTicket.waiting)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.answer(
        f"💬 Напишите комментарий к заявке <b>#{ticket_id}</b>:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(CommentTicket.waiting, F.text)
async def save_client_comment(message: Message, state: FSMContext, db, bot) -> None:
    u = message.from_user
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id))
        return
    data = await state.get_data()
    ticket_id = data["ticket_id"]
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != message.from_user.id:
        await state.clear()
        await message.answer("Заявка недоступна.", reply_markup=main_menu(u.id))
        return
    await db.add_comment(ticket_id, message.from_user.id, text, is_admin=False)
    await state.clear()
    await message.answer(
        f"Комментарий добавлен к #{ticket_id}.",
        reply_markup=main_menu(u.id),
    )
    await _notify_ticket_specialist(
        bot,
        db,
        ticket,
        f"💬 Комментарий клиента к <b>#{ticket_id}</b>:\n{text}",
    )


@router.message(F.text, F.reply_to_message)
async def save_client_native_reply(message: Message, db, bot) -> None:
    """Принимает обычный Telegram-ответ на сообщение специалиста."""
    replied = message.reply_to_message
    if not replied or not replied.from_user or not replied.from_user.is_bot:
        return

    source_text = replied.text or replied.caption or ""
    match = re.search(r"по заявке\s*#(\d+)\b", source_text, flags=re.IGNORECASE)
    if not match:
        return

    ticket_id = int(match.group(1))
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["user_id"] != message.from_user.id:
        await message.answer("Не удалось определить доступную заявку для ответа.")
        return
    if ticket["status"] in ("done", "cancelled"):
        await message.answer("Эта заявка уже закрыта. Откройте новую заявку, если помощь ещё нужна.")
        return

    text = (message.text or "").strip()
    if not text:
        return

    await db.add_comment(ticket_id, message.from_user.id, text, is_admin=False)
    await message.answer(
        f"Ответ отправлен специалисту по заявке #{ticket_id}.",
        reply_markup=main_menu(message.from_user.id),
    )
    await _notify_ticket_specialist(
        bot,
        db,
        ticket,
        f"💬 Ответ клиента по <b>#{ticket_id}</b>:\n{text}",
    )
