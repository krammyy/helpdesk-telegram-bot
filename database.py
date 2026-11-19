"""Асинхронная SQLite-база заявок."""

from __future__ import annotations

import aiosqlite
import uuid
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from config import CATEGORY, DB_PATH, PRIORITY, TIMEZONE_NAME

TZ = ZoneInfo(TIMEZONE_NAME)


def _now() -> str:
    """Текущее время в настроенном часовом поясе."""
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str | None = None) -> None:
        self.path = str(path or DB_PATH)

    async def connect(self) -> None:
        self.db = await aiosqlite.connect(self.path)
        self.db.row_factory = aiosqlite.Row
        await self.db.execute("PRAGMA foreign_keys = ON")
        await self._migrate()

    async def close(self) -> None:
        await self.db.close()

    async def _migrate(self) -> None:
        await self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS meta (
                key   TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS users (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tickets (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER NOT NULL,
                department      TEXT NOT NULL DEFAULT 'system',
                category        TEXT NOT NULL DEFAULT 'other',
                title           TEXT NOT NULL,
                description     TEXT NOT NULL,
                priority        TEXT NOT NULL DEFAULT 'normal',
                status          TEXT NOT NULL DEFAULT 'new',
                admin_id        INTEGER,
                admin_note      TEXT,
                location        TEXT,
                created_at      TEXT NOT NULL,
                updated_at      TEXT NOT NULL,
                closed_at       TEXT,
                FOREIGN KEY (user_id) REFERENCES users(user_id)
            );

            CREATE TABLE IF NOT EXISTS ticket_comments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                author_id   INTEGER NOT NULL,
                is_admin    INTEGER NOT NULL DEFAULT 0,
                text        TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS ticket_attachments (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                ticket_id   INTEGER NOT NULL,
                file_id     TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS crm_exports (
                ticket_id        INTEGER PRIMARY KEY,
                external_id      TEXT NOT NULL UNIQUE,
                admin_id         INTEGER NOT NULL,
                title            TEXT NOT NULL,
                duration_minutes INTEGER NOT NULL,
                comment          TEXT,
                report           TEXT,
                status           TEXT NOT NULL DEFAULT 'draft',
                crm_task_id      INTEGER,
                crm_task_url     TEXT,
                attempts         INTEGER NOT NULL DEFAULT 0,
                last_error       TEXT,
                created_at       TEXT NOT NULL,
                updated_at       TEXT NOT NULL,
                FOREIGN KEY (ticket_id) REFERENCES tickets(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_tickets_status ON tickets(status);
            CREATE INDEX IF NOT EXISTS idx_tickets_user ON tickets(user_id);
            CREATE INDEX IF NOT EXISTS idx_tickets_priority ON tickets(priority);
            """
        )
        await self.db.commit()
        columns = {
            str(row[1]) for row in await (await self.db.execute("PRAGMA table_info(tickets)")).fetchall()
        }
        if "department" not in columns:
            await self.db.execute(
                "ALTER TABLE tickets ADD COLUMN department TEXT NOT NULL DEFAULT 'system'"
            )
            await self.db.execute(
                "UPDATE tickets SET department = 'onec' "
                "WHERE category IN ('onec', 'development')"
            )
            await self.db.commit()
        await self.db.execute(
            "CREATE INDEX IF NOT EXISTS idx_tickets_department ON tickets(department)"
        )

        await self.db.execute(
            "UPDATE tickets SET department = 'crm' "
            "WHERE category IN ('crm', 'site') AND department != 'crm'"
        )
        await self.db.commit()
        await self._migrate_legacy_timezone()

    async def _migrate_legacy_timezone(self) -> None:
        """Переводит старые UTC-метки в настроенный часовой пояс."""
        cur = await self.db.execute(
            "SELECT value FROM meta WHERE key = 'timezone'"
        )
        row = await cur.fetchone()
        if row and row[0] == TIMEZONE_NAME:
            return


        offset = datetime.now(TZ).utcoffset() or timedelta()
        hours = int(offset.total_seconds() // 3600)
        shift = f"+{hours} hours" if hours >= 0 else f"{hours} hours"

        await self.db.executescript(
            f"""
            UPDATE tickets
            SET created_at = datetime(created_at, '{shift}'),
                updated_at = datetime(updated_at, '{shift}'),
                closed_at = CASE
                    WHEN closed_at IS NULL OR closed_at = '' THEN closed_at
                    ELSE datetime(closed_at, '{shift}')
                END;

            UPDATE ticket_comments
            SET created_at = datetime(created_at, '{shift}');

            UPDATE ticket_attachments
            SET created_at = datetime(created_at, '{shift}');

            UPDATE users
            SET created_at = datetime(created_at, '{shift}');

            INSERT INTO meta(key, value) VALUES('timezone', '{TIMEZONE_NAME}')
            ON CONFLICT(key) DO UPDATE SET value = excluded.value;
            """
        )
        await self.db.commit()

    async def upsert_user(self, user_id: int, username: str | None, full_name: str) -> None:
        await self.db.execute(
            """
            INSERT INTO users (user_id, username, full_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username = excluded.username,
                full_name = excluded.full_name
            """,
            (user_id, username, full_name, _now()),
        )
        await self.db.commit()

    async def create_ticket(
        self,
        user_id: int,
        department: str,
        category: str,
        title: str,
        description: str,
        priority: str = "normal",
        location: str | None = None,
    ) -> int:
        now = _now()
        cur = await self.db.execute(
            """
            INSERT INTO tickets
                (user_id, department, category, title, description, priority, status,
                 location, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, 'new', ?, ?, ?)
            """,
            (
                user_id,
                department,
                category,
                title,
                description,
                priority,
                location,
                now,
                now,
            ),
        )
        await self.db.commit()
        return int(cur.lastrowid)

    async def get_ticket(self, ticket_id: int) -> dict[str, Any] | None:
        cur = await self.db.execute(
            """
            SELECT t.*, u.full_name, u.username,
                   au.full_name AS admin_full_name,
                   au.username AS admin_username,
                   (SELECT COUNT(*) FROM ticket_attachments a WHERE a.ticket_id = t.id)
                       AS attachment_count
            FROM tickets t
            JOIN users u ON u.user_id = t.user_id
            LEFT JOIN users au ON au.user_id = t.admin_id
            WHERE t.id = ?
            """,
            (ticket_id,),
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def add_attachments(self, ticket_id: int, file_ids: list[str]) -> None:
        if not file_ids:
            return
        await self.db.executemany(
            """
            INSERT INTO ticket_attachments (ticket_id, file_id, created_at)
            VALUES (?, ?, ?)
            """,
            [(ticket_id, file_id, _now()) for file_id in file_ids],
        )
        await self.db.commit()

    async def get_attachments(self, ticket_id: int) -> list[str]:
        cur = await self.db.execute(
            "SELECT file_id FROM ticket_attachments WHERE ticket_id = ? ORDER BY id",
            (ticket_id,),
        )
        return [str(row[0]) for row in await cur.fetchall()]

    async def list_user_tickets(
        self, user_id: int, active_only: bool = True
    ) -> list[dict[str, Any]]:
        if active_only:
            sql = """
                SELECT * FROM tickets
                WHERE user_id = ? AND status NOT IN ('done', 'cancelled')
                ORDER BY id DESC
            """
        else:
            sql = "SELECT * FROM tickets WHERE user_id = ? ORDER BY id DESC LIMIT 20"
        cur = await self.db.execute(sql, (user_id,))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_queue(
        self,
        status: str | None = None,
        categories: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        """Очередь: сначала срочные, затем старые."""
        clauses: list[str] = []
        params: list[Any] = []
        if status:
            clauses.append("t.status = ?")
            params.append(status)
        else:
            clauses.append("t.status IN ('new', 'in_progress', 'waiting')")
        if categories is not None:
            if not categories:
                return []
            marks = ",".join("?" for _ in categories)
            clauses.append(f"t.category IN ({marks})")
            params.extend(sorted(categories))
        sql = f"""
                SELECT t.*, u.full_name, u.username,
                       au.full_name AS admin_full_name,
                       au.username AS admin_username
                FROM tickets t
                JOIN users u ON u.user_id = t.user_id
                LEFT JOIN users au ON au.user_id = t.admin_id
                WHERE {' AND '.join(clauses)}
                ORDER BY
                    CASE t.priority
                        WHEN 'critical' THEN 4
                        WHEN 'high' THEN 3
                        WHEN 'normal' THEN 2
                        ELSE 1
                    END DESC,
                    t.created_at ASC
            """
        cur = await self.db.execute(sql, tuple(params))
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_archive(
        self, limit: int = 25, categories: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Последние завершённые и отменённые заявки для администраторов."""
        clauses = ["t.status IN ('done', 'cancelled')"]
        params: list[Any] = []
        if categories is not None:
            if not categories:
                return []
            marks = ",".join("?" for _ in categories)
            clauses.append(f"t.category IN ({marks})")
            params.extend(sorted(categories))
        params.append(limit)
        cur = await self.db.execute(
            f"""
            SELECT t.*, u.full_name, u.username,
                   au.full_name AS admin_full_name,
                   au.username AS admin_username
            FROM tickets t
            JOIN users u ON u.user_id = t.user_id
            LEFT JOIN users au ON au.user_id = t.admin_id
            WHERE {' AND '.join(clauses)}
            ORDER BY COALESCE(t.closed_at, t.updated_at) DESC, t.id DESC
            LIMIT ?
            """,
            tuple(params),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def list_assigned(
        self, admin_id: int, categories: set[str] | None = None
    ) -> list[dict[str, Any]]:
        """Активные заявки, назначенные конкретному администратору."""
        clauses = [
            "t.admin_id = ?",
            "t.status IN ('in_progress', 'waiting')",
        ]
        params: list[Any] = [admin_id]
        if categories is not None:
            if not categories:
                return []
            marks = ",".join("?" for _ in categories)
            clauses.append(f"t.category IN ({marks})")
            params.extend(sorted(categories))
        cur = await self.db.execute(
            f"""
            SELECT t.*, u.full_name, u.username,
                   au.full_name AS admin_full_name,
                   au.username AS admin_username
            FROM tickets t
            JOIN users u ON u.user_id = t.user_id
            LEFT JOIN users au ON au.user_id = t.admin_id
            WHERE {' AND '.join(clauses)}
            ORDER BY
                CASE t.priority
                    WHEN 'critical' THEN 4
                    WHEN 'high' THEN 3
                    WHEN 'normal' THEN 2
                    ELSE 1
                END DESC,
                t.updated_at DESC,
                t.created_at ASC
            """,
            tuple(params),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def claim_ticket(self, ticket_id: int, admin_id: int) -> bool:
        """Атомарно назначает новую заявку одному администратору."""
        now = _now()
        cur = await self.db.execute(
            """
            UPDATE tickets
            SET status = 'in_progress', admin_id = ?, updated_at = ?
            WHERE id = ? AND status = 'new' AND admin_id IS NULL
            """,
            (admin_id, now, ticket_id),
        )
        await self.db.commit()
        return cur.rowcount == 1

    async def reassign_ticket(self, ticket_id: int, admin_id: int) -> bool:
        """Перехват активной заявки другим администратором."""
        now = _now()
        cur = await self.db.execute(
            """
            UPDATE tickets
            SET status = 'in_progress', admin_id = ?, updated_at = ?, closed_at = NULL
            WHERE id = ?
              AND status IN ('new', 'in_progress', 'waiting')
            """,
            (admin_id, now, ticket_id),
        )
        await self.db.commit()
        return cur.rowcount == 1

    async def cleanup_expired(
        self,
        retention_days: int,
        admin_ids: set[int] | None = None,
    ) -> tuple[int, int]:
        """Удаляет закрытые заявки старше срока и осиротевших не-админов."""
        cutoff = (
            datetime.now(TZ).replace(tzinfo=None) - timedelta(days=retention_days)
        ).strftime("%Y-%m-%d %H:%M:%S")
        cur = await self.db.execute(
            """
            DELETE FROM tickets
            WHERE status IN ('done', 'cancelled')
              AND datetime(COALESCE(closed_at, updated_at)) < datetime(?)
            """,
            (cutoff,),
        )
        deleted_tickets = max(cur.rowcount, 0)

        admin_ids = admin_ids or set()
        clauses = [
            "NOT EXISTS (SELECT 1 FROM tickets WHERE tickets.user_id = users.user_id)"
        ]
        params: list[Any] = []
        if admin_ids:
            marks = ",".join("?" for _ in admin_ids)
            clauses.append(f"user_id NOT IN ({marks})")
            params.extend(admin_ids)
        cur = await self.db.execute(
            f"DELETE FROM users WHERE {' AND '.join(clauses)}",
            tuple(params),
        )
        deleted_users = max(cur.rowcount, 0)
        await self.db.commit()
        return deleted_tickets, deleted_users

    async def set_status(
        self, ticket_id: int, status: str, admin_id: int | None = None
    ) -> None:
        now = _now()
        closed = now if status in ("done", "cancelled") else None
        if status == "new":
            await self.db.execute(
                """
                UPDATE tickets
                SET status = 'new', admin_id = NULL, updated_at = ?, closed_at = NULL
                WHERE id = ?
                """,
                (now, ticket_id),
            )
        elif admin_id is not None:
            await self.db.execute(
                """
                UPDATE tickets
                SET status = ?, admin_id = COALESCE(admin_id, ?),
                    updated_at = ?, closed_at = COALESCE(?, closed_at)
                WHERE id = ?
                """,
                (status, admin_id, now, closed, ticket_id),
            )
        else:
            await self.db.execute(
                """
                UPDATE tickets
                SET status = ?, updated_at = ?, closed_at = COALESCE(?, closed_at)
                WHERE id = ?
                """,
                (status, now, closed, ticket_id),
            )
        await self.db.commit()

    async def set_priority(self, ticket_id: int, priority: str) -> None:
        await self.db.execute(
            "UPDATE tickets SET priority = ?, updated_at = ? WHERE id = ?",
            (priority, _now(), ticket_id),
        )
        await self.db.commit()

    async def upsert_crm_export(
        self,
        ticket_id: int,
        admin_id: int,
        title: str,
        duration_minutes: int,
        comment: str | None,
        report: str | None,
    ) -> dict[str, Any]:
        """Сохраняет outbox CRM; внешний ID стабилен для повторных отправок."""
        existing = await self.get_crm_export(ticket_id)
        external_id = (
            existing["external_id"]
            if existing
            else str(uuid.uuid5(uuid.NAMESPACE_URL, f"helpdesk:{ticket_id}"))
        )
        now = _now()
        await self.db.execute(
            """
            INSERT INTO crm_exports (
                ticket_id, external_id, admin_id, title, duration_minutes,
                comment, report, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, 'draft', ?, ?)
            ON CONFLICT(ticket_id) DO UPDATE SET
                admin_id = excluded.admin_id,
                title = excluded.title,
                duration_minutes = excluded.duration_minutes,
                comment = excluded.comment,
                report = excluded.report,
                status = CASE
                    WHEN crm_exports.status = 'sent' THEN 'sent'
                    ELSE 'draft'
                END,
                last_error = NULL,
                updated_at = excluded.updated_at
            """,
            (
                ticket_id,
                external_id,
                admin_id,
                title,
                duration_minutes,
                comment,
                report,
                now,
                now,
            ),
        )
        await self.db.commit()
        result = await self.get_crm_export(ticket_id)
        if result is None:
            raise RuntimeError("Не удалось сохранить выгрузку CRM")
        return result

    async def get_crm_export(self, ticket_id: int) -> dict[str, Any] | None:
        cur = await self.db.execute(
            "SELECT * FROM crm_exports WHERE ticket_id = ?", (ticket_id,)
        )
        row = await cur.fetchone()
        return dict(row) if row else None

    async def mark_crm_export_attempt(self, ticket_id: int) -> None:
        await self.db.execute(
            """
            UPDATE crm_exports
            SET status = 'sending', attempts = attempts + 1,
                last_error = NULL, updated_at = ?
            WHERE ticket_id = ? AND status != 'sent'
            """,
            (_now(), ticket_id),
        )
        await self.db.commit()

    async def mark_crm_export_sent(
        self, ticket_id: int, crm_task_id: int, crm_task_url: str | None
    ) -> None:
        await self.db.execute(
            """
            UPDATE crm_exports
            SET status = 'sent', crm_task_id = ?, crm_task_url = ?,
                last_error = NULL, updated_at = ?
            WHERE ticket_id = ?
            """,
            (crm_task_id, crm_task_url, _now(), ticket_id),
        )
        await self.db.commit()

    async def mark_crm_export_failed(self, ticket_id: int, error: str) -> None:
        await self.db.execute(
            """
            UPDATE crm_exports
            SET status = 'failed', last_error = ?, updated_at = ?
            WHERE ticket_id = ? AND status != 'sent'
            """,
            (error[:1000], _now(), ticket_id),
        )
        await self.db.commit()

    async def set_admin_note(self, ticket_id: int, note: str, admin_id: int) -> None:
        await self.db.execute(
            """
            UPDATE tickets
            SET admin_note = ?, admin_id = ?, updated_at = ?
            WHERE id = ?
            """,
            (note, admin_id, _now(), ticket_id),
        )
        await self.db.commit()

    async def add_comment(
        self, ticket_id: int, author_id: int, text: str, is_admin: bool
    ) -> None:
        await self.db.execute(
            """
            INSERT INTO ticket_comments (ticket_id, author_id, is_admin, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (ticket_id, author_id, int(is_admin), text, _now()),
        )
        await self.db.execute(
            "UPDATE tickets SET updated_at = ? WHERE id = ?",
            (_now(), ticket_id),
        )
        await self.db.commit()

    async def get_comments(self, ticket_id: int) -> list[dict[str, Any]]:
        cur = await self.db.execute(
            """
            SELECT * FROM ticket_comments
            WHERE ticket_id = ?
            ORDER BY id ASC
            """,
            (ticket_id,),
        )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    async def queue_position(self, ticket_id: int) -> int | None:
        """Позиция в активной очереди с учётом приоритета."""
        ticket = await self.get_ticket(ticket_id)
        if not ticket or ticket["status"] in ("done", "cancelled"):
            return None
        department_categories = {
            key
            for key, value in CATEGORY.items()
            if value["department"] == ticket["department"]
        }
        queue = await self.list_queue(categories=department_categories)
        for i, t in enumerate(queue, start=1):
            if t["id"] == ticket_id:
                return i
        return None

    async def stats(self, categories: set[str] | None = None) -> dict[str, int]:
        where = ""
        params: tuple[Any, ...] = ()
        if categories is not None:
            if not categories:
                return {
                    "new_cnt": 0,
                    "in_progress_cnt": 0,
                    "waiting_cnt": 0,
                    "done_cnt": 0,
                    "cancelled_cnt": 0,
                    "critical_cnt": 0,
                    "total": 0,
                }
            marks = ",".join("?" for _ in categories)
            where = f"WHERE category IN ({marks})"
            params = tuple(sorted(categories))
        cur = await self.db.execute(
            f"""
            SELECT
                SUM(CASE WHEN status = 'new' THEN 1 ELSE 0 END) AS new_cnt,
                SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) AS in_progress_cnt,
                SUM(CASE WHEN status = 'waiting' THEN 1 ELSE 0 END) AS waiting_cnt,
                SUM(CASE WHEN status = 'done' THEN 1 ELSE 0 END) AS done_cnt,
                SUM(CASE WHEN status = 'cancelled' THEN 1 ELSE 0 END) AS cancelled_cnt,
                SUM(CASE WHEN priority = 'critical' AND status NOT IN ('done','cancelled') THEN 1 ELSE 0 END) AS critical_cnt,
                COUNT(*) AS total
            FROM tickets
            {where}
            """,
            params,
        )
        row = await cur.fetchone()
        return {k: int(row[k] or 0) for k in row.keys()}

    async def search(
        self,
        query: str,
        limit: int = 15,
        categories: set[str] | None = None,
    ) -> list[dict[str, Any]]:
        like = f"%{query}%"
        department_clause = ""
        department_params: list[Any] = []
        if categories is not None:
            if not categories:
                return []
            marks = ",".join("?" for _ in categories)
            department_clause = f" AND t.category IN ({marks})"
            department_params.extend(sorted(categories))
        if query.isdigit():
            cur = await self.db.execute(
                f"""
                SELECT t.*, u.full_name, u.username,
                       au.full_name AS admin_full_name,
                       au.username AS admin_username
                FROM tickets t
                JOIN users u ON u.user_id = t.user_id
                LEFT JOIN users au ON au.user_id = t.admin_id
                WHERE t.id = ?{department_clause}
                """,
                (int(query), *department_params),
            )
        else:
            cur = await self.db.execute(
                f"""
                SELECT t.*, u.full_name, u.username,
                       au.full_name AS admin_full_name,
                       au.username AS admin_username
                FROM tickets t
                JOIN users u ON u.user_id = t.user_id
                LEFT JOIN users au ON au.user_id = t.admin_id
                WHERE (t.title LIKE ? OR t.description LIKE ?
                   OR u.full_name LIKE ? OR IFNULL(u.username, '') LIKE ?)
                {department_clause}
                ORDER BY t.id DESC
                LIMIT ?
                """,
                (like, like, like, like, *department_params, limit),
            )
        rows = await cur.fetchall()
        return [dict(r) for r in rows]



PRIORITY_WEIGHT = {k: v["weight"] for k, v in PRIORITY.items()}
