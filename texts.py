"""Красивые шаблоны сообщений."""

from __future__ import annotations

from html import escape
from typing import Any

from config import CATEGORY, DEPARTMENT, PRIORITY, STATUS


def _user_line(ticket: dict[str, Any]) -> str:
    name = escape(ticket.get("full_name") or "—")
    uname = ticket.get("username")
    if uname:
        return f"{name} (@{escape(uname)})"
    return name


def _admin_line(ticket: dict[str, Any]) -> str | None:
    if not ticket.get("admin_id"):
        return None
    name = escape(ticket.get("admin_full_name") or "администратор")
    uname = ticket.get("admin_username")
    if uname:
        return f"{name} (@{escape(uname)})"
    return name


def ticket_card(
    ticket: dict[str, Any],
    *,
    position: int | None = None,
    show_user: bool = False,
    comments: list[dict[str, Any]] | None = None,
) -> str:
    cat = CATEGORY.get(ticket["category"], CATEGORY["other"])
    department = DEPARTMENT.get(ticket.get("department") or "system", DEPARTMENT["system"])
    pri = PRIORITY.get(ticket["priority"], PRIORITY["normal"])
    st = STATUS.get(ticket["status"], STATUS["new"])

    lines = [
        f"🎫 <b>Заявка #{ticket['id']}</b>",
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄",
        f"{st['emoji']} <b>Статус:</b> {st['label']}",
        f"{pri['emoji']} <b>Срочность:</b> {pri['label']}",
        f"{department['emoji']} <b>Направление:</b> {department['label']}",
        f"{cat['emoji']} <b>Категория:</b> {cat['label']}",
    ]
    if position is not None:
        lines.append(f"📊 <b>Место в очереди:</b> {position}")
    if show_user:
        lines.append(f"👤 <b>Клиент:</b> {_user_line(ticket)}")
    admin_line = _admin_line(ticket)
    if show_user and admin_line and ticket["status"] in ("in_progress", "waiting", "done"):
        lines.append(f"🔧 <b>В работе у:</b> {admin_line}")
    if ticket.get("location"):
        lines.append(f"📍 <b>Место:</b> {escape(ticket['location'])}")
    if ticket.get("attachment_count"):
        lines.append(f"📎 <b>Скриншотов:</b> {ticket['attachment_count']}")

    lines += [
        "",
        f"📌 <b>{escape(ticket['title'])}</b>",
        f"<i>{escape(ticket['description'])}</i>",
        "",
        f"🕒 Создана: <code>{ticket['created_at']}</code> ",
    ]
    if ticket.get("updated_at") and ticket["updated_at"] != ticket["created_at"]:
        lines.append(
            f"🔄 Обновлена: <code>{ticket['updated_at']}</code> "
        )
    if ticket.get("admin_note"):
        lines += ["", f"💬 <b>Комментарий поддержки:</b>\n{escape(ticket['admin_note'])}"]

    if comments:
        lines += ["", "🗒 <b>Переписка:</b>"]
        for c in comments[-5:]:
            who = "Поддержка" if c["is_admin"] else "Клиент"
            lines.append(f"• <b>{who}</b>: {escape(c['text'])}")

    return "\n".join(lines)


def queue_list(
    tickets: list[dict[str, Any]],
    title: str = "Очередь заявок",
    *,
    total: int | None = None,
    start: int = 0,
) -> str:
    """Страница очереди; total — размер всей очереди, start — смещение страницы."""
    if not tickets:
        return (
            f"📭 <b>{escape(title)}</b>\n"
            "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
            "Сейчас активных заявок нет.\nОтличная работа! ✨"
        )
    total = len(tickets) if total is None else total
    count = f"{total} шт."
    if total > len(tickets):
        shown = f"{start + 1}" if len(tickets) == 1 else f"{start + 1}–{start + len(tickets)}"
        count = f"{shown} из {total}"
    lines = [f"📋 <b>{escape(title)}</b>  ·  {count}", "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄"]
    for i, t in enumerate(tickets, start=start + 1):
        pri = PRIORITY.get(t["priority"], PRIORITY["normal"])
        st = STATUS.get(t["status"], STATUS["new"])
        cat = CATEGORY.get(t["category"], CATEGORY["other"])
        name = escape((t.get("full_name") or "")[:24])
        title_s = escape(t["title"][:40])
        block = (
            f"<b>{i}.</b> {pri['emoji']} #{t['id']} {st['emoji']} {cat['emoji']}\n"
            f"    {title_s}\n"
            f"    👤 {name}"
        )
        if t.get("status") in ("in_progress", "waiting") and t.get("admin_id"):
            admin_name = escape(
                (t.get("admin_full_name") or t.get("admin_username") or "админ")[:24]
            )
            block += f"\n    🔧 <b>в работе:</b> {admin_name}"
        lines.append(block)
    rest = total - start - len(tickets)
    if rest > 0:
        lines.append("┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄")
        lines.append(f"➡️ Ещё <b>{rest}</b> на следующей странице — кнопка «Ещё ▶️» ниже")
    return "\n".join(lines)


def stats_card(s: dict[str, int]) -> str:
    return (
        "📈 <b>Статистика Helpdesk</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"🆕 Новые: <b>{s.get('new_cnt', 0)}</b>\n"
        f"🔧 В работе: <b>{s.get('in_progress_cnt', 0)}</b>\n"
        f"⏳ Ждут ответа: <b>{s.get('waiting_cnt', 0)}</b>\n"
        f"🔴 Критичных в очереди: <b>{s.get('critical_cnt', 0)}</b>\n"
        f"✅ Закрыто: <b>{s.get('done_cnt', 0)}</b>\n"
        f"❎ Отменено: <b>{s.get('cancelled_cnt', 0)}</b>\n"
        f"📦 Всего заявок: <b>{s.get('total', 0)}</b>"
    )


def welcome(name: str, admin: bool) -> str:
    safe = escape(name)
    base = (
        f"👋 Привет, <b>{safe}</b>!\n\n"
        "Я бот <b>Helpdesk</b> — принимаю заявки в службу поддержки.\n\n"
        "Что умею:\n"
        "• принять описание проблемы\n"
        "• выдать номер и место в очереди\n"
        "• учесть срочность\n"
        "• показать статус вашей заявки\n"
    )
    if admin:
        base += (
            "\n🛠 <b>Режим администратора</b>\n"
            "Вам доступны очередь, «На мне», смена статусов, статистика и поиск."
        )
    return base


def ticket_created(ticket_id: int, position: int | None, priority_key: str) -> str:
    pri = PRIORITY[priority_key]
    pos = f"№ {position}" if position else "—"
    return (
        "✅ <b>Заявка принята!</b>\n"
        "┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄\n"
        f"🎫 Номер: <b>#{ticket_id}</b>\n"
        f"📊 Место в очереди: <b>{pos}</b>\n"
        f"{pri['emoji']} Срочность: <b>{pri['label']}</b>\n\n"
        "Служба поддержки увидит её в общей очереди.\n"
        "Статус можно смотреть в «Мои заявки»."
    )
