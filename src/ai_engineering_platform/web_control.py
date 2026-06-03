from __future__ import annotations

from dataclasses import dataclass
from html import escape
import hashlib
import hmac
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
import json
import os
from pathlib import Path
from sqlite3 import Connection
import sqlite3
import time
from typing import Any
from urllib import parse

from .agents import load_agents
from .prompts import load_agent_prompt


DEFAULT_WEB_DB = Path("work/control-center.db")


@dataclass(frozen=True)
class WebConfig:
    host: str = "127.0.0.1"
    port: int = 8080
    password: str = "change-me"
    session_secret: str = "change-me"
    agents_path: Path = Path("configs/agents.json")
    prompts_path: Path = Path("prompts")
    web_db_path: Path = DEFAULT_WEB_DB
    access_db_path: Path | None = None
    memory_db_path: Path | None = None
    materials_db_path: Path | None = None

    @classmethod
    def from_env(cls) -> "WebConfig":
        return cls(
            host=os.getenv("AI_ENGINEERING_WEB_HOST", "127.0.0.1"),
            port=int(os.getenv("AI_ENGINEERING_WEB_PORT", "8080")),
            password=os.getenv("AI_ENGINEERING_WEB_PASSWORD", "change-me"),
            session_secret=os.getenv("AI_ENGINEERING_WEB_SESSION_SECRET", os.getenv("AI_ENGINEERING_WEB_PASSWORD", "change-me")),
            agents_path=Path(os.getenv("AI_ENGINEERING_AGENTS_PATH", "configs/agents.json")),
            prompts_path=Path(os.getenv("AI_ENGINEERING_PROMPTS_PATH", "prompts")),
            web_db_path=Path(os.getenv("AI_ENGINEERING_WEB_DB", str(DEFAULT_WEB_DB))),
            access_db_path=env_path("TELEGRAM_ACCESS_DB"),
            memory_db_path=env_path("TELEGRAM_MEMORY_DB"),
            materials_db_path=env_path("TELEGRAM_MATERIALS_DB"),
        )


def env_path(name: str) -> Path | None:
    raw = os.getenv(name, "").strip()
    return Path(raw) if raw else None


def init_web_db(db_path: Path) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                goal TEXT NOT NULL DEFAULT '',
                agents TEXT NOT NULL DEFAULT '[]',
                notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS rules (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                scope TEXT NOT NULL DEFAULT 'global',
                content TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS web_users (
                username TEXT PRIMARY KEY,
                password_hash TEXT NOT NULL,
                role TEXT NOT NULL,
                is_active INTEGER NOT NULL DEFAULT 1,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS org_structures (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                parent_id INTEGER,
                description TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS org_positions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                structure_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                department TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                sort_order INTEGER NOT NULL DEFAULT 0,
                notes TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS backlog_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                area TEXT NOT NULL DEFAULT 'product',
                priority TEXT NOT NULL DEFAULT 'medium',
                status TEXT NOT NULL DEFAULT 'idea',
                description TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                result TEXT NOT NULL DEFAULT '',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS project_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL,
                artifact_type TEXT NOT NULL DEFAULT 'artifact',
                title TEXT NOT NULL,
                content TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'draft',
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
            """
        )
        ensure_project_material_columns(connection)
        seed_cto_structure(connection)
        seed_product_backlog(connection)


def ensure_project_material_columns(connection: sqlite3.Connection) -> None:
    table = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        ("project_materials",),
    ).fetchone()
    if table is None:
        return
    columns = {row[1] for row in connection.execute("PRAGMA table_info(project_materials)").fetchall()}
    if "project_id" not in columns:
        connection.execute("ALTER TABLE project_materials ADD COLUMN project_id INTEGER")


def ensure_materials_db_project_columns(db_path: Path | None) -> None:
    connection = connect_existing(db_path)
    if connection is None:
        return
    with connection:
        ensure_project_material_columns(connection)
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_project_materials_project ON project_materials(project_id, id)"
        )


CTO_POSITIONS = [
    "Electrical Lead Engineer",
    "Mechanical Design Lead",
    "Embedded Robot Control Engineer",
    "PLC and Industrial Senior Software Engineer",
    "Firmware Senior Engineer",
    "Robotics Application Senior Software Engineer",
    "Certification and Technical Documentation Senior Engineer",
    "AI-system Architect",
    "Product Manager",
    "Production and Assembly Manager",
    "Chief Assembly Technologist",
    "Field Service and Commissioning Senior Engineer",
    "Lead Quality Engineer",
]

INITIAL_BACKLOG = [
    (
        "Project Workspace v0.1",
        "product",
        "high",
        "planned",
        "Сделать проект центральной сущностью: материалы, задачи, история и совещания внутри проекта.",
    ),
    (
        "Проектные задачи AI-агентам",
        "agent-runtime",
        "high",
        "planned",
        "Создавать задачу агенту из проекта, хранить статус, результат и вопросы к человеку.",
    ),
    (
        "Материалы проекта вместо личных материалов",
        "knowledge",
        "high",
        "planned",
        "Привязывать Word/Excel/PPTX/ссылки к проекту и использовать их в контексте выбранного проекта.",
    ),
    (
        "Протоколы решений и Human Approval",
        "workflow",
        "medium",
        "idea",
        "Ответы AI переводить в заметки, решения, задачи или отправлять на доработку.",
    ),
]


def seed_cto_structure(connection: sqlite3.Connection) -> None:
    row = connection.execute("SELECT id FROM org_structures WHERE name = ?", ("Структура технического директора",)).fetchone()
    if row is not None:
        return
    now = int(time.time())
    cursor = connection.execute(
        """
        INSERT INTO org_structures (name, parent_id, description, sort_order, created_at, updated_at)
        VALUES (?, NULL, ?, ?, ?, ?)
        """,
        (
            "Структура технического директора",
            "Базовая верхнеуровневая структура CTO для робототехнической инженерной организации.",
            0,
            now,
            now,
        ),
    )
    structure_id = int(cursor.lastrowid)
    for index, title in enumerate(CTO_POSITIONS):
        connection.execute(
            """
            INSERT INTO org_positions (structure_id, title, department, sort_order, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (structure_id, title, suggest_position_department(title), index, now, now),
        )


def seed_product_backlog(connection: sqlite3.Connection) -> None:
    now = int(time.time())
    for title, area, priority, status, description in INITIAL_BACKLOG:
        row = connection.execute("SELECT id FROM backlog_items WHERE title = ?", (title,)).fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO backlog_items (title, area, priority, status, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, area, priority, status, description, now, now),
            )


def suggest_position_department(title: str) -> str:
    lowered = title.lower()
    if "production" in lowered or "assembly" in lowered or "technologist" in lowered or "quality" in lowered:
        return "Производство и качество"
    if "certification" in lowered or "documentation" in lowered:
        return "Сертификация и документация"
    if "product manager" in lowered:
        return "Продукт"
    if "software" in lowered or "firmware" in lowered or "embedded" in lowered or "ai-system" in lowered:
        return "ПО и системы управления"
    if "field service" in lowered or "commissioning" in lowered:
        return "Сервис и пусконаладка"
    return "Инженерия продукта"


def seed_admin_user(db_path: Path, password: str) -> None:
    now = int(time.time())
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT username FROM web_users WHERE username = 'admin'").fetchone()
        if row is None:
            connection.execute(
                """
                INSERT INTO web_users (username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                ("admin", hash_password(password), "owner", 1, now, now),
            )


def hash_password(password: str, salt: str | None = None) -> str:
    salt = salt or base64.urlsafe_b64encode(os.urandom(16)).decode("ascii")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), 120_000)
    return f"pbkdf2_sha256${salt}${base64.urlsafe_b64encode(digest).decode('ascii')}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    return hmac.compare_digest(hash_password(password, salt), stored)


def authenticate_user(db_path: Path, username: str, password: str) -> dict[str, str] | None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT username, password_hash, role, is_active FROM web_users WHERE username = ?",
            (username,),
        ).fetchone()
    if row is None or not int(row[3]) or not verify_password(password, str(row[1])):
        return None
    return {"username": str(row[0]), "role": str(row[2])}


def list_web_users(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT username, role, is_active, created_at, updated_at FROM web_users ORDER BY role, username"
        ).fetchall()
    return [
        {"username": row[0], "role": row[1], "is_active": bool(row[2]), "created_at": row[3], "updated_at": row[4]}
        for row in rows
    ]


def save_web_user(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    username = first(form, "username")
    password = first(form, "password")
    role = first(form, "role") or "member"
    is_active = 1 if first(form, "is_active") != "0" else 0
    if not username:
        raise ValueError("username is required")
    with sqlite3.connect(db_path) as connection:
        row = connection.execute("SELECT username FROM web_users WHERE username = ?", (username,)).fetchone()
        if row is None:
            if not password:
                raise ValueError("password is required for new user")
            connection.execute(
                """
                INSERT INTO web_users (username, password_hash, role, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (username, hash_password(password), role, is_active, now, now),
            )
        elif password:
            connection.execute(
                "UPDATE web_users SET password_hash = ?, role = ?, is_active = ?, updated_at = ? WHERE username = ?",
                (hash_password(password), role, is_active, now, username),
            )
        else:
            connection.execute(
                "UPDATE web_users SET role = ?, is_active = ?, updated_at = ? WHERE username = ?",
                (role, is_active, now, username),
            )


def connect_existing(db_path: Path | None) -> Connection | None:
    if db_path is None or not db_path.exists():
        return None
    return sqlite3.connect(db_path)


def list_projects(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, name, status, goal, agents, notes, created_at, updated_at FROM projects ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "status": row[2],
            "goal": row[3],
            "agents": json.loads(row[4] or "[]"),
            "notes": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def get_project(db_path: Path, project_id: int) -> dict[str, Any] | None:
    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            "SELECT id, name, status, goal, agents, notes, created_at, updated_at FROM projects WHERE id = ?",
            (project_id,),
        ).fetchone()
    if row is None:
        return None
    return {
        "id": row[0],
        "name": row[1],
        "status": row[2],
        "goal": row[3],
        "agents": json.loads(row[4] or "[]"),
        "notes": row[5],
        "created_at": row[6],
        "updated_at": row[7],
    }


def save_project(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    project_id = first(form, "id")
    name = first(form, "name") or "Новый проект"
    status = first(form, "status") or "active"
    goal = first(form, "goal")
    notes = first(form, "notes")
    agents = form.get("agents", [])
    with sqlite3.connect(db_path) as connection:
        if project_id:
            connection.execute(
                """
                UPDATE projects SET name = ?, status = ?, goal = ?, agents = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, status, goal, json.dumps(agents, ensure_ascii=False), notes, now, int(project_id)),
            )
        else:
            connection.execute(
                """
                INSERT INTO projects (name, status, goal, agents, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (name, status, goal, json.dumps(agents, ensure_ascii=False), notes, now, now),
            )


def list_project_tasks(db_path: Path, project_id: int | None = None) -> list[dict[str, Any]]:
    query = "SELECT id, project_id, title, agent_id, status, result, created_at, updated_at FROM project_tasks"
    params: tuple[Any, ...] = ()
    if project_id is not None:
        query += " WHERE project_id = ?"
        params = (project_id,)
    query += " ORDER BY updated_at DESC, id DESC"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row[0],
            "project_id": row[1],
            "title": row[2],
            "agent_id": row[3],
            "status": row[4],
            "result": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def save_project_task(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    task_id = first(form, "id")
    project_id = int(first(form, "project_id"))
    title = first(form, "title") or "Новая задача"
    agent_id = first(form, "agent_id")
    status = first(form, "status") or "open"
    result = first(form, "result")
    with sqlite3.connect(db_path) as connection:
        if task_id:
            connection.execute(
                """
                UPDATE project_tasks SET project_id = ?, title = ?, agent_id = ?, status = ?, result = ?, updated_at = ?
                WHERE id = ?
                """,
                (project_id, title, agent_id, status, result, now, int(task_id)),
            )
        else:
            connection.execute(
                """
                INSERT INTO project_tasks (project_id, title, agent_id, status, result, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, title, agent_id, status, result, now, now),
            )


def list_project_artifacts(db_path: Path, project_id: int, artifact_type: str | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT id, project_id, artifact_type, title, content, status, created_at, updated_at
        FROM project_artifacts
        WHERE project_id = ?
    """
    params: tuple[Any, ...] = (project_id,)
    if artifact_type is not None:
        query += " AND artifact_type = ?"
        params = (project_id, artifact_type)
    query += " ORDER BY updated_at DESC, id DESC"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row[0],
            "project_id": row[1],
            "artifact_type": row[2],
            "title": row[3],
            "content": row[4],
            "status": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def save_project_artifact(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    artifact_id = first(form, "id")
    project_id = int(first(form, "project_id"))
    artifact_type = first(form, "artifact_type") or "artifact"
    title = first(form, "title") or "Новый артефакт"
    content = first(form, "content")
    status = first(form, "status") or "draft"
    with sqlite3.connect(db_path) as connection:
        if artifact_id:
            connection.execute(
                """
                UPDATE project_artifacts SET artifact_type = ?, title = ?, content = ?, status = ?, updated_at = ?
                WHERE id = ? AND project_id = ?
                """,
                (artifact_type, title, content, status, now, int(artifact_id), project_id),
            )
        else:
            connection.execute(
                """
                INSERT INTO project_artifacts (project_id, artifact_type, title, content, status, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (project_id, artifact_type, title, content, status, now, now),
            )


def list_backlog_items(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, title, area, priority, status, description, created_at, updated_at
            FROM backlog_items
            ORDER BY
              CASE priority WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
              id DESC
            """
        ).fetchall()
    return [
        {
            "id": row[0],
            "title": row[1],
            "area": row[2],
            "priority": row[3],
            "status": row[4],
            "description": row[5],
            "created_at": row[6],
            "updated_at": row[7],
        }
        for row in rows
    ]


def save_backlog_item(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    item_id = first(form, "id")
    title = first(form, "title") or "Новая задача backlog"
    area = first(form, "area") or "product"
    priority = first(form, "priority") or "medium"
    status = first(form, "status") or "idea"
    description = first(form, "description")
    with sqlite3.connect(db_path) as connection:
        if item_id:
            connection.execute(
                """
                UPDATE backlog_items SET title = ?, area = ?, priority = ?, status = ?, description = ?, updated_at = ?
                WHERE id = ?
                """,
                (title, area, priority, status, description, now, int(item_id)),
            )
        else:
            connection.execute(
                """
                INSERT INTO backlog_items (title, area, priority, status, description, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (title, area, priority, status, description, now, now),
            )


def list_org_structures(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            """
            SELECT id, name, parent_id, description, sort_order, created_at, updated_at
            FROM org_structures
            ORDER BY sort_order, id
            """
        ).fetchall()
    return [
        {
            "id": row[0],
            "name": row[1],
            "parent_id": row[2],
            "description": row[3],
            "sort_order": row[4],
            "created_at": row[5],
            "updated_at": row[6],
        }
        for row in rows
    ]


def list_org_positions(db_path: Path, structure_id: int | None = None) -> list[dict[str, Any]]:
    query = """
        SELECT id, structure_id, title, department, agent_id, sort_order, notes, created_at, updated_at
        FROM org_positions
    """
    params: tuple[Any, ...] = ()
    if structure_id is not None:
        query += " WHERE structure_id = ?"
        params = (structure_id,)
    query += " ORDER BY structure_id, sort_order, id"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(query, params).fetchall()
    return [
        {
            "id": row[0],
            "structure_id": row[1],
            "title": row[2],
            "department": row[3],
            "agent_id": row[4],
            "sort_order": row[5],
            "notes": row[6],
            "created_at": row[7],
            "updated_at": row[8],
        }
        for row in rows
    ]


def save_org_structure(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    structure_id = first(form, "id")
    name = first(form, "name") or "Новая структура"
    parent_raw = first(form, "parent_id")
    parent_id = int(parent_raw) if parent_raw else None
    description = first(form, "description")
    sort_order = int(first(form, "sort_order") or "0")
    with sqlite3.connect(db_path) as connection:
        if structure_id:
            connection.execute(
                """
                UPDATE org_structures
                SET name = ?, parent_id = ?, description = ?, sort_order = ?, updated_at = ?
                WHERE id = ?
                """,
                (name, parent_id, description, sort_order, now, int(structure_id)),
            )
        else:
            connection.execute(
                """
                INSERT INTO org_structures (name, parent_id, description, sort_order, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (name, parent_id, description, sort_order, now, now),
            )


def save_org_position(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    position_id = first(form, "id")
    structure_id = int(first(form, "structure_id"))
    title = first(form, "title") or "Новая позиция"
    department = first(form, "department")
    agent_id = first(form, "agent_id")
    sort_order = int(first(form, "sort_order") or "0")
    notes = first(form, "notes")
    with sqlite3.connect(db_path) as connection:
        if position_id:
            connection.execute(
                """
                UPDATE org_positions
                SET structure_id = ?, title = ?, department = ?, agent_id = ?, sort_order = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (structure_id, title, department, agent_id, sort_order, notes, now, int(position_id)),
            )
        else:
            connection.execute(
                """
                INSERT INTO org_positions (structure_id, title, department, agent_id, sort_order, notes, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (structure_id, title, department, agent_id, sort_order, notes, now, now),
            )


def delete_org_structure(db_path: Path, structure_id: int) -> None:
    with sqlite3.connect(db_path) as connection:
        child = connection.execute("SELECT id FROM org_structures WHERE parent_id = ? LIMIT 1", (structure_id,)).fetchone()
        if child is not None:
            raise ValueError("Сначала удали или перепривяжи дочерние структуры.")
        connection.execute("DELETE FROM org_positions WHERE structure_id = ?", (structure_id,))
        connection.execute("DELETE FROM org_structures WHERE id = ?", (structure_id,))


def delete_org_position(db_path: Path, position_id: int) -> None:
    with sqlite3.connect(db_path) as connection:
        connection.execute("DELETE FROM org_positions WHERE id = ?", (position_id,))


def list_rules(db_path: Path) -> list[dict[str, Any]]:
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT id, title, scope, content, created_at, updated_at FROM rules ORDER BY updated_at DESC"
        ).fetchall()
    return [
        {"id": row[0], "title": row[1], "scope": row[2], "content": row[3], "created_at": row[4], "updated_at": row[5]}
        for row in rows
    ]


def save_rule(db_path: Path, form: dict[str, list[str]]) -> None:
    now = int(time.time())
    rule_id = first(form, "id")
    title = first(form, "title") or "Новое правило"
    scope = first(form, "scope") or "global"
    content = first(form, "content")
    with sqlite3.connect(db_path) as connection:
        if rule_id:
            connection.execute(
                "UPDATE rules SET title = ?, scope = ?, content = ?, updated_at = ? WHERE id = ?",
                (title, scope, content, now, int(rule_id)),
            )
        else:
            connection.execute(
                "INSERT INTO rules (title, scope, content, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
                (title, scope, content, now, now),
            )


def save_agent(agents_path: Path, prompts_path: Path, form: dict[str, list[str]]) -> str:
    agent_id = first(form, "id").strip()
    if not agent_id:
        raise ValueError("agent id is required")
    data = json.loads(agents_path.read_text(encoding="utf-8"))
    agents = data.setdefault("agents", [])
    payload = {
        "id": agent_id,
        "name": first(form, "name") or agent_id,
        "department": first(form, "department") or "Инженерная команда",
        "order": int(first(form, "order") or "0"),
        "focus": first(form, "focus"),
        "keywords": split_csv(first(form, "keywords")),
        "expected_artifacts": split_csv(first(form, "expected_artifacts")),
    }
    for index, agent in enumerate(agents):
        if agent.get("id") == agent_id:
            agents[index] = payload
            break
    else:
        agents.append(payload)
    agents_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    prompts_path.mkdir(parents=True, exist_ok=True)
    (prompts_path / f"{agent_id}.md").write_text(first(form, "prompt"), encoding="utf-8")
    return agent_id


def save_agent_layout(agents_path: Path, payload: list[dict[str, Any]]) -> None:
    data = json.loads(agents_path.read_text(encoding="utf-8"))
    layout: dict[str, tuple[str, int]] = {}
    for item in payload:
        agent_id = str(item.get("id", "")).strip()
        department = str(item.get("department", "")).strip() or "Инженерная команда"
        order = int(item.get("order", 0))
        if agent_id:
            layout[agent_id] = (department, order)
    for index, agent in enumerate(data.get("agents", [])):
        agent_id = str(agent.get("id", ""))
        if agent_id in layout:
            department, order = layout[agent_id]
            agent["department"] = department
            agent["order"] = order
        else:
            agent["order"] = int(agent.get("order", index))
    data["agents"] = sorted(data.get("agents", []), key=lambda item: (str(item.get("department", "")), int(item.get("order", 0))))
    agents_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def split_csv(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def first(form: dict[str, list[str]], key: str) -> str:
    values = form.get(key, [])
    return values[0].strip() if values else ""


def count_table(db_path: Path | None, table: str) -> int:
    connection = connect_existing(db_path)
    if connection is None:
        return 0
    with connection:
        row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    return int(row[0])


def recent_history(db_path: Path | None, limit: int = 50) -> list[dict[str, Any]]:
    connection = connect_existing(db_path)
    if connection is None:
        return []
    with connection:
        rows = connection.execute(
            """
            SELECT telegram_id, agent_id, role, content, created_at
            FROM conversation_events
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [{"telegram_id": row[0], "agent_id": row[1], "role": row[2], "content": row[3], "created_at": row[4]} for row in rows]


def recent_materials(db_path: Path | None, limit: int = 50, project_id: int | None = None) -> list[dict[str, Any]]:
    connection = connect_existing(db_path)
    if connection is None:
        return []
    with connection:
        ensure_project_material_columns(connection)
        where = ""
        params: tuple[Any, ...] = (limit,)
        if project_id is not None:
            where = "WHERE project_id = ?"
            params = (project_id, limit)
        rows = connection.execute(
            f"""
            SELECT id, telegram_id, project_id, source_type, title, source_url, created_at
            FROM project_materials
            {where}
            ORDER BY id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [
        {
            "id": row[0],
            "telegram_id": row[1],
            "project_id": row[2],
            "source_type": row[3],
            "title": row[4],
            "source_url": row[5],
            "created_at": row[6],
        }
        for row in rows
    ]


def assign_material_to_project(db_path: Path | None, material_id: int, project_id: int | None) -> None:
    connection = connect_existing(db_path)
    if connection is None:
        raise ValueError("База материалов не настроена.")
    with connection:
        ensure_project_material_columns(connection)
        connection.execute(
            "UPDATE project_materials SET project_id = ? WHERE id = ?",
            (project_id, material_id),
        )


def render_page(config: WebConfig, active: str, body: str) -> bytes:
    nav = [
        ("dashboard", "Панель"),
        ("agents", "Агенты"),
        ("org", "Штат"),
        ("projects", "Проекты"),
        ("backlog", "Backlog"),
        ("knowledge", "База знаний"),
        ("history", "История"),
        ("rules", "Правила"),
        ("settings", "Настройки"),
        ("logout", "Выход"),
    ]
    links = "\n".join(
        f'<a class="{"active" if key == active else ""}" href="/{key}">{label}</a>' for key, label in nav
    )
    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>AI Team Control Center</title>
  <style>{CSS}</style>
</head>
<body>
  <aside>
    <div class="brand">AI Team<br><span>Control Center</span></div>
    <nav>{links}</nav>
  </aside>
  <main>{body}</main>
  {MODAL_SCRIPT}
</body>
</html>"""
    return html.encode("utf-8")


def render_login(error: str = "") -> bytes:
    error_html = f"<p class='error'>{h(error)}</p>" if error else ""
    html = f"""<!doctype html>
<html lang="ru">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Вход · AI Team Control Center</title>
  <style>{CSS}</style>
</head>
<body class="login-page">
  <main class="login-main">
    <form class="login-card" method="post" action="/login">
      <h1>AI Team Control Center</h1>
      <p class="lead">Вход в кабинет управления AI-командой.</p>
      {error_html}
      <label>Логин<input name="username" autocomplete="username" autofocus></label>
      <label>Пароль<input name="password" type="password" autocomplete="current-password"></label>
      <button type="submit">Войти</button>
    </form>
  </main>
</body>
</html>"""
    return html.encode("utf-8")


def h(value: object) -> str:
    return escape(str(value), quote=True)


def fmt_time(timestamp: int | None) -> str:
    if not timestamp:
        return "-"
    return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


class ControlCenterHandler(BaseHTTPRequestHandler):
    config: WebConfig

    def do_GET(self) -> None:
        parsed_url = parse.urlparse(self.path)
        path = parsed_url.path.strip("/") or "dashboard"
        if path == "login":
            self.respond(render_login())
            return
        user = self.current_user()
        if user is None:
            self.redirect("/login")
            return
        if path == "logout":
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/login")
            self.send_header("Set-Cookie", "ai_team_session=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax")
            self.end_headers()
            return
        routes = {
            "dashboard": self.render_dashboard,
            "agents": self.render_agents,
            "org": self.render_org,
            "projects": self.render_projects,
            "project": lambda: self.render_project(parse.parse_qs(parsed_url.query)),
            "backlog": self.render_backlog,
            "knowledge": self.render_knowledge,
            "history": self.render_history,
            "rules": self.render_rules,
            "settings": self.render_settings,
        }
        renderer = routes.get(path)
        if renderer is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.respond(render_page(self.config, path, renderer()))

    def do_POST(self) -> None:
        path = parse.urlparse(self.path).path
        if path == "/agents/layout":
            user = self.current_user()
            if user is None:
                self.respond_json({"ok": False, "error": "unauthorized"}, HTTPStatus.UNAUTHORIZED)
                return
            try:
                self.require_role(user, {"owner", "admin"})
                payload = json.loads(self.read_raw_body().decode("utf-8"))
                save_agent_layout(self.config.agents_path, payload.get("agents", []))
                self.respond_json({"ok": True})
            except Exception as exc:
                self.respond_json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
            return
        form = self.read_form()
        if path == "/login":
            user = authenticate_user(self.config.web_db_path, first(form, "username"), first(form, "password"))
            if user is None:
                self.respond(render_login("Неверный логин или пароль."), HTTPStatus.UNAUTHORIZED)
                return
            self.send_response(HTTPStatus.SEE_OTHER)
            self.send_header("Location", "/dashboard")
            self.send_header("Set-Cookie", f"ai_team_session={self.make_session_cookie(user['username'], user['role'])}; Path=/; HttpOnly; SameSite=Lax")
            self.end_headers()
            return
        user = self.current_user()
        if user is None:
            self.redirect("/login")
            return
        try:
            if path == "/agents/save":
                self.require_role(user, {"owner", "admin"})
                save_agent(self.config.agents_path, self.config.prompts_path, form)
                self.redirect("/agents")
                return
            if path == "/projects/save":
                self.require_role(user, {"owner", "admin", "member"})
                save_project(self.config.web_db_path, form)
                self.redirect("/projects")
                return
            if path == "/project/task/save":
                self.require_role(user, {"owner", "admin", "member"})
                save_project_task(self.config.web_db_path, form)
                self.redirect(f"/project?id={first(form, 'project_id')}")
                return
            if path == "/project/artifact/save":
                self.require_role(user, {"owner", "admin", "member"})
                save_project_artifact(self.config.web_db_path, form)
                self.redirect(f"/project?id={first(form, 'project_id')}")
                return
            if path == "/materials/assign":
                self.require_role(user, {"owner", "admin", "member"})
                project_raw = first(form, "project_id")
                assign_material_to_project(
                    self.config.materials_db_path,
                    int(first(form, "material_id")),
                    int(project_raw) if project_raw else None,
                )
                redirect_to = first(form, "redirect_to") or "/knowledge"
                self.redirect(redirect_to)
                return
            if path == "/backlog/save":
                self.require_role(user, {"owner", "admin", "member"})
                save_backlog_item(self.config.web_db_path, form)
                self.redirect("/backlog")
                return
            if path == "/rules/save":
                self.require_role(user, {"owner", "admin"})
                save_rule(self.config.web_db_path, form)
                self.redirect("/rules")
                return
            if path == "/users/save":
                self.require_role(user, {"owner", "admin"})
                save_web_user(self.config.web_db_path, form)
                self.redirect("/settings")
                return
            if path == "/org/structure/save":
                self.require_role(user, {"owner", "admin"})
                save_org_structure(self.config.web_db_path, form)
                self.redirect("/org")
                return
            if path == "/org/position/save":
                self.require_role(user, {"owner", "admin"})
                save_org_position(self.config.web_db_path, form)
                self.redirect("/org")
                return
            if path == "/org/structure/delete":
                self.require_role(user, {"owner", "admin"})
                delete_org_structure(self.config.web_db_path, int(first(form, "id")))
                self.redirect("/org")
                return
            if path == "/org/position/delete":
                self.require_role(user, {"owner", "admin"})
                delete_org_position(self.config.web_db_path, int(first(form, "id")))
                self.redirect("/org")
                return
        except Exception as exc:
            self.respond(render_page(self.config, "settings", f"<h1>Ошибка</h1><p>{h(exc)}</p>"), HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def make_session_cookie(self, username: str, role: str) -> str:
        expires = int(time.time()) + 60 * 60 * 24 * 7
        payload = f"{username}|{role}|{expires}"
        signature = hmac.new(self.config.session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        return base64.urlsafe_b64encode(f"{payload}|{signature}".encode("utf-8")).decode("ascii")

    def current_user(self) -> dict[str, str] | None:
        cookie = self.headers.get("Cookie", "")
        marker = "ai_team_session="
        raw = ""
        for part in cookie.split(";"):
            part = part.strip()
            if part.startswith(marker):
                raw = part.removeprefix(marker)
                break
        if not raw:
            return None
        try:
            decoded = base64.urlsafe_b64decode(raw.encode("ascii")).decode("utf-8")
            username, role, expires_raw, signature = decoded.rsplit("|", 3)
            payload = f"{username}|{role}|{expires_raw}"
            expected = hmac.new(self.config.session_secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
        except Exception:
            return None
        if not hmac.compare_digest(signature, expected) or int(expires_raw) < int(time.time()):
            return None
        return {"username": username, "role": role}

    def require_role(self, user: dict[str, str], roles: set[str]) -> None:
        if user["role"] not in roles:
            raise PermissionError("Недостаточно прав для этого действия.")

    def read_form(self) -> dict[str, list[str]]:
        return parse.parse_qs(self.read_raw_body().decode("utf-8"))

    def read_raw_body(self) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        return self.rfile.read(length)

    def redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.end_headers()

    def respond(self, body: bytes, status: HTTPStatus = HTTPStatus.OK) -> None:
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def respond_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def render_dashboard(self) -> str:
        agents = load_agents(self.config.agents_path)
        projects = list_projects(self.config.web_db_path)
        return f"""
<section class="hero">
  <div>
    <p class="eyebrow">Робототехническая инженерная команда</p>
    <h1>Центр управления AI-специалистами</h1>
    <p>Настройка ролей, правил, проектов, базы знаний и истории работы команды.</p>
  </div>
  <div class="status">сервер активен</div>
</section>
<section class="metrics">
  {metric("Агенты", len(agents))}
  {metric("Проекты", len(projects))}
  {metric("Материалы", count_table(self.config.materials_db_path, "project_materials"))}
  {metric("Сообщения", count_table(self.config.memory_db_path, "conversation_events"))}
</section>
<section class="grid two">
  <div>{panel_title("Активные проекты")}{project_list(projects[:6], agents)}</div>
  <div>{panel_title("Последняя история")}{history_list(recent_history(self.config.memory_db_path, 8))}</div>
</section>
"""

    def render_agents(self) -> str:
        agents = sorted(load_agents(self.config.agents_path), key=lambda item: (item.department, item.order, item.name))
        departments: dict[str, list[Any]] = {}
        for agent in agents:
            departments.setdefault(agent.department, []).append(agent)
        sections = "".join(agent_department_section(department, items, self.config.prompts_path) for department, items in sorted(departments.items()))
        new_agent = agent_modal("", "", "Инженерная команда", "", [], [], "")
        return f"""
<div class="page-head">
  <div>
    <h1>Агенты</h1>
    <p class="lead">Штат AI-команды по отделам. Перетаскивай карточки мышкой, чтобы менять отдел и порядок.</p>
  </div>
  <div class="head-actions">
    <span id="layout-status" class="save-status">порядок сохранен</span>
    <a class="button-link" href="#agent-new">Новый агент</a>
  </div>
</div>
{sections}
{new_agent}
{AGENTS_DRAG_SCRIPT}
"""

    def render_org(self) -> str:
        agents = load_agents(self.config.agents_path)
        structures = list_org_structures(self.config.web_db_path)
        positions = list_org_positions(self.config.web_db_path)
        return f"""
<h1>Штатная структура</h1>
<p class="lead">Несколько структур можно объединять через родительскую структуру: CTO, производство, продукт, сервис, сертификация.</p>
<section class="grid two">
  <div>{panel_title("Структуры")}{org_structure_tree(structures)}</div>
  <div>{panel_title("Добавить структуру")}{org_structure_form(None, structures)}</div>
</section>
{org_structure_sections(structures, positions, agents)}
"""

    def render_projects(self) -> str:
        agents = load_agents(self.config.agents_path)
        projects = list_projects(self.config.web_db_path)
        existing = "".join(project_form(project, agents) for project in projects)
        return f"<h1>Проекты</h1><p class='lead'>Проект связывает цель, AI-сотрудников, заметки и будущие материалы.</p>{project_form(None, agents)}{existing}"

    def render_project(self, query: dict[str, list[str]]) -> str:
        project_id_raw = query.get("id", [""])[0]
        if not project_id_raw:
            return "<h1>Проект не выбран</h1><p class='lead'>Открой проект из списка проектов.</p>"
        project = get_project(self.config.web_db_path, int(project_id_raw))
        if project is None:
            return "<h1>Проект не найден</h1>"
        agents = load_agents(self.config.agents_path)
        tasks = list_project_tasks(self.config.web_db_path, project["id"])
        artifacts = list_project_artifacts(self.config.web_db_path, project["id"], "artifact")
        decisions = list_project_artifacts(self.config.web_db_path, project["id"], "decision")
        materials = recent_materials(self.config.materials_db_path, 100, project["id"])
        available_materials = [
            material
            for material in recent_materials(self.config.materials_db_path, 100)
            if material["project_id"] in (None, project["id"])
        ]
        return f"""
<section class="project-cockpit">
  <div>
    <p class="eyebrow">Project Cockpit</p>
    <h1>{h(project['name'])}</h1>
    <p class="lead">{h(project['goal'] or 'Цель проекта не задана.')}</p>
  </div>
  <div class="cockpit-actions">
    <a class="button-link" href="#project-task-new">Запустить задачу</a>
    <a class="button-link secondary" href="#project-artifact-new">Добавить артефакт</a>
    <a class="button-link ghost" href="/projects">Все проекты</a>
  </div>
</section>
<section class="metrics">
  {metric("Задачи", len(tasks))}
  {metric("Материалы", len(materials))}
  {metric("Артефакты", len(artifacts) + len(decisions))}
  {metric("Статус", project['status'])}
</section>
<nav class="tabs">
  <a href="#project-chat">Чат</a>
  <a href="#project-tasks">Задачи</a>
  <a href="#project-artifacts">Артефакты</a>
  <a href="#project-materials">Материалы</a>
  <a href="#project-decisions">Решения</a>
</nav>
<section id="project-chat" class="card">
  <div class="section-head">
    <div>
      <h2>Чат проекта</h2>
      <p class="lead">Быстрый запуск обсуждения или поручения внутри проекта. История настоящего диалога появится следующим слоем.</p>
    </div>
    <a class="text-action" href="#project-task-new">Создать задачу</a>
  </div>
  {project_brief(project, agents)}
</section>
<section id="project-tasks" class="card">
  <div class="section-head">
    <div><h2>Задачи агентам</h2><p class="lead">Что уже поручено AI-агентам или людям по этому проекту.</p></div>
    <a class="text-action" href="#project-task-new">Новая задача</a>
  </div>
  {project_task_list(tasks, agents)}
</section>
<section id="project-artifacts" class="card">
  <div class="section-head">
    <div><h2>Артефакты</h2><p class="lead">Результаты работы: отчеты, проверки, списки рисков, протоколы, черновики документов.</p></div>
    <a class="text-action" href="#project-artifact-new">Добавить</a>
  </div>
  {project_artifact_list(artifacts)}
</section>
<section id="project-materials" class="card">
  <h2>Материалы проекта</h2>
  <p class="lead">Материалы, закрепленные за этим проектом. Их удобно использовать как контекст для задач AI-агентам.</p>
  {materials_table(materials[:20])}
  {material_assign_form(available_materials, project['id'], f"/project?id={project['id']}")}
</section>
<section id="project-decisions" class="card">
  <div class="section-head">
    <div><h2>Решения</h2><p class="lead">Ключевые решения человека и AI-команды, которые нельзя потерять.</p></div>
    <a class="text-action" href="#project-decision-new">Добавить решение</a>
  </div>
  {project_artifact_list(decisions)}
</section>
{project_task_modal(project['id'], agents)}
{project_artifact_modal('project-artifact-new', project['id'], 'artifact', 'Новый артефакт')}
{project_artifact_modal('project-decision-new', project['id'], 'decision', 'Новое решение')}
"""

    def render_backlog(self) -> str:
        items = list_backlog_items(self.config.web_db_path)
        return f"""
<div class="page-head">
  <div>
    <h1>Backlog</h1>
    <p class="lead">Идеи и задачи развития продукта, которые появляются по ходу работы.</p>
  </div>
</div>
<section class="grid two">
  <div>{panel_title("Очередь продукта")}{backlog_list(items)}</div>
  <div>{panel_title("Добавить идею")}{backlog_form(None)}</div>
</section>
"""

    def render_knowledge(self) -> str:
        materials = recent_materials(self.config.materials_db_path, 100)
        projects = list_projects(self.config.web_db_path)
        project_names = {project["id"]: project["name"] for project in projects}
        rows = "".join(
            f"<tr><td>#{m['id']}</td><td>{h(m['title'])}<br><span class='muted'>Проект: {h(project_names.get(m['project_id'], 'Не привязан'))}</span></td><td>{h(m['source_type'])}</td><td>{h(m['telegram_id'])}</td><td>{fmt_time(m['created_at'])}</td></tr>"
            for m in materials
        )
        return f"""
<h1>База знаний</h1>
<p class="lead">Материалы, которые пользователи отправили боту: файлы, презентации, документы и ссылки.</p>
<table><thead><tr><th>ID</th><th>Материал</th><th>Тип</th><th>Пользователь</th><th>Дата</th></tr></thead><tbody>{rows}</tbody></table>
"""

    def render_history(self) -> str:
        return f"<h1>История запросов</h1><p class='lead'>Последние сообщения из памяти специалистов.</p>{history_list(recent_history(self.config.memory_db_path, 100))}"

    def render_rules(self) -> str:
        rules = list_rules(self.config.web_db_path)
        cards = "".join(rule_form(rule) for rule in rules)
        return f"<h1>Правила</h1><p class='lead'>Глобальные правила, ограничения и принципы работы AI-команды.</p>{rule_form(None)}{cards}"

    def render_settings(self) -> str:
        values = {
            "agents": self.config.agents_path,
            "prompts": self.config.prompts_path,
            "web_db": self.config.web_db_path,
            "access_db": self.config.access_db_path,
            "memory_db": self.config.memory_db_path,
            "materials_db": self.config.materials_db_path,
        }
        rows = "".join(f"<tr><td>{h(key)}</td><td>{h(value or '-')}</td></tr>" for key, value in values.items())
        users = list_web_users(self.config.web_db_path)
        user_rows = "".join(
            f"<tr><td>{h(user['username'])}</td><td>{h(user['role'])}</td><td>{'active' if user['is_active'] else 'disabled'}</td><td>{fmt_time(user['updated_at'])}</td></tr>"
            for user in users
        )
        return f"""
<h1>Настройки</h1>
<h2>Пути и базы</h2>
<table><tbody>{rows}</tbody></table>
<h2>Пользователи веб-кабинета</h2>
<table><thead><tr><th>Логин</th><th>Роль</th><th>Статус</th><th>Обновлен</th></tr></thead><tbody>{user_rows}</tbody></table>
{web_user_form()}
"""


def metric(label: str, value: int) -> str:
    return f"<div class='metric'><span>{h(label)}</span><strong>{h(value)}</strong></div>"


def panel_title(title: str) -> str:
    return f"<h2>{h(title)}</h2>"


def project_list(projects: list[dict[str, Any]], agents: list[Any]) -> str:
    if not projects:
        return "<p class='muted'>Проектов пока нет.</p>"
    known = {agent.id: agent.name for agent in agents}
    items = []
    for project in projects:
        labels = ", ".join(known.get(agent_id, agent_id) for agent_id in project["agents"]) or "агенты не выбраны"
        items.append(f"<li><strong><a href='/project?id={h(project['id'])}'>{h(project['name'])}</a></strong><span>{h(project['status'])} · {h(labels)}</span></li>")
    return f"<ul class='list'>{''.join(items)}</ul>"


def project_task_list(tasks: list[dict[str, Any]], agents: list[Any]) -> str:
    if not tasks:
        return "<p class='muted'>Задач пока нет.</p>"
    agent_names = {agent.id: agent.name for agent in agents}
    items = []
    for task in tasks:
        agent = agent_names.get(task["agent_id"], "AI-агент не выбран")
        items.append(
            f"<article class='event'><div>{h(task['status'])} · {h(agent)} · {fmt_time(task['updated_at'])}</div><p><strong>{h(task['title'])}</strong></p><p>{h(task['result'])}</p></article>"
        )
    return "".join(items)


def project_task_form(task: dict[str, Any] | None, project_id: int, agents: list[Any]) -> str:
    agent_options = ["<option value=''>Не выбран</option>"]
    for agent in agents:
        selected = "selected" if task and task["agent_id"] == agent.id else ""
        agent_options.append(f"<option value='{h(agent.id)}' {selected}>{h(agent.name)}</option>")
    return f"""
<form class="compact-form" method="post" action="/project/task/save">
  <input type="hidden" name="id" value="{h(task['id'] if task else '')}">
  <input type="hidden" name="project_id" value="{h(project_id)}">
  <label class="wide">Задача<input name="title" value="{h(task['title'] if task else '')}" placeholder="Например: проверить BOM по питанию"></label>
  <label>AI-агент<select name="agent_id">{''.join(agent_options)}</select></label>
  <label>Статус
    <select name="status">
      <option value="open">open</option>
      <option value="in_progress">in_progress</option>
      <option value="done">done</option>
      <option value="needs_human">needs_human</option>
    </select>
  </label>
  <label class="wide">Результат / заметки<textarea name="result">{h(task['result'] if task else '')}</textarea></label>
  <button type="submit">Сохранить задачу</button>
</form>
"""


def project_task_modal(project_id: int, agents: list[Any]) -> str:
    return f"""
<div id="project-task-new" class="modal">
  <button class="modal-backdrop" type="button" data-close-modal aria-label="Закрыть"></button>
  <div class="modal-card">
    <div class="modal-head">
      <div><p class="eyebrow">Запуск работы</p><h2>Новая задача проекта</h2></div>
      <button class="close" type="button" data-close-modal aria-label="Закрыть">x</button>
    </div>
    {project_task_form(None, project_id, agents)}
  </div>
</div>
"""


def project_brief(project: dict[str, Any], agents: list[Any]) -> str:
    agent_names = {agent.id: agent.name for agent in agents}
    selected = [agent_names.get(agent_id, agent_id) for agent_id in project["agents"]]
    team = ", ".join(selected) if selected else "AI-агенты пока не выбраны"
    notes = project["notes"] or "Заметки проекта пока пустые."
    return f"""
<div class="project-brief">
  <div><span>Команда</span><strong>{h(team)}</strong></div>
  <div><span>Заметки</span><p>{h(notes)}</p></div>
</div>
"""


def project_artifact_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p class='muted'>Пока пусто.</p>"
    cards = []
    for item in items:
        cards.append(
            f"<article class='artifact-card'><div><strong>{h(item['title'])}</strong><span>{h(item['status'])} · {fmt_time(item['updated_at'])}</span></div><p>{h(item['content'])}</p></article>"
        )
    return "".join(cards)


def project_artifact_form(project_id: int, artifact_type: str, title: str) -> str:
    return f"""
<form class="compact-form" method="post" action="/project/artifact/save">
  <input type="hidden" name="project_id" value="{h(project_id)}">
  <input type="hidden" name="artifact_type" value="{h(artifact_type)}">
  <label class="wide">Название<input name="title" placeholder="{h(title)}"></label>
  <label>Статус
    <select name="status">
      <option value="draft">draft</option>
      <option value="review">review</option>
      <option value="approved">approved</option>
    </select>
  </label>
  <label class="wide">Содержание<textarea name="content" placeholder="Кратко зафиксируй результат, решение или артефакт"></textarea></label>
  <button type="submit">Сохранить</button>
</form>
"""


def project_artifact_modal(modal_id: str, project_id: int, artifact_type: str, title: str) -> str:
    return f"""
<div id="{h(modal_id)}" class="modal">
  <button class="modal-backdrop" type="button" data-close-modal aria-label="Закрыть"></button>
  <div class="modal-card">
    <div class="modal-head">
      <div><p class="eyebrow">Project Cockpit</p><h2>{h(title)}</h2></div>
      <button class="close" type="button" data-close-modal aria-label="Закрыть">x</button>
    </div>
    {project_artifact_form(project_id, artifact_type, title)}
  </div>
</div>
"""


def materials_table(materials: list[dict[str, Any]]) -> str:
    if not materials:
        return "<p class='muted'>Материалов пока нет.</p>"
    rows = "".join(
        f"<tr><td>#{m['id']}</td><td>{h(m['title'])}</td><td>{h(m['source_type'])}</td><td>{fmt_time(m['created_at'])}</td></tr>"
        for m in materials
    )
    return f"<table><thead><tr><th>ID</th><th>Материал</th><th>Тип</th><th>Дата</th></tr></thead><tbody>{rows}</tbody></table>"


def material_assign_form(materials: list[dict[str, Any]], project_id: int, redirect_to: str) -> str:
    if not materials:
        return "<p class='muted'>Нет свободных материалов для привязки к проекту.</p>"
    options = "".join(
        f"<option value='{h(material['id'])}'>#{h(material['id'])} {h(material['title'])} ({h(material['source_type'])})</option>"
        for material in materials
    )
    return f"""
<form class="inline-form" method="post" action="/materials/assign">
  <input type="hidden" name="project_id" value="{h(project_id)}">
  <input type="hidden" name="redirect_to" value="{h(redirect_to)}">
  <label>Добавить материал из базы знаний<select name="material_id">{options}</select></label>
  <button type="submit">Закрепить за проектом</button>
</form>
"""


def backlog_list(items: list[dict[str, Any]]) -> str:
    if not items:
        return "<p class='muted'>Backlog пока пуст.</p>"
    cards = []
    for item in items:
        cards.append(
            f"<article class='backlog-card'><div><strong>{h(item['title'])}</strong><span>{h(item['area'])} · {h(item['priority'])} · {h(item['status'])}</span></div><p>{h(item['description'])}</p></article>"
        )
    return "".join(cards)


def backlog_form(item: dict[str, Any] | None) -> str:
    return f"""
<form class="compact-form" method="post" action="/backlog/save">
  <input type="hidden" name="id" value="{h(item['id'] if item else '')}">
  <label class="wide">Название<input name="title" value="{h(item['title'] if item else '')}"></label>
  <label>Область<input name="area" value="{h(item['area'] if item else 'product')}"></label>
  <label>Приоритет
    <select name="priority">
      <option value="high">high</option>
      <option value="medium" selected>medium</option>
      <option value="low">low</option>
    </select>
  </label>
  <label>Статус
    <select name="status">
      <option value="idea" selected>idea</option>
      <option value="planned">planned</option>
      <option value="in_progress">in_progress</option>
      <option value="done">done</option>
    </select>
  </label>
  <label class="wide">Описание<textarea name="description">{h(item['description'] if item else '')}</textarea></label>
  <button type="submit">Сохранить backlog</button>
</form>
"""


def history_list(events: list[dict[str, Any]]) -> str:
    if not events:
        return "<p class='muted'>Истории пока нет.</p>"
    items = []
    for event in events:
        content = str(event["content"])
        if len(content) > 420:
            content = content[:420] + "..."
        items.append(
            f"<article class='event'><div>{h(event['agent_id'])} · {h(event['role'])} · {fmt_time(event['created_at'])}</div><p>{h(content)}</p></article>"
        )
    return "".join(items)


def org_structure_tree(structures: list[dict[str, Any]]) -> str:
    if not structures:
        return "<p class='muted'>Структур пока нет.</p>"
    children: dict[int | None, list[dict[str, Any]]] = {}
    for structure in structures:
        children.setdefault(structure["parent_id"], []).append(structure)

    def render_branch(parent_id: int | None) -> str:
        items = []
        for structure in children.get(parent_id, []):
            items.append(
                f"<li><strong>{h(structure['name'])}</strong><span>{h(structure['description'] or 'без описания')}</span>{render_branch(structure['id'])}</li>"
            )
        return f"<ul>{''.join(items)}</ul>" if items else ""

    return f"<div class='org-tree'>{render_branch(None)}</div>"


def org_structure_sections(
    structures: list[dict[str, Any]],
    positions: list[dict[str, Any]],
    agents: list[Any],
) -> str:
    if not structures:
        return ""
    by_structure: dict[int, list[dict[str, Any]]] = {}
    for position in positions:
        by_structure.setdefault(position["structure_id"], []).append(position)
    sections = []
    for structure in structures:
        position_cards = "".join(org_position_card(position, agents) for position in by_structure.get(structure["id"], []))
        sections.append(
            f"""
<section class="org-structure">
  <div class="department-head">
    <div>
      <h2>{h(structure['name'])}</h2>
      <p class="muted">{h(structure['description'] or 'Описание не задано.')}</p>
    </div>
    <div class="structure-actions">
      <span>{len(by_structure.get(structure['id'], []))} позиций</span>
      <a class="text-action" href="#structure-edit-{h(structure['id'])}">Редактировать</a>
      <form method="post" action="/org/structure/delete" onsubmit="return confirm('Удалить структуру и ее позиции?');">
        <input type="hidden" name="id" value="{h(structure['id'])}">
        <button class="danger-button" type="submit">Удалить</button>
      </form>
    </div>
  </div>
  {org_structure_modal(structure, structures)}
  <div class="position-grid">{position_cards}</div>
  {org_position_form(None, structure['id'], agents)}
</section>
"""
        )
    return "".join(sections)


def org_position_card(position: dict[str, Any], agents: list[Any]) -> str:
    agent_name = next((agent.name for agent in agents if agent.id == position["agent_id"]), "")
    agent_line = f"<span>AI-агент: {h(agent_name)}</span>" if agent_name else "<span>AI-агент не привязан</span>"
    return f"""
<article class="position-card">
  <strong>{h(position['title'])}</strong>
  <span>{h(position['department'] or 'отдел не задан')}</span>
  {agent_line}
  <p>{h(position['notes'])}</p>
  <div class="position-actions">
    <a class="text-action" href="#position-edit-{h(position['id'])}">Редактировать</a>
    <form method="post" action="/org/position/delete" onsubmit="return confirm('Удалить позицию?');">
      <input type="hidden" name="id" value="{h(position['id'])}">
      <button class="danger-button" type="submit">Удалить</button>
    </form>
  </div>
</article>
{org_position_modal(position, position['structure_id'], agents)}
"""


def org_structure_form(structure: dict[str, Any] | None, structures: list[dict[str, Any]]) -> str:
    parent_options = ["<option value=''>Верхний уровень</option>"]
    current_id = structure["id"] if structure else None
    for item in structures:
        if item["id"] == current_id:
            continue
        selected = "selected" if structure and structure["parent_id"] == item["id"] else ""
        parent_options.append(f"<option value='{h(item['id'])}' {selected}>{h(item['name'])}</option>")
    return f"""
<form class="compact-form" method="post" action="/org/structure/save">
  <input type="hidden" name="id" value="{h(structure['id'] if structure else '')}">
  <label>Название<input name="name" value="{h(structure['name'] if structure else '')}" placeholder="Например: Производственный блок"></label>
  <label>Родительская структура<select name="parent_id">{''.join(parent_options)}</select></label>
  <label>Порядок<input name="sort_order" value="{h(structure['sort_order'] if structure else '0')}"></label>
  <label class="wide">Описание<textarea name="description">{h(structure['description'] if structure else '')}</textarea></label>
  <button type="submit">Сохранить структуру</button>
</form>
"""


def org_structure_modal(structure: dict[str, Any], structures: list[dict[str, Any]]) -> str:
    modal_id = f"structure-edit-{h(structure['id'])}"
    return f"""
<div class="modal" id="{modal_id}">
  <button class="modal-backdrop" type="button" data-close-modal aria-label="Закрыть"></button>
  <div class="modal-card">
    <div class="modal-head">
      <div>
        <p class="eyebrow">Редактирование структуры</p>
        <h2>{h(structure['name'])}</h2>
      </div>
      <button class="close" type="button" data-close-modal aria-label="Закрыть">x</button>
    </div>
    {org_structure_form(structure, structures)}
  </div>
</div>
"""


def org_position_form(position: dict[str, Any] | None, structure_id: int, agents: list[Any]) -> str:
    agent_options = ["<option value=''>Не привязан</option>"]
    for agent in agents:
        selected = "selected" if position and position["agent_id"] == agent.id else ""
        agent_options.append(f"<option value='{h(agent.id)}' {selected}>{h(agent.name)}</option>")
    return f"""
<form class="compact-form position-form" method="post" action="/org/position/save">
  <input type="hidden" name="id" value="{h(position['id'] if position else '')}">
  <input type="hidden" name="structure_id" value="{h(structure_id)}">
  <label>Должность<input name="title" value="{h(position['title'] if position else '')}" placeholder="Например: Mechanical Design Lead"></label>
  <label>Отдел<input name="department" value="{h(position['department'] if position else '')}"></label>
  <label>AI-агент<select name="agent_id">{''.join(agent_options)}</select></label>
  <label>Порядок<input name="sort_order" value="{h(position['sort_order'] if position else '0')}"></label>
  <label class="wide">Заметки<textarea name="notes">{h(position['notes'] if position else '')}</textarea></label>
  <button type="submit">Добавить позицию</button>
</form>
"""


def org_position_modal(position: dict[str, Any], structure_id: int, agents: list[Any]) -> str:
    modal_id = f"position-edit-{h(position['id'])}"
    return f"""
<div class="modal" id="{modal_id}">
  <button class="modal-backdrop" type="button" data-close-modal aria-label="Закрыть"></button>
  <div class="modal-card">
    <div class="modal-head">
      <div>
        <p class="eyebrow">Редактирование позиции</p>
        <h2>{h(position['title'])}</h2>
      </div>
      <button class="close" type="button" data-close-modal aria-label="Закрыть">x</button>
    </div>
    {org_position_form(position, structure_id, agents)}
  </div>
</div>
"""


def agent_department_section(department: str, agents: list[Any], prompts_path: Path) -> str:
    cards = "".join(agent_card(agent, load_agent_prompt(agent.id, prompts_path)) for agent in agents)
    return f"""
<section class="department">
  <div class="department-head">
    <h2>{h(department)}</h2>
    <span>{len(agents)} специалистов</span>
  </div>
  <div class="agent-grid drop-zone" data-department="{h(department)}">{cards}</div>
</section>
"""


def agent_card(agent: Any, prompt: str) -> str:
    keywords = ", ".join(agent.keywords[:4]) or "ключевые слова не заданы"
    artifacts = ", ".join(agent.expected_artifacts[:3]) or "артефакты не заданы"
    modal_id = f"agent-{h(agent.id)}"
    return f"""
<article class="agent-card" data-agent-id="{h(agent.id)}">
  <div class="agent-top">
    <span class="agent-id"><span class="drag-handle" draggable="true" title="Перетащить карточку" aria-label="Перетащить карточку">::</span> {h(agent.id)}</span>
    <a class="icon-button" href="#{modal_id}" aria-label="Открыть настройки">Настройки</a>
  </div>
  <h3>{h(agent.name)}</h3>
  <p>{h(agent.focus)}</p>
  <dl>
    <dt>Ключи</dt><dd>{h(keywords)}</dd>
    <dt>Артефакты</dt><dd>{h(artifacts)}</dd>
  </dl>
</article>
{agent_modal(agent.id, agent.name, agent.department, agent.focus, agent.keywords, agent.expected_artifacts, prompt)}
"""


def agent_modal(
    agent_id: str,
    name: str,
    department: str,
    focus: str,
    keywords: list[str],
    artifacts: list[str],
    prompt: str,
) -> str:
    title = "Новый агент" if not agent_id else name
    readonly = "readonly" if agent_id else ""
    modal_id = f"agent-{h(agent_id)}" if agent_id else "agent-new"
    return f"""
<div class="modal" id="{modal_id}">
  <button class="modal-backdrop" type="button" data-close-modal aria-label="Закрыть"></button>
  <form class="modal-card" method="post" action="/agents/save">
    <div class="modal-head">
      <div>
        <p class="eyebrow">Карточка специалиста</p>
        <h2>{h(title)}</h2>
      </div>
      <button class="close" type="button" data-close-modal aria-label="Закрыть">x</button>
    </div>
    <div class="fields">
      <label>ID<input name="id" value="{h(agent_id)}" {readonly}></label>
      <label>Имя роли<input name="name" value="{h(name)}"></label>
      <label>Отдел<input name="department" value="{h(department)}"></label>
      <input type="hidden" name="order" value="0">
      <label>Ожидаемые артефакты<input name="expected_artifacts" value="{h(', '.join(artifacts))}"></label>
      <label class="wide">Фокус<textarea name="focus">{h(focus)}</textarea></label>
      <label class="wide">Ключевые слова<input name="keywords" value="{h(', '.join(keywords))}"></label>
      <label class="wide">Ролевые инструкции<textarea name="prompt" rows="10">{h(prompt)}</textarea></label>
    </div>
    <button type="submit">Сохранить агента</button>
  </form>
</div>
"""


def project_form(project: dict[str, Any] | None, agents: list[Any]) -> str:
    selected = set(project["agents"]) if project else set()
    checkboxes = "".join(
        f"<label class='check'><input type='checkbox' name='agents' value='{h(agent.id)}' {'checked' if agent.id in selected else ''}> {h(agent.name)}</label>"
        for agent in agents
    )
    return f"""
<form class="card" method="post" action="/projects/save">
  <input type="hidden" name="id" value="{h(project['id'] if project else '')}">
  <div class="form-title-row">
    <h2>{h(project['name'] if project else 'Новый проект')}</h2>
    {f'<a class="text-action" href="/project?id={h(project["id"])}">Открыть workspace</a>' if project else ''}
  </div>
  <div class="fields">
    <label>Название<input name="name" value="{h(project['name'] if project else '')}"></label>
    <label>Статус<input name="status" value="{h(project['status'] if project else 'active')}"></label>
    <label class="wide">Цель<textarea name="goal">{h(project['goal'] if project else '')}</textarea></label>
    <div class="wide checks">{checkboxes}</div>
    <label class="wide">Заметки<textarea name="notes" rows="6">{h(project['notes'] if project else '')}</textarea></label>
  </div>
  <button type="submit">Сохранить проект</button>
</form>
"""


def rule_form(rule: dict[str, Any] | None) -> str:
    return f"""
<form class="card" method="post" action="/rules/save">
  <input type="hidden" name="id" value="{h(rule['id'] if rule else '')}">
  <h2>{h(rule['title'] if rule else 'Новое правило')}</h2>
  <div class="fields">
    <label>Название<input name="title" value="{h(rule['title'] if rule else '')}"></label>
    <label>Область<input name="scope" value="{h(rule['scope'] if rule else 'global')}"></label>
    <label class="wide">Правило<textarea name="content" rows="6">{h(rule['content'] if rule else '')}</textarea></label>
  </div>
  <button type="submit">Сохранить правило</button>
</form>
"""


def web_user_form() -> str:
    return """
<form class="card" method="post" action="/users/save">
  <h2>Добавить или обновить пользователя</h2>
  <div class="fields">
    <label>Логин<input name="username"></label>
    <label>Пароль<input name="password" type="password" placeholder="оставь пустым, чтобы не менять"></label>
    <label>Роль
      <select name="role">
        <option value="owner">owner</option>
        <option value="admin">admin</option>
        <option value="member" selected>member</option>
        <option value="viewer">viewer</option>
      </select>
    </label>
    <label>Статус
      <select name="is_active">
        <option value="1" selected>active</option>
        <option value="0">disabled</option>
      </select>
    </label>
  </div>
  <button type="submit">Сохранить пользователя</button>
</form>
"""


AGENTS_DRAG_SCRIPT = """
<script>
(() => {
  const status = document.getElementById('layout-status');
  const zones = Array.from(document.querySelectorAll('.drop-zone'));
  let dragged = null;

  function setStatus(text, state = '') {
    if (!status) return;
    status.textContent = text;
    status.dataset.state = state;
  }

  function cardsIn(zone) {
    return Array.from(zone.querySelectorAll('.agent-card'));
  }

  function placeholderBefore(zone, y) {
    return cardsIn(zone).find(card => {
      const box = card.getBoundingClientRect();
      return y < box.top + box.height / 2;
    });
  }

  async function saveLayout() {
    const agents = [];
    zones.forEach(zone => {
      cardsIn(zone).forEach((card, index) => {
        agents.push({
          id: card.dataset.agentId,
          department: zone.dataset.department,
          order: index,
        });
      });
    });
    setStatus('сохраняю...', 'saving');
    try {
      const response = await fetch('/agents/layout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({agents}),
      });
      if (!response.ok) throw new Error(await response.text());
      setStatus('порядок сохранен', 'ok');
    } catch (error) {
      setStatus('не удалось сохранить', 'error');
      console.error(error);
    }
  }

  document.querySelectorAll('.drag-handle').forEach(handle => {
    const card = handle.closest('.agent-card');
    handle.addEventListener('dragstart', event => {
      dragged = card;
      card.classList.add('dragging');
      event.dataTransfer.effectAllowed = 'move';
      event.dataTransfer.setData('text/plain', card.dataset.agentId);
    });
    handle.addEventListener('dragend', () => {
      card.classList.remove('dragging');
      zones.forEach(zone => zone.classList.remove('drag-over'));
      dragged = null;
    });
  });

  zones.forEach(zone => {
    zone.addEventListener('dragover', event => {
      event.preventDefault();
      zone.classList.add('drag-over');
      if (!dragged) return;
      const before = placeholderBefore(zone, event.clientY);
      if (before && before !== dragged) {
        zone.insertBefore(dragged, before);
      } else if (!before) {
        zone.appendChild(dragged);
      }
    });
    zone.addEventListener('dragleave', () => zone.classList.remove('drag-over'));
    zone.addEventListener('drop', event => {
      event.preventDefault();
      zone.classList.remove('drag-over');
      saveLayout();
    });
  });
})();
</script>
"""


MODAL_SCRIPT = """
<script>
(() => {
  function closeModalWithoutScroll() {
    const y = window.scrollY;
    const modal = document.querySelector('.modal:target') || document.querySelector('.modal.is-open');
    if (modal) {
      modal.classList.add('is-closed');
    }
    history.replaceState(null, '', window.location.pathname + window.location.search);
    window.scrollTo(0, y);
  }

  document.addEventListener('click', event => {
    const opener = event.target.closest('a[href^="#"]');
    if (opener) {
      const target = document.querySelector(opener.getAttribute('href'));
      if (target && target.classList.contains('modal')) {
        target.classList.remove('is-closed');
        target.classList.add('is-open');
      }
    }
    const closer = event.target.closest('[data-close-modal]');
    if (!closer) return;
    event.preventDefault();
    closeModalWithoutScroll();
  });

  document.addEventListener('keydown', event => {
    if (event.key === 'Escape' && window.location.hash) {
      event.preventDefault();
      closeModalWithoutScroll();
    }
  });
})();
</script>
"""


CSS = """
:root { color-scheme: light; --ink: #1b2430; --muted: #647084; --line: #d9dee7; --bg: #f5f7fa; --panel: #ffffff; --accent: #3457d5; --ok: #1f8a5b; }
* { box-sizing: border-box; }
body { margin: 0; font-family: Inter, Segoe UI, Arial, sans-serif; color: var(--ink); background: var(--bg); display: flex; min-height: 100vh; }
aside { width: 252px; background: #111827; color: #fff; padding: 24px 18px; position: fixed; inset: 0 auto 0 0; }
.brand { font-weight: 800; font-size: 24px; line-height: 1.05; margin-bottom: 28px; }
.brand span { color: #a8b3c7; font-size: 14px; font-weight: 600; }
nav { display: grid; gap: 6px; }
nav a { color: #cbd5e1; text-decoration: none; padding: 11px 12px; border-radius: 8px; font-weight: 650; }
nav a.active, nav a:hover { background: #263244; color: #fff; }
main { margin-left: 252px; padding: 30px; width: calc(100% - 252px); max-width: 1420px; }
h1 { font-size: 34px; margin: 0 0 8px; letter-spacing: 0; }
h2 { font-size: 19px; margin: 0 0 16px; letter-spacing: 0; }
h3 { font-size: 18px; margin: 0; letter-spacing: 0; }
.lead, .muted { color: var(--muted); }
.page-head { display: flex; align-items: center; justify-content: space-between; gap: 18px; margin-bottom: 18px; }
.head-actions { display: flex; align-items: center; gap: 12px; }
.save-status { color: var(--muted); font-size: 13px; font-weight: 800; white-space: nowrap; }
.save-status[data-state="saving"] { color: #9a6a00; }
.save-status[data-state="error"] { color: #b42318; }
.save-status[data-state="ok"] { color: var(--ok); }
.button-link { display: inline-flex; align-items: center; justify-content: center; min-height: 42px; padding: 0 14px; background: var(--accent); color: #fff; text-decoration: none; border-radius: 6px; font-weight: 800; white-space: nowrap; }
.button-link.secondary { background: #111827; }
.button-link.ghost { background: #fff; color: var(--accent); border: 1px solid #cbd5e1; }
.project-cockpit { min-height: 190px; background: linear-gradient(120deg, rgba(17,24,39,.92), rgba(52,87,213,.76)), url('https://images.unsplash.com/photo-1581092921461-eab62e97a780?q=80&w=1600&auto=format&fit=crop'); background-size: cover; background-position: center; color: #fff; padding: 28px; display: flex; align-items: flex-end; justify-content: space-between; gap: 18px; margin-bottom: 18px; border-radius: 8px; }
.project-cockpit .lead { color: #e2e8f0; max-width: 760px; }
.cockpit-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.tabs { display: flex; gap: 8px; flex-wrap: wrap; margin: 0 0 18px; }
.tabs a { background: #fff; border: 1px solid var(--line); color: #344054; text-decoration: none; padding: 10px 13px; border-radius: 6px; font-weight: 800; }
.tabs a:hover { border-color: #94a3ff; color: var(--accent); }
.section-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 14px; margin-bottom: 14px; }
.section-head h2 { margin-bottom: 4px; }
.project-brief { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 2fr); gap: 14px; }
.project-brief div { background: #f8fafc; border: 1px solid var(--line); border-radius: 8px; padding: 14px; }
.project-brief span { display: block; color: var(--muted); font-size: 13px; font-weight: 800; margin-bottom: 6px; }
.project-brief p { margin: 0; color: #475467; line-height: 1.45; }
.artifact-card { border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 10px; background: #fff; }
.artifact-card span { display: block; color: var(--muted); font-size: 13px; font-weight: 700; margin-top: 4px; }
.artifact-card p { margin: 10px 0 0; color: #475467; line-height: 1.45; white-space: pre-wrap; }
.hero { min-height: 230px; background: linear-gradient(120deg, rgba(26,38,65,.88), rgba(45,72,144,.72)), url('https://images.unsplash.com/photo-1517048676732-d65bc937f952?q=80&w=1600&auto=format&fit=crop'); background-size: cover; background-position: center; color: #fff; padding: 32px; display: flex; align-items: flex-end; justify-content: space-between; margin-bottom: 18px; }
.hero h1 { max-width: 760px; }
.hero p { max-width: 700px; color: #e2e8f0; }
.eyebrow { text-transform: uppercase; font-size: 12px; font-weight: 800; letter-spacing: 0; margin: 0 0 8px; }
.status { background: rgba(255,255,255,.14); border: 1px solid rgba(255,255,255,.28); padding: 10px 12px; border-radius: 8px; white-space: nowrap; }
.metrics { display: grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap: 14px; margin-bottom: 18px; }
.metric, .card, .grid > div { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 18px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.metric span { color: var(--muted); display: block; font-weight: 650; }
.metric strong { font-size: 34px; line-height: 1.15; }
.grid.two { display: grid; grid-template-columns: 1fr 1fr; gap: 18px; }
.card { margin: 18px 0; }
.form-title-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin-bottom: 16px; }
.form-title-row h2 { margin: 0; }
.department { margin: 22px 0 30px; }
.department-head { display: flex; justify-content: space-between; align-items: baseline; gap: 16px; margin-bottom: 12px; border-bottom: 1px solid var(--line); padding-bottom: 8px; }
.department-head h2 { margin: 0; }
.department-head span { color: var(--muted); font-weight: 700; }
.agent-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 14px; min-height: 128px; border: 1px dashed transparent; border-radius: 8px; padding: 2px; }
.agent-grid.drag-over { border-color: #94a3ff; background: #f1f5ff; }
.agent-card { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 16px; min-height: 245px; display: grid; grid-template-rows: auto auto 1fr auto; gap: 12px; box-shadow: 0 1px 2px rgba(16,24,40,.04); }
.agent-card.dragging { opacity: .58; outline: 2px solid #94a3ff; }
.agent-card p { margin: 0; color: #475467; line-height: 1.45; }
.agent-top { display: flex; justify-content: space-between; align-items: center; gap: 10px; }
.agent-id { color: var(--muted); font-size: 12px; font-weight: 800; text-transform: uppercase; }
.drag-handle { display: inline-flex; align-items: center; justify-content: center; width: 22px; height: 22px; margin-right: 4px; color: #98a2b3; font-weight: 900; border-radius: 6px; cursor: grab; user-select: none; }
.drag-handle:hover { background: #eef2f7; color: #475467; }
.drag-handle:active { cursor: grabbing; background: #dbe4f0; }
.icon-button { color: var(--accent); text-decoration: none; font-size: 13px; font-weight: 800; }
.agent-card dl { display: grid; grid-template-columns: 86px 1fr; gap: 7px 10px; margin: 0; font-size: 13px; }
.agent-card dt { color: var(--muted); font-weight: 800; }
.agent-card dd { margin: 0; color: #344054; }
.modal { display: none; position: fixed; inset: 0; z-index: 20; }
.modal:target { display: block; }
.modal.is-closed { display: none; }
.modal-backdrop { position: absolute; inset: 0; z-index: 0; width: 100%; height: 100%; border: 0; padding: 0; margin: 0; background: rgba(15,23,42,.58); cursor: default; }
.modal-card { position: relative; z-index: 1; width: min(920px, calc(100vw - 32px)); max-height: calc(100vh - 48px); overflow: auto; margin: 24px auto; background: #fff; border-radius: 8px; padding: 22px; box-shadow: 0 24px 90px rgba(0,0,0,.32); }
.modal-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; margin-bottom: 16px; }
.modal-head h2 { margin: 0; }
.close { margin: 0; padding: 0; border: 0; background: transparent; color: var(--muted); text-decoration: none; font-weight: 900; font-size: 20px; line-height: 1; cursor: pointer; width: 36px; height: 36px; display: inline-flex; align-items: center; justify-content: center; border-radius: 6px; }
.close:hover { background: #eef2f7; color: #344054; }
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 6px; font-weight: 700; color: #344054; }
input, textarea, select { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 11px; font: inherit; color: var(--ink); background: #fff; }
textarea { resize: vertical; min-height: 86px; }
.wide { grid-column: 1 / -1; }
.checks { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 8px; }
.check { display: flex; align-items: center; gap: 8px; font-weight: 650; }
.check input { width: auto; }
button { margin-top: 14px; border: 0; background: var(--accent); color: #fff; border-radius: 6px; padding: 11px 14px; font-weight: 800; cursor: pointer; }
table { width: 100%; border-collapse: collapse; background: #fff; border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
th, td { text-align: left; padding: 12px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { background: #eef2f7; font-size: 13px; color: #344054; }
.list { list-style: none; padding: 0; margin: 0; display: grid; gap: 12px; }
.list li, .org li { display: grid; gap: 4px; padding-bottom: 12px; border-bottom: 1px solid var(--line); }
.list span, .org span, .event div { color: var(--muted); font-size: 13px; }
.event { border-bottom: 1px solid var(--line); padding: 12px 0; }
.event p { margin: 6px 0 0; line-height: 1.45; }
.backlog-card { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 14px; margin-bottom: 10px; display: grid; gap: 8px; }
.backlog-card span { display: block; color: var(--muted); font-size: 13px; font-weight: 700; margin-top: 3px; }
.backlog-card p { margin: 0; color: #475467; line-height: 1.4; }
.org { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 20px; }
.cto { display: inline-block; background: #e7efff; border: 1px solid #b7c8ff; color: #183a8f; padding: 12px 16px; border-radius: 8px; font-weight: 800; margin-bottom: 18px; }
.org ul { margin: 0; padding-left: 24px; display: grid; gap: 12px; }
.org-tree ul { list-style: none; margin: 0; padding-left: 18px; display: grid; gap: 12px; border-left: 2px solid #dbe4f0; }
.org-tree > ul { padding-left: 0; border-left: 0; }
.org-tree li { display: grid; gap: 4px; }
.org-tree span { color: var(--muted); font-size: 13px; }
.org-structure { margin: 26px 0; }
.position-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; margin-bottom: 14px; }
.position-card { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 14px; display: grid; gap: 7px; min-height: 132px; }
.position-card strong { font-size: 17px; line-height: 1.25; }
.position-card span { color: var(--muted); font-size: 13px; font-weight: 700; }
.position-card p { margin: 0; color: #475467; line-height: 1.35; }
.structure-actions, .position-actions { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; justify-content: flex-end; }
.position-actions { justify-content: flex-start; margin-top: 4px; }
.structure-actions form, .position-actions form { margin: 0; }
.text-action { color: var(--accent); text-decoration: none; font-weight: 800; font-size: 13px; }
.danger-button { margin: 0; background: #fff1f1; color: #b42318; border: 1px solid #ffd0d0; padding: 7px 10px; font-size: 13px; }
.danger-button:hover { background: #ffe4e4; }
.compact-form { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 14px; display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; }
.modal-card .compact-form { border: 0; padding: 0; }
.compact-form button { width: fit-content; }
.inline-form { margin-top: 14px; display: grid; grid-template-columns: minmax(0, 1fr) auto; gap: 12px; align-items: end; }
.inline-form button { margin: 0; white-space: nowrap; }
.position-form { margin-top: 12px; }
.login-page { display: grid; place-items: center; background: #111827; }
.login-main { margin: 0; width: min(460px, calc(100vw - 32px)); padding: 0; }
.login-card { background: #fff; border-radius: 8px; padding: 28px; display: grid; gap: 14px; box-shadow: 0 20px 80px rgba(0,0,0,.28); }
.login-card h1 { font-size: 28px; }
.error { background: #fff1f1; color: #9f1c1c; border: 1px solid #ffd0d0; padding: 10px 12px; border-radius: 6px; margin: 0; }
@media (max-width: 1100px) { .agent-grid, .position-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
@media (max-width: 900px) { body { display:block; } aside { position: static; width: 100%; } main { margin: 0; width: 100%; padding: 18px; } .metrics, .grid.two, .fields, .checks, .agent-grid, .position-grid, .compact-form, .project-brief, .inline-form { grid-template-columns: 1fr; } .hero, .page-head, .project-cockpit, .section-head { display: block; } .button-link { margin-top: 12px; } .cockpit-actions { justify-content: flex-start; } }
"""


def run_web(config: WebConfig) -> None:
    init_web_db(config.web_db_path)
    ensure_materials_db_project_columns(config.materials_db_path)
    seed_admin_user(config.web_db_path, config.password)
    ControlCenterHandler.config = config
    server = ThreadingHTTPServer((config.host, config.port), ControlCenterHandler)
    print(f"AI Team Control Center running on http://{config.host}:{config.port}")
    server.serve_forever()
