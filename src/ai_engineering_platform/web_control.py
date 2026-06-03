from __future__ import annotations

from dataclasses import dataclass
from html import escape
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


def recent_materials(db_path: Path | None, limit: int = 50) -> list[dict[str, Any]]:
    connection = connect_existing(db_path)
    if connection is None:
        return []
    with connection:
        rows = connection.execute(
            """
            SELECT id, telegram_id, source_type, title, source_url, created_at
            FROM project_materials
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [
        {"id": row[0], "telegram_id": row[1], "source_type": row[2], "title": row[3], "source_url": row[4], "created_at": row[5]}
        for row in rows
    ]


def render_page(config: WebConfig, active: str, body: str) -> bytes:
    nav = [
        ("dashboard", "Панель"),
        ("agents", "Агенты"),
        ("org", "Штат"),
        ("projects", "Проекты"),
        ("knowledge", "База знаний"),
        ("history", "История"),
        ("rules", "Правила"),
        ("settings", "Настройки"),
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
        if not self.authorized():
            self.request_auth()
            return
        path = parse.urlparse(self.path).path.strip("/") or "dashboard"
        routes = {
            "dashboard": self.render_dashboard,
            "agents": self.render_agents,
            "org": self.render_org,
            "projects": self.render_projects,
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
        if not self.authorized():
            self.request_auth()
            return
        path = parse.urlparse(self.path).path
        form = self.read_form()
        try:
            if path == "/agents/save":
                save_agent(self.config.agents_path, self.config.prompts_path, form)
                self.redirect("/agents")
                return
            if path == "/projects/save":
                save_project(self.config.web_db_path, form)
                self.redirect("/projects")
                return
            if path == "/rules/save":
                save_rule(self.config.web_db_path, form)
                self.redirect("/rules")
                return
        except Exception as exc:
            self.respond(render_page(self.config, "settings", f"<h1>Ошибка</h1><p>{h(exc)}</p>"), HTTPStatus.BAD_REQUEST)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def authorized(self) -> bool:
        header = self.headers.get("Authorization", "")
        if not header.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(header.removeprefix("Basic ")).decode("utf-8")
        except Exception:
            return False
        _, _, password = decoded.partition(":")
        return password == self.config.password

    def request_auth(self) -> None:
        self.send_response(HTTPStatus.UNAUTHORIZED)
        self.send_header("WWW-Authenticate", 'Basic realm="AI Team Control Center"')
        self.end_headers()

    def read_form(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length).decode("utf-8")
        return parse.parse_qs(raw)

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
        agents = load_agents(self.config.agents_path)
        cards = []
        for agent in agents:
            prompt = load_agent_prompt(agent.id, self.config.prompts_path)
            cards.append(agent_form(agent.id, agent.name, agent.focus, agent.keywords, agent.expected_artifacts, prompt))
        cards.append(agent_form("", "", "", [], [], ""))
        return f"<h1>Агенты</h1><p class='lead'>Карточки должностей, фокус, артефакты и ролевые инструкции.</p>{''.join(cards)}"

    def render_org(self) -> str:
        agents = load_agents(self.config.agents_path)
        items = "".join(f"<li><strong>{h(agent.name)}</strong><span>{h(agent.focus)}</span></li>" for agent in agents)
        return f"""
<h1>Штатная структура</h1>
<p class="lead">Первый MVP показывает текущий штат AI-сотрудников. Следующий шаг - связи подчинения и эскалации.</p>
<div class="org">
  <div class="cto">CTO / Human Approval</div>
  <ul>{items}</ul>
</div>
"""

    def render_projects(self) -> str:
        agents = load_agents(self.config.agents_path)
        projects = list_projects(self.config.web_db_path)
        existing = "".join(project_form(project, agents) for project in projects)
        return f"<h1>Проекты</h1><p class='lead'>Проект связывает цель, AI-сотрудников, заметки и будущие материалы.</p>{project_form(None, agents)}{existing}"

    def render_knowledge(self) -> str:
        materials = recent_materials(self.config.materials_db_path, 100)
        rows = "".join(
            f"<tr><td>#{m['id']}</td><td>{h(m['title'])}</td><td>{h(m['source_type'])}</td><td>{h(m['telegram_id'])}</td><td>{fmt_time(m['created_at'])}</td></tr>"
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
        return f"<h1>Настройки</h1><table><tbody>{rows}</tbody></table>"


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
        items.append(f"<li><strong>{h(project['name'])}</strong><span>{h(project['status'])} · {h(labels)}</span></li>")
    return f"<ul class='list'>{''.join(items)}</ul>"


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


def agent_form(agent_id: str, name: str, focus: str, keywords: list[str], artifacts: list[str], prompt: str) -> str:
    title = "Новый агент" if not agent_id else name
    readonly = "readonly" if agent_id else ""
    return f"""
<form class="card" method="post" action="/agents/save">
  <h2>{h(title)}</h2>
  <div class="fields">
    <label>ID<input name="id" value="{h(agent_id)}" {readonly}></label>
    <label>Имя роли<input name="name" value="{h(name)}"></label>
    <label class="wide">Фокус<textarea name="focus">{h(focus)}</textarea></label>
    <label>Ключевые слова<input name="keywords" value="{h(', '.join(keywords))}"></label>
    <label>Ожидаемые артефакты<input name="expected_artifacts" value="{h(', '.join(artifacts))}"></label>
    <label class="wide">Ролевые инструкции<textarea name="prompt" rows="8">{h(prompt)}</textarea></label>
  </div>
  <button type="submit">Сохранить агента</button>
</form>
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
  <h2>{h(project['name'] if project else 'Новый проект')}</h2>
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
.lead, .muted { color: var(--muted); }
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
.fields { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
label { display: grid; gap: 6px; font-weight: 700; color: #344054; }
input, textarea { width: 100%; border: 1px solid #cbd5e1; border-radius: 6px; padding: 10px 11px; font: inherit; color: var(--ink); background: #fff; }
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
.org { background: #fff; border: 1px solid var(--line); border-radius: 8px; padding: 20px; }
.cto { display: inline-block; background: #e7efff; border: 1px solid #b7c8ff; color: #183a8f; padding: 12px 16px; border-radius: 8px; font-weight: 800; margin-bottom: 18px; }
.org ul { margin: 0; padding-left: 24px; display: grid; gap: 12px; }
@media (max-width: 900px) { body { display:block; } aside { position: static; width: 100%; } main { margin: 0; width: 100%; padding: 18px; } .metrics, .grid.two, .fields, .checks { grid-template-columns: 1fr; } .hero { display: block; } }
"""


def run_web(config: WebConfig) -> None:
    init_web_db(config.web_db_path)
    ControlCenterHandler.config = config
    server = ThreadingHTTPServer((config.host, config.port), ControlCenterHandler)
    print(f"AI Team Control Center running on http://{config.host}:{config.port}")
    server.serve_forever()
