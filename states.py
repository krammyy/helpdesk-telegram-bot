"""FSM-состояния."""

from aiogram.fsm.state import State, StatesGroup


class CreateTicket(StatesGroup):
    department = State()
    category = State()
    title = State()
    description = State()
    screenshots = State()
    location = State()
    priority = State()


class CommentTicket(StatesGroup):
    waiting = State()


class AdminComment(StatesGroup):
    waiting = State()


class SearchTicket(StatesGroup):
    waiting = State()


class CrmExport(StatesGroup):
    title = State()
    duration = State()
    comment = State()
    report = State()
    confirm = State()
