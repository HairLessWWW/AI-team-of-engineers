from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time


ROLES = ("owner", "admin", "member", "viewer")
ADMIN_ROLES = {"owner", "admin"}
ACTIVE_ROLES = set(ROLES)


@dataclass(frozen=True)
class AccessUser:
    telegram_id: int
    role: str
    is_active: bool
    created_at: int
    updated_at: int


class AccessStore:
    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self.db_path)

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS users (
                    telegram_id INTEGER PRIMARY KEY,
                    role TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def ensure_user(self, telegram_id: int, role: str = "member", is_active: bool = True) -> None:
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role}")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO users (telegram_id, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(telegram_id) DO UPDATE SET
                    role = excluded.role,
                    is_active = excluded.is_active,
                    updated_at = excluded.updated_at
                """,
                (telegram_id, role, int(is_active), now, now),
            )

    def set_active(self, telegram_id: int, is_active: bool) -> None:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET is_active = ?, updated_at = ? WHERE telegram_id = ?",
                (int(is_active), now, telegram_id),
            )

    def set_role(self, telegram_id: int, role: str) -> None:
        if role not in ROLES:
            raise ValueError(f"Unknown role: {role}")
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                "UPDATE users SET role = ?, updated_at = ? WHERE telegram_id = ?",
                (role, now, telegram_id),
            )

    def get_user(self, telegram_id: int) -> AccessUser | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT telegram_id, role, is_active, created_at, updated_at FROM users WHERE telegram_id = ?",
                (telegram_id,),
            ).fetchone()
        if row is None:
            return None
        return AccessUser(
            telegram_id=int(row[0]),
            role=str(row[1]),
            is_active=bool(row[2]),
            created_at=int(row[3]),
            updated_at=int(row[4]),
        )

    def list_users(self) -> list[AccessUser]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT telegram_id, role, is_active, created_at, updated_at FROM users ORDER BY role, telegram_id"
            ).fetchall()
        return [
            AccessUser(
                telegram_id=int(row[0]),
                role=str(row[1]),
                is_active=bool(row[2]),
                created_at=int(row[3]),
                updated_at=int(row[4]),
            )
            for row in rows
        ]

    def is_allowed(self, telegram_id: int) -> bool:
        user = self.get_user(telegram_id)
        return bool(user and user.is_active and user.role in ACTIVE_ROLES)

    def is_admin(self, telegram_id: int) -> bool:
        user = self.get_user(telegram_id)
        return bool(user and user.is_active and user.role in ADMIN_ROLES)


def seed_owner_users(store: AccessStore, owner_ids: set[int]) -> None:
    for owner_id in owner_ids:
        store.ensure_user(owner_id, role="owner", is_active=True)
