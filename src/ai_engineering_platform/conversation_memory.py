from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import time


@dataclass(frozen=True)
class MemoryEvent:
    id: int
    telegram_id: int
    agent_id: str
    role: str
    content: str
    created_at: int


class ConversationMemory:
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
                CREATE TABLE IF NOT EXISTS conversation_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    telegram_id INTEGER NOT NULL,
                    agent_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS idx_conversation_agent_user ON conversation_events(agent_id, telegram_id, id)"
            )

    def add_event(self, telegram_id: int, agent_id: str, role: str, content: str) -> None:
        now = int(time.time())
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO conversation_events (telegram_id, agent_id, role, content, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (telegram_id, agent_id, role, content, now),
            )

    def get_recent_events(self, telegram_id: int, agent_id: str, limit: int) -> list[MemoryEvent]:
        if limit <= 0:
            return []
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, telegram_id, agent_id, role, content, created_at
                FROM conversation_events
                WHERE telegram_id = ? AND agent_id = ?
                ORDER BY id DESC
                LIMIT ?
                """,
                (telegram_id, agent_id, limit),
            ).fetchall()
        return [
            MemoryEvent(
                id=int(row[0]),
                telegram_id=int(row[1]),
                agent_id=str(row[2]),
                role=str(row[3]),
                content=str(row[4]),
                created_at=int(row[5]),
            )
            for row in reversed(rows)
        ]

    def clear_user_agent(self, telegram_id: int, agent_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM conversation_events WHERE telegram_id = ? AND agent_id = ?",
                (telegram_id, agent_id),
            )

    def count_events(self, telegram_id: int | None = None) -> int:
        with self._connect() as connection:
            if telegram_id is None:
                row = connection.execute("SELECT COUNT(*) FROM conversation_events").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM conversation_events WHERE telegram_id = ?",
                    (telegram_id,),
                ).fetchone()
        return int(row[0])
