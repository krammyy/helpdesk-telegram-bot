"""Админские сценарии: очередь, статусы, поиск, статистика."""

from __future__ import annotations

import html
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message

from config import (
    CRM_EXPORT_ENABLED,
    CRM_TELEGRAM_IDS,
    DEPARTMENT,
    STATUS,
    admin_allowed_categories,
    admin_departments,
    admin_identity_sets_for_ticket,
    can_access_ticket,
    is_admin,
)
from crm_client import CrmIntegrationError
from keyboards import (
    PAGE_SIZE,
    QUEUE_BUTTONS,
    admin_ticket_kb,
    archive_tickets_kb,
    cancel_kb,
    claim_taken_kb,
    client_reply_kb,
    confirm_claim_kb,
    crm_comment_choice_kb,
    crm_confirm_kb,
    crm_offer_kb,
    crm_report_kb,
    crm_retry_kb,
    crm_title_kb,
    main_menu,
    remove_kb,
    queue_filter_kb,
    queue_tickets_kb,
)
from states import AdminComment, CrmExport, SearchTicket
from texts import queue_list, stats_card, ticket_card

router = Router(name="admin")
log = logging.getLogger("sysadmin_bot.admin")


def _admin_only(user_id: int, username: str | None = None) -> bool:
    return is_admin(user_id, username)


def _crm_pilot(user_id: int) -> bool:
    return CRM_EXPORT_ENABLED and user_id in CRM_TELEGRAM_IDS


def _parse_duration_minutes(value: str) -> int | None:
    """Понимает 45, 45м, 1ч 30м и 2:15."""
    text = value.strip().casefold()
    minutes: int | None = None
    if text.isdigit():
        minutes = int(text)
    elif match := re.fullmatch(r"(\d{1,3}):(\d{1,2})", text):
        hours, remainder = map(int, match.groups())
        if remainder < 60:
            minutes = hours * 60 + remainder
    else:
        match = re.fullmatch(
            r"\s*(?:(\d+)\s*(?:ч|час(?:а|ов)?))?\s*"
            r"(?:(\d+)\s*(?:м|мин(?:ут(?:а|ы)?)?))?\s*",
            text,
        )
        if match and any(match.groups()):
            hours = int(match.group(1) or 0)
            remainder = int(match.group(2) or 0)
            if remainder < 60 or hours == 0:
                minutes = hours * 60 + remainder
    if minutes is None or not 1 <= minutes <= 7 * 24 * 60:
        return None
    return minutes


def _duration_label(minutes: int) -> str:
    hours, remainder = divmod(minutes, 60)
    if hours and remainder:
        return f"{hours} ч {remainder} мин"
    if hours:
        return f"{hours} ч"
    return f"{remainder} мин"


async def _crm_ticket_for_user(db, ticket_id: int, user_id: int) -> dict | None:
    if not _crm_pilot(user_id):
        return None
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket.get("status") != "done":
        return None
    if int(ticket.get("admin_id") or 0) != user_id:
        return None
    return ticket


def _crm_summary(ticket_id: int, data: dict) -> str:
    comment = html.escape(data.get("comment") or "Не добавлен")
    report = html.escape(data.get("report") or "Не указан")
    return (
        f"📋 <b>Задача CRM по заявке #{ticket_id}</b>\n\n"
        f"<b>Заголовок:</b> {html.escape(data['title'])}\n"
        f"<b>Фактическое время:</b> {_duration_label(int(data['duration_minutes']))}\n"
        f"<b>Комментарий:</b> {comment}\n"
        f"<b>Отчёт о завершении:</b> {report}\n"
        "<b>Тип:</b> Внутренняя техническая задача\n\n"
        "Проверьте данные перед отправкой в тестовую CRM."
    )


def _admin_display_name(user) -> str:
    return user.full_name or user.first_name or user.username or str(user.id)


def _assignee_notice(ticket: dict, admin, intro: str) -> str:
    """Сообщение автору: кто и когда взял его заявку."""
    name = html.escape(_admin_display_name(admin))
    if admin.username:
        name += f" (@{html.escape(admin.username)})"
    raw = str(ticket.get("updated_at") or "")
    when = f"{raw[8:10]}.{raw[5:7]} в {raw[11:16]}" if len(raw) >= 16 else raw
    return (
        f"🔧 Заявка <b>#{ticket['id']}</b> {intro}\n"
        f"📝 {html.escape(ticket.get('title') or '')}\n"
        f"👤 Специалист: <b>{name}</b>\n"
        f"🕒 {when}"
    )


def _scope(user) -> set[str]:
    return admin_allowed_categories(user.id, user.username)


def _can_access_ticket(user, ticket: dict) -> bool:
    return can_access_ticket(
        user.id,
        user.username,
        ticket.get("department") or "system",
        ticket.get("category") or "other",
    )


def _queue_title(user) -> str:
    departments = admin_departments(user.id, user.username)
    if len(departments) == 1:
        return DEPARTMENT[next(iter(departments))]["queue_title"]
    return "Общая очередь"


async def _notify_other_admins_claimed(bot, db, ticket: dict, claimant) -> None:
    name = _admin_display_name(claimant)
    position = await db.queue_position(ticket["id"])
    text = (
        f"🔧 <b>Заявку #{ticket['id']} взял в работу</b>\n"
        f"Исполнитель: <b>{name}</b>\n\n"
        + ticket_card(ticket, position=position, show_user=True)
    )
    kb = claim_taken_kb(ticket["id"])
    admin_ids, admin_usernames = admin_identity_sets_for_ticket(
        ticket.get("department") or "system",
        ticket.get("category") or "other",
    )
    for aid in await db.admin_recipient_ids(admin_ids, admin_usernames):
        if aid == claimant.id:
            continue
        try:
            await bot.send_message(aid, text, reply_markup=kb)
        except Exception as exc:
            log.warning("Не удалось уведомить админа %s о взятии заявки: %s", aid, exc)

async def _queue_for_kind(
    db,
    kind: str,
    *,
    admin_id: int | None = None,
    categories: set[str] | None = None,
) -> tuple[list[dict], str]:
    if kind in ("all", "refresh"):
        return await db.list_queue(categories=categories), "Очередь заявок"
    if kind == "critical":
        return [
            t
            for t in await db.list_queue(categories=categories)
            if t["priority"] == "critical"
        ], "Критичные заявки"
    if kind == "mine":
        if admin_id is None:
            raise ValueError("Неизвестный фильтр")
        return await db.list_assigned(admin_id, categories), "Заявки на мне"
    if kind in ("new", "in_progress", "waiting"):
        return await db.list_queue(
            status=kind, categories=categories
        ), f"Статус: {STATUS[kind]['label']}"
    raise ValueError("Неизвестный фильтр")


async def _send_mine(message: Message, db) -> None:
    tickets = await db.list_assigned(message.from_user.id, _scope(message.from_user))
    current = tickets[:PAGE_SIZE]
    empty = (
        "👤 <b>Заявки на мне</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        "Сейчас на вас нет активных заявок."
    )
    text = (
        queue_list(current, title="Заявки на мне", total=len(tickets))
        if tickets
        else empty
    )
    await message.answer(
        text,
        reply_markup=queue_tickets_kb(current, page=0, kind="mine", total=len(tickets)),
    )

async def _send_archive(message: Message, db) -> None:
    tickets = await db.list_archive(categories=_scope(message.from_user))
    text = (
        f"🗄 <b>Архив задач</b>\nПоследние записи: <b>{len(tickets)}</b>"
        if tickets
        else "🗄 <b>Архив задач</b>\n\nАрхив пока пуст."
    )
    await message.answer(text, reply_markup=archive_tickets_kb(tickets))


@router.message(F.text == "🗄 Архив задач")
@router.message(Command("archive"))
async def show_archive(message: Message, db) -> None:
    if not _admin_only(message.from_user.id, message.from_user.username):
        await message.answer("Команда только для администраторов.")
        return
    await _send_archive(message, db)


@router.callback_query(F.data == "archive:refresh")
async def refresh_archive(callback: CallbackQuery, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    tickets = await db.list_archive(categories=_scope(callback.from_user))
    text = (
        f"🗄 <b>Архив задач</b>\nПоследние записи: <b>{len(tickets)}</b>"
        if tickets
        else "🗄 <b>Архив задач</b>\n\nАрхив пока пуст."
    )
    await callback.message.edit_text(text, reply_markup=archive_tickets_kb(tickets))
    await callback.answer("Архив обновлён")


@router.message(F.text == "👤 На мне")
@router.message(Command("mine"))
async def show_mine(message: Message, db) -> None:
    if not _admin_only(message.from_user.id, message.from_user.username):
        await message.answer("Команда только для администраторов.")
        return
    await _send_mine(message, db)


@router.message(F.text.in_(QUEUE_BUTTONS))
@router.message(Command("queue"))
async def show_queue(message: Message, db) -> None:
    if not _admin_only(message.from_user.id, message.from_user.username):
        await message.answer("Команда только для администраторов.")
        return
    tickets = await db.list_queue(categories=_scope(message.from_user))
    current = tickets[:PAGE_SIZE]
    await message.answer(
        queue_list(current, title=_queue_title(message.from_user), total=len(tickets)),
        reply_markup=queue_tickets_kb(current, page=0, kind="all", total=len(tickets)),
    )
    await message.answer("Фильтры:", reply_markup=queue_filter_kb())


@router.callback_query(F.data.startswith("queue:"))
async def filter_queue(callback: CallbackQuery, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    kind = callback.data.split(":", 1)[1]
    try:
        tickets, title = await _queue_for_kind(
            db,
            kind,
            admin_id=callback.from_user.id,
            categories=_scope(callback.from_user),
        )
    except ValueError:
        await callback.answer("Неизвестный фильтр")
        return
    current = tickets[:PAGE_SIZE]
    text = (
        queue_list(current, title=title, total=len(tickets))
        if tickets or kind != "mine"
        else (
            "👤 <b>Заявки на мне</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "Сейчас на вас нет активных заявок."
        )
    )
    await callback.message.edit_text(
        text,
        reply_markup=queue_tickets_kb(current, page=0, kind=kind, total=len(tickets)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("queue_page:"))
async def queue_page(callback: CallbackQuery, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    _, kind, raw_page = callback.data.split(":", 2)
    tickets, title = await _queue_for_kind(
        db,
        kind,
        admin_id=callback.from_user.id,
        categories=_scope(callback.from_user),
    )
    pages = max(1, (len(tickets) + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(max(0, int(raw_page)), pages - 1)
    start = page * PAGE_SIZE
    current = tickets[start : start + PAGE_SIZE]
    text = (
        queue_list(
            current, title=f"{title} · {page + 1}/{pages}", total=len(tickets), start=start
        )
        if tickets or kind != "mine"
        else (
            "👤 <b>Заявки на мне</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "Сейчас на вас нет активных заявок."
        )
    )
    await callback.message.edit_text(
        text,
        reply_markup=queue_tickets_kb(current, page=page, kind=kind, total=len(tickets)),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("claim_confirm:"))
async def confirm_claim(callback: CallbackQuery, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or not _can_access_ticket(callback.from_user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return
    if ticket["status"] != "new" or ticket.get("admin_id") is not None:
        await callback.answer("Заявку уже взял другой администратор", show_alert=True)
        return
    await callback.message.edit_text(
        f"Взять заявку <b>#{ticket_id}</b> в работу на себя?",
        reply_markup=confirm_claim_kb(ticket_id),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("claim:"))
async def claim_ticket(callback: CallbackQuery, db, bot) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    ticket_id = int(callback.data.split(":", 1)[1])
    user = callback.from_user
    ticket = await db.get_ticket(ticket_id)
    if not ticket or not _can_access_ticket(user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return
    await db.upsert_user(
        user.id, user.username, user.full_name or user.first_name or "Админ"
    )
    if not await db.claim_ticket(ticket_id, user.id):
        await callback.answer("Заявку уже взял другой администратор", show_alert=True)
        ticket = await db.get_ticket(ticket_id)
        if ticket:
            await callback.message.edit_text(
                ticket_card(
                    ticket,
                    position=await db.queue_position(ticket_id),
                    show_user=True,
                ),
                reply_markup=admin_ticket_kb(
                    ticket_id,
                    ticket["status"],
                    viewer_id=user.id,
                    assignee_id=ticket.get("admin_id"),
                ),
            )
        return

    ticket = await db.get_ticket(ticket_id)
    try:
        await bot.send_message(
            ticket["user_id"],
            _assignee_notice(ticket, user, "взята в работу"),
        )
    except Exception:
        pass

    await _notify_other_admins_claimed(bot, db, ticket, user)

    await callback.message.edit_text(
        ticket_card(ticket, position=await db.queue_position(ticket_id), show_user=True),
        reply_markup=admin_ticket_kb(
            ticket_id,
            "in_progress",
            viewer_id=user.id,
            assignee_id=user.id,
        ),
    )
    await callback.answer("Заявка назначена вам")


@router.callback_query(F.data.startswith("takeover:"))
async def takeover_ticket(callback: CallbackQuery, db, bot) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket or ticket["status"] in ("done", "cancelled"):
        await callback.answer("Заявка недоступна", show_alert=True)
        return
    if not _can_access_ticket(callback.from_user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return

    user = callback.from_user
    prev_admin_id = ticket.get("admin_id")
    if prev_admin_id == user.id:
        await callback.message.edit_text(
            ticket_card(
                ticket,
                position=await db.queue_position(ticket_id),
                show_user=True,
            ),
            reply_markup=admin_ticket_kb(
                ticket_id,
                ticket["status"],
                viewer_id=user.id,
                assignee_id=user.id,
            ),
        )
        await callback.answer("Уже ваша заявка")
        return

    await db.upsert_user(
        user.id, user.username, user.full_name or user.first_name or "Админ"
    )
    if not await db.reassign_ticket(ticket_id, user.id):
        await callback.answer("Не удалось перехватить", show_alert=True)
        return

    ticket = await db.get_ticket(ticket_id)
    name = _admin_display_name(user)

    if prev_admin_id and prev_admin_id != user.id:
        try:
            await bot.send_message(
                prev_admin_id,
                f"🔄 Заявку <b>#{ticket_id}</b> перехватил <b>{name}</b>.",
            )
        except Exception:
            pass

    try:
        await bot.send_message(
            ticket["user_id"],
            _assignee_notice(ticket, user, "передана другому специалисту"),
        )
    except Exception:
        pass

    await callback.message.edit_text(
        ticket_card(ticket, position=await db.queue_position(ticket_id), show_user=True),
        reply_markup=admin_ticket_kb(
            ticket_id,
            "in_progress",
            viewer_id=user.id,
            assignee_id=user.id,
        ),
    )
    await callback.answer("Заявка перехвачена")


@router.callback_query(F.data.startswith("claim_dismiss:"))
async def claim_dismiss(callback: CallbackQuery, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    ticket_id = callback.data.split(":", 1)[1]
    ticket = await db.get_ticket(int(ticket_id))
    if not ticket or not _can_access_ticket(callback.from_user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return
    await callback.message.edit_text(
        f"Ок. Заявка <b>#{ticket_id}</b> остаётся у текущего исполнителя."
    )
    await callback.answer()


@router.callback_query(F.data.startswith("st:"))
async def change_status(callback: CallbackQuery, db, bot) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return

    _, tid, status = callback.data.split(":", 2)
    ticket_id = int(tid)
    if status not in STATUS:
        await callback.answer("Ошибка статуса", show_alert=True)
        return

    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Не найдено", show_alert=True)
        return
    if not _can_access_ticket(callback.from_user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return

    if status == "in_progress" and ticket["status"] == "new":
        await callback.answer("Подтвердите взятие заявки новой кнопкой", show_alert=True)
        return

    if (
        ticket.get("admin_id")
        and ticket["admin_id"] != callback.from_user.id
        and ticket["status"] in ("in_progress", "waiting")
        and status != "new"
    ):
        await callback.answer(
            "Заявка у другого администратора — сначала перехватите",
            show_alert=True,
        )
        return

    await db.set_status(ticket_id, status, admin_id=callback.from_user.id)
    ticket = await db.get_ticket(ticket_id)
    position = await db.queue_position(ticket_id)
    st = STATUS[status]

    try:
        await bot.send_message(
            ticket["user_id"],
            f"{st['emoji']} Статус заявки <b>#{ticket_id}</b> → "
            f"<b>{st['label']}</b>\n\n"
            + ticket_card(ticket, position=position),
        )
    except Exception:
        pass

    await callback.message.edit_text(
        ticket_card(ticket, position=position, show_user=True),
        reply_markup=admin_ticket_kb(
            ticket_id,
            status,
            viewer_id=callback.from_user.id,
            assignee_id=ticket.get("admin_id"),
        ),
    )
    await callback.answer(f"{st['label']}")

    if status == "done" and _crm_pilot(callback.from_user.id):
        export = await db.get_crm_export(ticket_id)
        if not export or export.get("status") != "sent":
            await callback.message.answer(
                f"📤 Отправить закрытую заявку <b>#{ticket_id}</b> в CRM?",
                reply_markup=crm_offer_kb(ticket_id),
            )


@router.callback_query(F.data.startswith("crm_offer:"))
async def crm_offer(callback: CallbackQuery, state: FSMContext, db) -> None:
    try:
        _, tid, answer = callback.data.split(":", 2)
        ticket_id = int(tid)
    except (TypeError, ValueError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    ticket = await _crm_ticket_for_user(db, ticket_id, callback.from_user.id)
    if not ticket:
        await callback.answer("Выгрузка недоступна", show_alert=True)
        return
    if answer == "no":
        await state.clear()
        await callback.message.edit_text(
            f"Заявка <b>#{ticket_id}</b> закрыта без отправки в CRM."
        )
        await callback.answer()
        return
    if answer != "yes":
        await callback.answer("Некорректная команда", show_alert=True)
        return
    existing = await db.get_crm_export(ticket_id)
    if existing and existing.get("status") == "sent":
        await callback.answer("Эта задача уже отправлена в CRM", show_alert=True)
        return
    await state.clear()
    await state.set_state(CrmExport.title)
    await state.update_data(ticket_id=ticket_id, original_title=ticket["title"])
    await callback.message.edit_text(f"Готовим задачу CRM по заявке <b>#{ticket_id}</b>.")
    await callback.message.answer(
        "Задайте заголовок задачи или оставьте исходный:",
        reply_markup=crm_title_kb(),
    )
    await callback.answer()


@router.message(CrmExport.title, F.text)
async def crm_title(message: Message, state: FSMContext) -> None:
    if not _crm_pilot(message.from_user.id):
        await state.clear()
        return
    text = (message.text or "").strip()
    data = await state.get_data()
    if text == "Оставить исходный заголовок":
        text = str(data.get("original_title") or "").strip()
    if not text:
        await message.answer("Заголовок не может быть пустым.")
        return
    if len(text) > 255:
        await message.answer("Заголовок слишком длинный — максимум 255 символов.")
        return
    await state.update_data(title=text)
    await state.set_state(CrmExport.duration)
    await message.answer(
        "Сколько времени ушло на выполнение задачи?\n"
        "Например: <code>45</code>, <code>1ч 30м</code> или <code>2:15</code>.",
        reply_markup=cancel_kb(),
    )


@router.message(CrmExport.duration, F.text)
async def crm_duration(message: Message, state: FSMContext) -> None:
    if not _crm_pilot(message.from_user.id):
        await state.clear()
        return
    minutes = _parse_duration_minutes(message.text or "")
    if minutes is None:
        await message.answer(
            "Не удалось распознать время. Введите, например, "
            "<code>45</code>, <code>1ч 30м</code> или <code>2:15</code>."
        )
        return
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    await state.update_data(duration_minutes=minutes)
    await state.set_state(CrmExport.comment)
    await message.answer("Время сохранено.", reply_markup=remove_kb())
    await message.answer(
        "Хотите добавить комментарий к задаче?",
        reply_markup=crm_comment_choice_kb(ticket_id),
    )


async def _ask_crm_report(message: Message, state: FSMContext) -> None:
    await state.set_state(CrmExport.report)
    await message.answer(
        "Опишите отчёт о завершении работы или нажмите «Пропустить»:",
        reply_markup=crm_report_kb(),
    )


@router.callback_query(F.data.startswith("crm_comment:"))
async def crm_comment_choice(callback: CallbackQuery, state: FSMContext, db) -> None:
    try:
        _, tid, answer = callback.data.split(":", 2)
        ticket_id = int(tid)
    except (TypeError, ValueError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    ticket = await _crm_ticket_for_user(db, ticket_id, callback.from_user.id)
    data = await state.get_data()
    if not ticket or int(data.get("ticket_id") or 0) != ticket_id:
        await callback.answer("Сценарий устарел, начните заново", show_alert=True)
        return
    if answer == "cancel":
        await state.clear()
        await callback.message.edit_text("Отправка в CRM отменена.")
        await callback.message.answer(
            "Главное меню ниже 👇",
            reply_markup=main_menu(callback.from_user.id, callback.from_user.username),
        )
    elif answer == "yes":
        await state.update_data(expecting_comment=True)
        await callback.message.edit_text("Введите комментарий к задаче CRM:")
    elif answer == "no":
        await state.update_data(comment=None, expecting_comment=False)
        await callback.message.edit_text("Комментарий не добавляем.")
        await _ask_crm_report(callback.message, state)
    else:
        await callback.answer("Некорректная команда", show_alert=True)
        return
    await callback.answer()


@router.message(CrmExport.comment, F.text)
async def crm_comment(message: Message, state: FSMContext) -> None:
    if not _crm_pilot(message.from_user.id):
        await state.clear()
        return
    data = await state.get_data()
    if not data.get("expecting_comment"):
        await message.answer("Выберите «Да» или «Нет» кнопками выше.")
        return
    text = (message.text or "").strip()
    if not text:
        await message.answer("Комментарий не может быть пустым.")
        return
    if len(text) > 4000:
        await message.answer("Комментарий слишком длинный — максимум 4000 символов.")
        return
    await state.update_data(comment=text, expecting_comment=False)
    await _ask_crm_report(message, state)


@router.message(CrmExport.report, F.text)
async def crm_report(message: Message, state: FSMContext, db) -> None:
    if not _crm_pilot(message.from_user.id):
        await state.clear()
        return
    report = (message.text or "").strip()
    if report == "⏭ Пропустить":
        report = ""
    elif not report:
        await message.answer("Введите отчёт или нажмите «Пропустить».")
        return
    if len(report) > 8000:
        await message.answer("Отчёт слишком длинный — максимум 8000 символов.")
        return
    await state.update_data(report=report or None)
    data = await state.get_data()
    ticket_id = int(data["ticket_id"])
    ticket = await _crm_ticket_for_user(db, ticket_id, message.from_user.id)
    if not ticket:
        await state.clear()
        await message.answer(
            "Заявка больше недоступна для отправки.",
            reply_markup=main_menu(message.from_user.id, message.from_user.username),
        )
        return
    export = await db.upsert_crm_export(
        ticket_id=ticket_id,
        admin_id=message.from_user.id,
        title=str(data["title"]),
        duration_minutes=int(data["duration_minutes"]),
        comment=data.get("comment"),
        report=report or None,
    )
    await state.set_state(CrmExport.confirm)
    await message.answer("Данные сохранены.", reply_markup=remove_kb())
    await message.answer(
        _crm_summary(ticket_id, export),
        reply_markup=crm_confirm_kb(ticket_id),
    )


@router.callback_query(F.data.startswith("crm_edit:"))
async def crm_edit(callback: CallbackQuery, state: FSMContext, db) -> None:
    ticket_id = int(callback.data.split(":", 1)[1])
    ticket = await _crm_ticket_for_user(db, ticket_id, callback.from_user.id)
    export = await db.get_crm_export(ticket_id)
    if not ticket or (export and export.get("status") == "sent"):
        await callback.answer("Редактирование недоступно", show_alert=True)
        return
    await state.clear()
    await state.set_state(CrmExport.title)
    await state.update_data(ticket_id=ticket_id, original_title=ticket["title"])
    await callback.message.edit_text("Заполним данные заново.")
    await callback.message.answer(
        "Задайте заголовок задачи или оставьте исходный:",
        reply_markup=crm_title_kb(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crm_abort:"))
async def crm_abort(callback: CallbackQuery, state: FSMContext) -> None:
    if not _crm_pilot(callback.from_user.id):
        await callback.answer("Недоступно", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text("Отправка в CRM отменена. Заявка HelpDesk уже закрыта.")
    await callback.message.answer(
        "Главное меню ниже 👇",
        reply_markup=main_menu(callback.from_user.id, callback.from_user.username),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("crm_send:"))
async def crm_send(callback: CallbackQuery, state: FSMContext, db, crm_client) -> None:
    try:
        ticket_id = int(callback.data.split(":", 1)[1])
    except (TypeError, ValueError):
        await callback.answer("Некорректная команда", show_alert=True)
        return
    ticket = await _crm_ticket_for_user(db, ticket_id, callback.from_user.id)
    export = await db.get_crm_export(ticket_id)
    if not ticket or not export:
        await callback.answer("Данные отправки не найдены", show_alert=True)
        return
    if export.get("status") == "sent":
        crm_task_id = int(export["crm_task_id"])
        crm_task_url = str(export.get("crm_task_url") or "") or None
        link = (
            f'\n<a href="{html.escape(crm_task_url, quote=True)}">Открыть задачу в CRM</a>'
            if crm_task_url
            else ""
        )
        await callback.message.edit_text(
            f"✅ Задача CRM <b>#{crm_task_id}</b> уже создана и закрыта."
            f"\nТип: <b>Внутренняя техническая задача</b>{link}"
        )
        await callback.answer("Задача уже отправлена")
        return

    await state.clear()
    await callback.answer("Отправляю…")
    await callback.message.edit_text(
        f"⏳ Отправляю заявку <b>#{ticket_id}</b> в тестовую CRM…"
    )
    await db.mark_crm_export_attempt(ticket_id)
    payload = {
        "external_id": export["external_id"],
        "ticket_id": ticket_id,
        "telegram_user_id": callback.from_user.id,
        "title": export["title"],
        "duration_minutes": int(export["duration_minutes"]),
        "comment": export.get("comment") or "",
        "report": export.get("report") or "",
        "closed_at": ticket.get("closed_at") or ticket.get("updated_at"),
        "helpdesk_description": ticket.get("description") or "",
        "requester_name": ticket.get("full_name") or "",
        "requester_username": ticket.get("username") or "",
    }
    try:
        result = await crm_client.create_task(payload)
    except CrmIntegrationError as exc:
        error = str(exc)
        await db.mark_crm_export_failed(ticket_id, error)
        log.warning("CRM export failed for HelpDesk #%s: %s", ticket_id, error)
        await callback.message.edit_text(
            f"⚠️ Не удалось отправить заявку <b>#{ticket_id}</b> в CRM.\n"
            f"Причина: {html.escape(error)}\n\n"
            "Данные сохранены, повторная отправка не создаст дубль.",
            reply_markup=crm_retry_kb(ticket_id),
        )
        return

    crm_task_id = int(result["task_id"])
    crm_task_url = str(result.get("task_url") or "") or None
    await db.mark_crm_export_sent(ticket_id, crm_task_id, crm_task_url)
    link = (
        f'\n<a href="{html.escape(crm_task_url, quote=True)}">Открыть задачу в CRM</a>'
        if crm_task_url
        else ""
    )
    await callback.message.edit_text(
        f"✅ Задача CRM <b>#{crm_task_id}</b> создана и закрыта."
        f"\nТип: <b>Внутренняя техническая задача</b>{link}"
    )
    await callback.message.answer(
        "Готово.",
        reply_markup=main_menu(callback.from_user.id, callback.from_user.username),
    )


@router.message(F.text == "📈 Статистика")
@router.message(Command("stats"))
async def show_stats(message: Message, db) -> None:
    if not _admin_only(message.from_user.id, message.from_user.username):
        await message.answer("Команда только для администраторов.")
        return
    s = await db.stats(_scope(message.from_user))
    u = message.from_user
    await message.answer(stats_card(s), reply_markup=main_menu(u.id, u.username))


@router.message(F.text == "🔎 Поиск")
@router.message(Command("search"))
async def start_search(message: Message, state: FSMContext) -> None:
    if not _admin_only(message.from_user.id, message.from_user.username):
        await message.answer("Команда только для администраторов.")
        return
    await state.set_state(SearchTicket.waiting)
    await message.answer(
        "🔎 Введите номер заявки или текст для поиска:",
        reply_markup=cancel_kb(),
    )


@router.message(SearchTicket.waiting, F.text)
async def do_search(message: Message, state: FSMContext, db) -> None:
    u = message.from_user
    if not _admin_only(u.id, u.username):
        await state.clear()
        return
    q = (message.text or "").strip()
    if q == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id, u.username))
        return
    results = await db.search(q, categories=_scope(u))
    await state.clear()
    if not results:
        await message.answer(
            "Ничего не найдено.",
            reply_markup=main_menu(u.id, u.username),
        )
        return
    await message.answer(
        queue_list(results, title=f"Найдено: «{q}»"),
        reply_markup=queue_tickets_kb(results),
    )
    await message.answer("Готово.", reply_markup=main_menu(u.id, u.username))


@router.callback_query(F.data.startswith("acomment:"))
async def start_admin_comment(callback: CallbackQuery, state: FSMContext, db) -> None:
    if not _admin_only(callback.from_user.id, callback.from_user.username):
        await callback.answer("Только для администраторов", show_alert=True)
        return
    ticket_id = int(callback.data.split(":")[1])
    ticket = await db.get_ticket(ticket_id)
    if not ticket:
        await callback.answer("Не найдено", show_alert=True)
        return
    if not _can_access_ticket(callback.from_user, ticket):
        await callback.answer("Нет доступа к этому направлению", show_alert=True)
        return
    await state.set_state(AdminComment.waiting)
    await state.update_data(ticket_id=ticket_id)
    await callback.message.answer(
        f"💬 Сообщение клиенту по заявке <b>#{ticket_id}</b>:",
        reply_markup=cancel_kb(),
    )
    await callback.answer()


@router.message(AdminComment.waiting, F.text)
async def save_admin_comment(message: Message, state: FSMContext, db, bot) -> None:
    u = message.from_user
    if not _admin_only(u.id, u.username):
        await state.clear()
        return
    text = (message.text or "").strip()
    if text == "❌ Отмена":
        await state.clear()
        await message.answer("Отменено.", reply_markup=main_menu(u.id, u.username))
        return

    data = await state.get_data()
    ticket_id = data["ticket_id"]
    ticket = await db.get_ticket(ticket_id)
    if not ticket or not _can_access_ticket(message.from_user, ticket):
        await state.clear()
        await message.answer(
            "Нет доступа к этой заявке.",
            reply_markup=main_menu(u.id, u.username),
        )
        return
    await db.add_comment(ticket_id, message.from_user.id, text, is_admin=True)
    await db.set_admin_note(ticket_id, text, message.from_user.id)
    ticket = await db.get_ticket(ticket_id)
    await state.clear()

    await message.answer(
        f"Отправлено клиенту по #{ticket_id}.",
        reply_markup=main_menu(u.id, u.username),
    )
    try:
        await bot.send_message(
            ticket["user_id"],
            f"💬 <b>Сообщение от поддержки</b> по заявке <b>#{ticket_id}</b>:\n\n"
            f"{text}",
            reply_markup=client_reply_kb(ticket_id),
        )
    except Exception:
        await message.answer("⚠ Не удалось доставить сообщение клиенту (он мог заблокировать бота).")
