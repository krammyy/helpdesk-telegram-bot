"""Inline и reply-клавиатуры."""

from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

from config import (
    CATEGORY,
    DEPARTMENT,
    PRIORITY,
    STATUS,
    admin_departments,
    is_admin,
)

PAGE_SIZE = 8


ALL_QUEUE_BUTTON = "🛠 Общая очередь"


def queue_button_text(user_id: int) -> str:
    departments = admin_departments(user_id)
    if len(departments) == 1:
        return DEPARTMENT[next(iter(departments))]["queue_button"]
    return ALL_QUEUE_BUTTON


QUEUE_BUTTONS = {ALL_QUEUE_BUTTON} | {
    value["queue_button"] for value in DEPARTMENT.values()
}


def main_menu(user_id: int) -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="📝 Новая заявка")],
        [KeyboardButton(text="📂 Мои заявки"), KeyboardButton(text="ℹ️ Помощь")],
    ]
    if is_admin(user_id):
        rows.append(
            [
                KeyboardButton(text=queue_button_text(user_id)),
                KeyboardButton(text="👤 На мне"),
            ]
        )
        rows.append(
            [KeyboardButton(text="📈 Статистика"), KeyboardButton(text="🔎 Поиск")]
        )
        rows.append([KeyboardButton(text="🗄 Архив задач")])
    return ReplyKeyboardMarkup(
        keyboard=rows,
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Выберите действие",
    )


def cancel_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Введите данные или отмените действие",
    )


def remove_kb() -> ReplyKeyboardRemove:
    return ReplyKeyboardRemove()


def department_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text=f"{value['emoji']} {value['label']}",
                    callback_data=f"dept:{key}",
                )
            ]
            for key, value in DEPARTMENT.items()
        ]
        + [[InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")]]
    )


def categories_kb(department: str) -> InlineKeyboardMarkup:
    buttons = [
        InlineKeyboardButton(
            text=f"{v['emoji']} {v['label']}",
            callback_data=f"cat:{k}",
        )
        for k, v in CATEGORY.items()
        if v["department"] == department
    ]
    rows = [buttons[i : i + 2] for i in range(0, len(buttons), 2)]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def priority_kb() -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{v['emoji']} {v['label']}",
                callback_data=f"prio:{k}",
            )
        ]
        for k, v in PRIORITY.items()
    ]
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def priority_for_ticket_kb(ticket_id: int) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{v['emoji']} {v['label']}",
                callback_data=f"setprio:{ticket_id}:{k}",
            )
        ]
        for k, v in PRIORITY.items()
    ]
    rows.append(
        [InlineKeyboardButton(text="« Назад", callback_data=f"ticket:{ticket_id}")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_location_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="⏭ Пропустить", callback_data="loc:skip")],
            [InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")],
        ]
    )


def screenshots_kb(has_screenshots: bool = False) -> InlineKeyboardMarkup:
    rows = []
    if has_screenshots:
        rows.append([InlineKeyboardButton(text="✅ Готово", callback_data="screens:done")])
    rows.append([InlineKeyboardButton(text="⏭ Без скриншотов", callback_data="screens:skip")])
    rows.append([InlineKeyboardButton(text="❌ Отмена", callback_data="cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_ticket_kb(ticket_id: int, status: str) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                text="🔄 Обновить", callback_data=f"ticket:{ticket_id}"
            ),
            InlineKeyboardButton(
                text="⚡ Срочность", callback_data=f"prio_menu:{ticket_id}"
            ),
        ],
        [
            InlineKeyboardButton(
                text="💬 Комментарий", callback_data=f"ccomment:{ticket_id}"
            ),
            InlineKeyboardButton(
                text="📎 Скриншоты", callback_data=f"attachments:{ticket_id}"
            ),
        ],
    ]
    if status not in ("done", "cancelled"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="❎ Отменить заявку", callback_data=f"cancel_ticket:{ticket_id}"
                )
            ]
        )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def client_reply_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Кнопка быстрого ответа на сообщение специалиста по заявке."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="💬 Ответить специалисту",
                    callback_data=f"ccomment:{ticket_id}",
                )
            ]
        ]
    )


def admin_ticket_kb(
    ticket_id: int,
    status: str,
    *,
    viewer_id: int | None = None,
    assignee_id: int | None = None,
) -> InlineKeyboardMarkup:
    foreign = (
        assignee_id is not None
        and viewer_id is not None
        and int(assignee_id) != int(viewer_id)
        and status in ("in_progress", "waiting")
    )
    if foreign:
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="🔄 Перехватить задачу",
                        callback_data=f"takeover:{ticket_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        text="📎 Скриншоты", callback_data=f"attachments:{ticket_id}"
                    )
                ],
                [InlineKeyboardButton(text="« Назад", callback_data="queue:refresh")],
            ]
        )

    rows: list[list[InlineKeyboardButton]] = []
    if status == "new":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔧 Взять в работу", callback_data=f"claim_confirm:{ticket_id}"
                )
            ]
        )
    if status == "in_progress":
        rows.append(
            [
                InlineKeyboardButton(
                    text="⏳ Ждёт клиента", callback_data=f"st:{ticket_id}:waiting"
                ),
                InlineKeyboardButton(
                    text="✅ Готово", callback_data=f"st:{ticket_id}:done"
                ),
            ]
        )
    if status == "waiting":
        rows.append(
            [
                InlineKeyboardButton(
                    text="🔧 Снова в работу", callback_data=f"st:{ticket_id}:in_progress"
                ),
                InlineKeyboardButton(
                    text="✅ Готово", callback_data=f"st:{ticket_id}:done"
                ),
            ]
        )
    if status not in ("done", "cancelled"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="⚡ Срочность", callback_data=f"prio_menu:{ticket_id}"
                ),
                InlineKeyboardButton(
                    text="💬 Клиенту", callback_data=f"acomment:{ticket_id}"
                ),
            ]
        )
        rows.append(
            [
                InlineKeyboardButton(
                    text="❎ Отклонить", callback_data=f"st:{ticket_id}:cancelled"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="📎 Скриншоты", callback_data=f"attachments:{ticket_id}")]
    )
    if status in ("done", "cancelled"):
        rows.append(
            [
                InlineKeyboardButton(
                    text="🆕 Открыть снова", callback_data=f"st:{ticket_id}:new"
                )
            ]
        )
    rows.append(
        [InlineKeyboardButton(text="« К очереди", callback_data="queue:refresh")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def queue_filter_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📋 Все активные", callback_data="queue:all"),
                InlineKeyboardButton(text="🆕 Новые", callback_data="queue:new"),
            ],
            [
                InlineKeyboardButton(
                    text="🔧 В работе", callback_data="queue:in_progress"
                ),
                InlineKeyboardButton(text="⏳ Ожидают", callback_data="queue:waiting"),
            ],
            [
                InlineKeyboardButton(
                    text="🔴 Критичные", callback_data="queue:critical"
                ),
                InlineKeyboardButton(text="👤 На мне", callback_data="queue:mine"),
            ],
        ]
    )


def queue_tickets_kb(
    tickets: list[dict], *, page: int = 0, kind: str = "all", total: int | None = None
) -> InlineKeyboardMarkup:
    rows = []
    for t in tickets:
        st = STATUS.get(t["status"], STATUS["new"])
        pri = PRIORITY.get(t["priority"], PRIORITY["normal"])
        mark = ""
        if t.get("status") == "in_progress":
            who = (t.get("admin_full_name") or t.get("admin_username") or "").strip()
            mark = f" · 🔧{(' ' + who[:12]) if who else ''}"
        elif t.get("status") == "waiting":
            mark = " · ⏳"
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"{st['emoji']} {pri['emoji']} #{t['id']} · {t['title'][:22]}{mark}",
                    callback_data=f"ticket:{t['id']}",
                )
            ]
        )
    total = len(tickets) if total is None else total
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"queue_page:{kind}:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        rest = total - (page + 1) * PAGE_SIZE
        nav.append(
            InlineKeyboardButton(text=f"Ещё {rest} ▶️", callback_data=f"queue_page:{kind}:{page + 1}")
        )
    if nav:
        rows.append(nav)
    rows.append([InlineKeyboardButton(text="🔄 Обновить", callback_data=f"queue_page:{kind}:{page}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def user_tickets_kb(
    tickets: list[dict], *, page: int = 0, total: int | None = None
) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{STATUS.get(t['status'], STATUS['new'])['emoji']} "
                f"{PRIORITY.get(t['priority'], PRIORITY['normal'])['emoji']} "
                f"#{t['id']} · {t['title'][:28]}",
                callback_data=f"ticket:{t['id']}",
            )
        ]
        for t in tickets
    ]
    total = len(tickets) if total is None else total
    nav: list[InlineKeyboardButton] = []
    if page > 0:
        nav.append(InlineKeyboardButton(text="◀️", callback_data=f"my_page:{page - 1}"))
    if (page + 1) * PAGE_SIZE < total:
        nav.append(InlineKeyboardButton(text="▶️", callback_data=f"my_page:{page + 1}"))
    if nav:
        rows.append(nav)
    if not rows:
        rows = [[InlineKeyboardButton(text="📝 Создать заявку", callback_data="new")]]
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_claim_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Да, взять", callback_data=f"claim:{ticket_id}"),
                InlineKeyboardButton(text="Нет", callback_data=f"ticket:{ticket_id}"),
            ]
        ]
    )


def claim_taken_kb(ticket_id: int) -> InlineKeyboardMarkup:
    """Уведомление другим админам: перехватить или закрыть."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Перехватить задачу",
                    callback_data=f"takeover:{ticket_id}",
                )
            ],
            [
                InlineKeyboardButton(
                    text="« Назад", callback_data=f"claim_dismiss:{ticket_id}"
                )
            ],
        ]
    )


def archive_tickets_kb(tickets: list[dict]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                text=f"{STATUS.get(t['status'], STATUS['done'])['emoji']} "
                f"#{t['id']} · {t['title'][:32]}",
                callback_data=f"ticket:{t['id']}",
            )
        ]
        for t in tickets[:25]
    ]
    rows.append(
        [InlineKeyboardButton(text="🔄 Обновить архив", callback_data="archive:refresh")]
    )
    return InlineKeyboardMarkup(inline_keyboard=rows)


def confirm_cancel_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да, отменить", callback_data=f"confirm_cancel:{ticket_id}"
                ),
                InlineKeyboardButton(
                    text="Нет", callback_data=f"ticket:{ticket_id}"
                ),
            ]
        ]
    )


def crm_offer_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="✅ Да, отправить", callback_data=f"crm_offer:{ticket_id}:yes"
                ),
                InlineKeyboardButton(
                    text="Нет", callback_data=f"crm_offer:{ticket_id}:no"
                ),
            ]
        ]
    )


def crm_title_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="Оставить исходный заголовок")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Введите заголовок задачи",
    )


def crm_comment_choice_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Да", callback_data=f"crm_comment:{ticket_id}:yes"
                ),
                InlineKeyboardButton(
                    text="Нет", callback_data=f"crm_comment:{ticket_id}:no"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"crm_comment:{ticket_id}:cancel"
                )
            ],
        ]
    )


def crm_report_kb() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="⏭ Пропустить")],
            [KeyboardButton(text="❌ Отмена")],
        ],
        resize_keyboard=True,
        is_persistent=True,
        input_field_placeholder="Опишите выполненную работу",
    )


def crm_confirm_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Отправить в CRM", callback_data=f"crm_send:{ticket_id}"
                )
            ],
            [
                InlineKeyboardButton(
                    text="✏️ Заполнить заново", callback_data=f"crm_edit:{ticket_id}"
                ),
                InlineKeyboardButton(
                    text="❌ Отмена", callback_data=f"crm_abort:{ticket_id}"
                ),
            ],
        ]
    )


def crm_retry_kb(ticket_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="🔄 Повторить отправку", callback_data=f"crm_send:{ticket_id}"
                )
            ]
        ]
    )
