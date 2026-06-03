from __future__ import annotations

from dataclasses import dataclass, field
import json
import os
import time
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib import parse, request
from urllib.error import HTTPError, URLError

from .access_control import AccessStore, ROLES, seed_owner_users
from .agents import AgentProfile, load_agents
from .conversation_memory import ConversationMemory, MemoryEvent
from .llm import DeepSeekLLMClient, LLMClient, MockLLMClient, OpenAICompatibleLLMClient
from .prompts import load_agent_prompt
from .project_materials import ProjectMaterial, ProjectMaterials, extract_file_text, extract_urls, fetch_url_text


HELP_TEXT = """AI Team of Engineers

Это бот с AI-сотрудниками инженерной команды.

Основной сценарий:
1. Нажми "Специалисты".
2. Выбери нужного специалиста.
3. Нажми "Начать чат".
4. Пиши обычным текстом.

Команды:
/start - главное меню
/help - справка
/whoami - показать твой Telegram user id
/status - статус бота
/memory - статус памяти
/forget - очистить память выбранного специалиста
/materials - список загруженных материалов
/clear_materials - очистить твои материалы проекта
/agents - список специалистов
/ask <agent_id> <вопрос> - задать вопрос специалисту
/meeting <тема> - совещание всех MVP-агентов
/meeting <agent_id,agent_id> <тема> - совещание выбранных агентов

Материалы проекта:
- пришли Word .docx, PowerPoint .pptx, .txt, .md, .csv или .tsv файлом
- пришли сообщение со ссылкой http/https
- затем выбери специалиста и задай вопрос по материалам

Администрирование:
/users
/allow <telegram_id> [owner|admin|member|viewer]
/deny <telegram_id>
/role <telegram_id> <owner|admin|member|viewer]
"""


@dataclass(frozen=True)
class AgentCard:
    id: str
    label: str
    role: str
    description: str
    scope: str
    out_of_scope_redirect: str
    aliases: tuple[str, ...] = ()


AGENT_CARDS = {
    "systems": AgentCard(
        id="systems",
        label="Системный архитектор",
        role="Systems Engineering / Chief Architect",
        description="Смотрит на робота как на систему: требования, интерфейсы, архитектура, риски между направлениями.",
        scope="системная архитектура, требования, интерфейсы, междисциплинарные риски, готовность к design review",
        out_of_scope_redirect="если вопрос слишком детальный по электрике, производству или документации, предложи подключить профильного специалиста",
        aliases=("system", "architect", "архитектор", "системщик", "системный"),
    ),
    "electrical": AgentCard(
        id="electrical",
        label="Ведущий электрик",
        role="Electrical Lead Engineer",
        description="Питание, защиты, шкафы, кабели, разъемы, электрический BOM, FAT/SAT по электрике.",
        scope="электрика, питание, защиты, заземление, кабели, разъемы, шкафы, карты сигналов, электрический BOM",
        out_of_scope_redirect="если вопрос про механику, производство, firmware, сертификацию или бизнес, скажи что это вне роли электрика и предложи нужного специалиста",
        aliases=("electric", "электрик", "электрика"),
    ),
    "manufacturing": AgentCard(
        id="manufacturing",
        label="Технолог производства",
        role="Manufacturing Engineering",
        description="Пилотная сборка, технологические карты, оснастка, контроль, калибровка, производственные blockers.",
        scope="сборка, технологические карты, оснастка, контрольные операции, входной контроль, калибровка, pilot production readiness",
        out_of_scope_redirect="если вопрос про схемы, firmware, системную архитектуру или сертификацию, скажи что это вне роли технолога и предложи нужного специалиста",
        aliases=("production", "производство", "технолог"),
    ),
    "certification_docs": AgentCard(
        id="certification_docs",
        label="Документация и сертификация",
        role="Certification and Technical Documentation",
        description="Паспорта, РЭ, инструкции, ПМИ, протоколы, risk assessment, комплектность документации.",
        scope="техническая документация, эксплуатационные документы, ПМИ, протоколы, risk assessment, traceability, сертификационная готовность",
        out_of_scope_redirect="если вопрос про проектирование схем, сборку, firmware или архитектурное решение, скажи что это вне роли документации/сертификации и предложи профильного специалиста",
        aliases=("certification", "docs", "documentation", "сертификация", "документация"),
    ),
}

AGENT_ALIASES = {
    alias: card.id
    for card in AGENT_CARDS.values()
    for alias in (card.id, *card.aliases)
}


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    agents_path: Path = Path("configs/agents.json")
    prompts_path: Path = Path("prompts")
    mode: str = "mock-llm"
    allowed_user_ids: set[int] | None = None
    owner_user_ids: set[int] | None = None
    access_db_path: Path | None = None
    memory_db_path: Path | None = None
    memory_depth: int = 10
    materials_db_path: Path | None = None
    materials_files_dir: Path | None = None
    materials_depth: int = 5
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot.")
        allowed_ids_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
        allowed_user_ids = parse_user_ids(allowed_ids_raw)
        owner_ids_raw = os.getenv("TELEGRAM_OWNER_IDS", "").strip()
        owner_user_ids = parse_user_ids(owner_ids_raw) or (set(allowed_user_ids) if allowed_user_ids else None)
        access_db_raw = os.getenv("TELEGRAM_ACCESS_DB", "").strip()
        memory_db_raw = os.getenv("TELEGRAM_MEMORY_DB", "").strip()
        memory_depth_raw = os.getenv("TELEGRAM_MEMORY_DEPTH", "10").strip()
        materials_db_raw = os.getenv("TELEGRAM_MATERIALS_DB", "").strip()
        materials_files_raw = os.getenv("TELEGRAM_MATERIALS_DIR", "").strip()
        materials_depth_raw = os.getenv("TELEGRAM_MATERIALS_DEPTH", "5").strip()
        return cls(
            token=token,
            mode=os.getenv("AI_ENGINEERING_BOT_MODE", "mock-llm"),
            allowed_user_ids=allowed_user_ids,
            owner_user_ids=owner_user_ids,
            access_db_path=Path(access_db_raw) if access_db_raw else None,
            memory_db_path=Path(memory_db_raw) if memory_db_raw else None,
            memory_depth=int(memory_depth_raw),
            materials_db_path=Path(materials_db_raw) if materials_db_raw else None,
            materials_files_dir=Path(materials_files_raw) if materials_files_raw else None,
            materials_depth=int(materials_depth_raw),
        )


@dataclass(frozen=True)
class BotReply:
    text: str
    reply_markup: dict[str, object] | None = None


@dataclass
class BotSession:
    mode: str = "idle"
    selected_agent_id: str | None = None
    meeting_agent_ids: set[str] = field(default_factory=set)


class TelegramAPI:
    def __init__(self, token: str) -> None:
        self.base_url = f"https://api.telegram.org/bot{token}"

    def call(self, method: str, payload: dict[str, object] | None = None) -> dict[str, object]:
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}/{method}",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=60) as response:
            return json.loads(response.read().decode("utf-8"))

    def get_updates(self, offset: int | None) -> list[dict[str, object]]:
        query = {"timeout": 30}
        if offset is not None:
            query["offset"] = offset
        url = f"{self.base_url}/getUpdates?{parse.urlencode(query)}"
        with request.urlopen(url, timeout=35) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data.get("result", [])

    def get_me(self) -> dict[str, object]:
        data = self.call("getMe")
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected Telegram getMe response: {data}")
        return result

    def get_file(self, file_id: str) -> dict[str, object]:
        data = self.call("getFile", {"file_id": file_id})
        result = data.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"Unexpected Telegram getFile response: {data}")
        return result

    def download_file(self, file_path: str, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        url = f"{self.base_url.replace('/bot', '/file/bot')}/{file_path}"
        with request.urlopen(url, timeout=60) as response:
            destination.write_bytes(response.read())

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, object] | None = None) -> None:
        for chunk in split_telegram_message(text):
            payload: dict[str, object] = {"chat_id": chat_id, "text": chunk}
            if reply_markup and chunk == text:
                payload["reply_markup"] = reply_markup
            self.call("sendMessage", payload)

    def edit_message_text(
        self,
        chat_id: int,
        message_id: int,
        text: str,
        reply_markup: dict[str, object] | None = None,
    ) -> None:
        payload: dict[str, object] = {"chat_id": chat_id, "message_id": message_id, "text": text}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        self.call("editMessageText", payload)

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_query_id})


def parse_user_ids(raw: str) -> set[int] | None:
    if not raw:
        return None
    return {int(item.strip()) for item in raw.split(",") if item.strip()}


def split_telegram_message(text: str, limit: int = 3800) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = ""
    for line in text.splitlines(keepends=True):
        while len(line) > limit:
            if current:
                chunks.append(current)
                current = ""
            chunks.append(line[:limit])
            line = line[limit:]
        if len(current) + len(line) > limit:
            if current:
                chunks.append(current)
            current = ""
        current += line
    if current:
        chunks.append(current)
    return chunks


def build_llm_client(mode: str) -> LLMClient:
    if mode == "mock-llm":
        return MockLLMClient(response_prefix="Telegram mock analysis")
    if mode == "llm":
        return OpenAICompatibleLLMClient.from_env()
    if mode == "deepseek":
        return DeepSeekLLMClient.from_env()
    raise ValueError(f"Unsupported Telegram bot mode: {mode}")


def normalize_agent_id(agent_id: str) -> str:
    normalized = agent_id.strip().lower()
    return AGENT_ALIASES.get(normalized, normalized)


def find_agent(agents: list[AgentProfile], agent_id: str) -> AgentProfile | None:
    normalized = normalize_agent_id(agent_id)
    for agent in agents:
        if agent.id.lower() == normalized:
            return agent
    return None


def get_agent_card(agent: AgentProfile) -> AgentCard:
    return AGENT_CARDS.get(
        agent.id,
        AgentCard(
            id=agent.id,
            label=agent.name,
            role=agent.name,
            description=agent.focus,
            scope=agent.focus,
            out_of_scope_redirect="если вопрос вне роли, скажи об этом и предложи профильного специалиста",
        ),
    )


def llm_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError) and exc.code == 429:
        return (
            "LLM-провайдер вернул 429 Too Many Requests.\n\n"
            "Сейчас недоступна квота, биллинг или rate limit. Сам бот работает; "
            "можно временно перейти в mock-режим или попробовать короткий запрос к одному специалисту позже."
        )
    if isinstance(exc, HTTPError):
        return f"HTTP-ошибка LLM-провайдера {exc.code}: {exc.reason}"
    if isinstance(exc, URLError):
        return f"Сетевая ошибка LLM-провайдера: {exc.reason}"
    return f"Ошибка LLM-провайдера: {exc}"


def complete_safely(llm_client: LLMClient, messages: list[dict[str, str]]) -> str:
    try:
        return llm_client.complete(messages)
    except Exception as exc:
        return llm_error_message(exc)


def render_memory_context(events: list[MemoryEvent]) -> str:
    if not events:
        return "Истории диалога с этим специалистом пока нет."
    lines = ["Последние сообщения диалога с этим специалистом:"]
    for event in events:
        speaker = "Пользователь" if event.role == "user" else "Специалист"
        lines.append(f"{speaker}: {event.content}")
    return "\n".join(lines)


def render_materials_context(materials: list[ProjectMaterial]) -> str:
    if not materials:
        return "Материалы проекта пока не загружены."
    lines = ["Последние материалы проекта пользователя:"]
    for material in materials:
        content = material.content[:3000]
        lines.append(f"\nМатериал #{material.id}: {material.title} ({material.source_type})\n{content}")
    return "\n".join(lines)


def ask_agent(
    agent: AgentProfile,
    question: str,
    llm_client: LLMClient,
    prompts_path: Path | None,
    *,
    memory_events: list[MemoryEvent] | None = None,
    materials: list[ProjectMaterial] | None = None,
) -> str:
    role_prompt = load_agent_prompt(agent.id, prompts_path)
    card = get_agent_card(agent)
    system_prompt = (
        "Ты AI-сотрудник робототехнической компании. Отвечай на русском языке как ведущий специалист. "
        "Пиши структурно и прикладно. Отделяй факты, предположения, риски, открытые вопросы, рекомендации "
        "и решения, которые требуют подтверждения человеком. "
        "Не утверждай safety-critical и production решения самостоятельно.\n\n"
        f"Граница твоей роли: {card.scope}.\n"
        f"Фильтр выхода за роль: {card.out_of_scope_redirect}. "
        "Если вопрос выходит за рамки твоей роли, не отвечай как эксперт соседнего направления. "
        "Коротко обозначь границу компетенции, дай только смежные замечания в рамках своей роли и предложи, какого специалиста подключить."
    )
    if role_prompt:
        system_prompt = f"{system_prompt}\n\nРолевые инструкции:\n{role_prompt}"
    return complete_safely(
        llm_client,
        [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": (
                    f"Специалист: {card.label}\n"
                    f"Роль: {card.role}\n"
                    f"Фокус: {agent.focus}\n"
                    f"Вопрос: {question}\n\n"
                    f"Контекст памяти:\n{render_memory_context(memory_events or [])}\n\n"
                    f"Материалы проекта:\n{render_materials_context(materials or [])}"
                ),
            },
        ],
    )


def run_meeting(agents: list[AgentProfile], topic: str, llm_client: LLMClient, prompts_path: Path | None) -> str:
    sections = [f"# Инженерное совещание\n\nТема: {topic}\n"]
    for agent in agents:
        card = get_agent_card(agent)
        response = ask_agent(agent, f"Дай свою позицию для инженерного совещания по теме: {topic}", llm_client, prompts_path)
        sections.append(f"## {card.label}\n\n{response}\n")
    summary_prompt = (
        "Суммируй это инженерное совещание для CTO на русском языке. Включи консенсус, разногласия, риски, "
        "открытые вопросы и следующие действия. Не заявляй финальное утверждение.\n\n"
        + "\n\n".join(sections)
    )
    summary = complete_safely(
        llm_client,
        [
            {"role": "system", "content": "Ты CTO Control Tower робототехнической инженерной организации. Отвечай на русском языке."},
            {"role": "user", "content": summary_prompt},
        ],
    )
    sections.append(f"## Итог для CTO\n\n{summary}")
    return "\n".join(sections)


def render_start() -> str:
    return (
        "AI Team of Engineers\n\n"
        "Выбери специалиста и пиши ему обычным текстом. "
        "Или собери совещание из нескольких AI-сотрудников.\n\n"
        "Команды спрятаны в /help."
    )


def render_agents(agents: list[AgentProfile]) -> str:
    lines = ["Специалисты:"]
    for agent in agents:
        card = get_agent_card(agent)
        lines.append(f"\n{card.label}\nРоль: {card.role}\n{card.description}")
    return "\n".join(lines)


def render_agent_profile(agent: AgentProfile) -> str:
    card = get_agent_card(agent)
    return f"{card.label}\n\nРоль: {card.role}\n\n{card.description}\n\nНажми \"Начать чат\", чтобы общаться с этим специалистом."


def main_menu_keyboard() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [{"text": "Специалисты", "callback_data": "menu:agents"}],
            [{"text": "Собрать совещание", "callback_data": "meeting:start"}],
            [
                {"text": "Статус", "callback_data": "menu:status"},
                {"text": "Справка", "callback_data": "menu:help"},
            ],
        ]
    }


def agents_keyboard(agents: list[AgentProfile]) -> dict[str, object]:
    rows = []
    for agent in agents:
        card = get_agent_card(agent)
        rows.append([{"text": card.label, "callback_data": f"agent:{agent.id}"}])
    rows.append([{"text": "Назад", "callback_data": "menu:start"}])
    return {"inline_keyboard": rows}


def agent_profile_keyboard(agent: AgentProfile) -> dict[str, object]:
    return {
        "inline_keyboard": [
            [{"text": "Начать чат", "callback_data": f"chat:{agent.id}"}],
            [{"text": "Назад к специалистам", "callback_data": "menu:agents"}],
        ]
    }


def after_answer_keyboard(agent_id: str | None = None) -> dict[str, object]:
    rows = []
    if agent_id:
        rows.append([{"text": "Продолжить с этим специалистом", "callback_data": f"post:chat:{agent_id}"}])
    rows.append(
        [
            {"text": "Другой специалист", "callback_data": "post:menu:agents"},
            {"text": "Совещание", "callback_data": "post:meeting:start"},
        ]
    )
    rows.append([{"text": "Главное меню", "callback_data": "post:menu:start"}])
    return {"inline_keyboard": rows}


def meeting_keyboard(agents: list[AgentProfile], selected_ids: set[str]) -> dict[str, object]:
    rows = []
    for agent in agents:
        card = get_agent_card(agent)
        marker = "[x]" if agent.id in selected_ids else "[ ]"
        rows.append([{"text": f"{marker} {card.label}", "callback_data": f"meeting:toggle:{agent.id}"}])
    rows.append([{"text": "Дальше: написать тему", "callback_data": "meeting:run"}])
    rows.append(
        [
            {"text": "Выбрать всех", "callback_data": "meeting:all"},
            {"text": "Очистить", "callback_data": "meeting:clear"},
        ]
    )
    rows.append([{"text": "Назад", "callback_data": "menu:start"}])
    return {"inline_keyboard": rows}


def render_meeting_selection(agents: list[AgentProfile], selected_ids: set[str]) -> str:
    if selected_ids:
        selected_labels = [get_agent_card(agent).label for agent in agents if agent.id in selected_ids]
        selected_text = ", ".join(selected_labels)
    else:
        selected_text = "пока никто не выбран"
    return f"Совещание\n\nВыбери участников кнопками.\n\nСейчас выбрано: {selected_text}"


def render_status(
    mode: str,
    agents: list[AgentProfile],
    allowed_user_ids: set[int] | None,
    access_store: AccessStore | None = None,
) -> str:
    if access_store:
        access = "база пользователей"
    else:
        access = "whitelist" if allowed_user_ids else "открытый"
    return "\n".join(
        [
            "Статус бота:",
            f"- режим: {mode}",
            f"- специалистов загружено: {len(agents)}",
            f"- доступ: {access}",
            "- интерфейс: Telegram long polling",
        ]
    )


def render_memory_status(memory: ConversationMemory | None, user_id: int | None) -> str:
    if memory is None:
        return "Память диалогов не включена. Укажи TELEGRAM_MEMORY_DB."
    total = memory.count_events()
    user_total = memory.count_events(user_id) if user_id is not None else 0
    return "\n".join(
        [
            "Память диалогов:",
            f"- всего сообщений в памяти: {total}",
            f"- твоих сообщений/ответов: {user_total}",
            "- память хранится отдельно по каждому специалисту",
        ]
    )


def render_materials_status(materials: ProjectMaterials | None, user_id: int | None) -> str:
    if materials is None:
        return "Материалы проекта не включены. Укажи TELEGRAM_MATERIALS_DB и TELEGRAM_MATERIALS_DIR."
    user_total = materials.count_materials(user_id) if user_id is not None else 0
    recent = materials.get_recent_materials(user_id, 10) if user_id is not None else []
    lines = [
        "Материалы проекта:",
        f"- твоих материалов: {user_total}",
        "- поддерживаются: .docx, .pptx, .txt, .md, .csv, .tsv и ссылки http/https",
    ]
    if recent:
        lines.append("\nПоследние материалы:")
        for material in recent:
            lines.append(f"- #{material.id}: {material.title} ({material.source_type})")
    return "\n".join(lines)


def render_users(access_store: AccessStore | None) -> str:
    if access_store is None:
        return "База доступа не включена. Используется TELEGRAM_ALLOWED_USER_IDS."
    users = access_store.list_users()
    if not users:
        return "В базе доступа пока нет пользователей."
    lines = ["Пользователи:"]
    for user in users:
        status = "active" if user.is_active else "disabled"
        lines.append(f"- {user.telegram_id}: {user.role}, {status}")
    return "\n".join(lines)


def require_admin(access_store: AccessStore | None, user_id: int | None) -> str | None:
    if access_store is None:
        return "Команда доступна только при включенной базе доступа TELEGRAM_ACCESS_DB."
    if user_id is None or not access_store.is_admin(user_id):
        return "Недостаточно прав. Нужна роль owner или admin."
    return None


def as_reply(text: str, reply_markup: dict[str, object] | None = None) -> BotReply:
    return BotReply(text=text, reply_markup=reply_markup)


def safe_filename(name: str) -> str:
    cleaned = "".join(char if char.isalnum() or char in "._-" else "_" for char in name)
    return cleaned[:120] or "material"


def store_telegram_document(
    api: TelegramAPI,
    document: dict[str, object],
    user_id: int,
    materials: ProjectMaterials | None,
) -> BotReply:
    if materials is None:
        return as_reply("Материалы проекта не включены. Укажи TELEGRAM_MATERIALS_DB и TELEGRAM_MATERIALS_DIR.")
    file_id = document.get("file_id")
    file_name = document.get("file_name") or "material"
    if not isinstance(file_id, str) or not isinstance(file_name, str):
        return as_reply("Не удалось прочитать данные файла из Telegram.")
    try:
        telegram_file = api.get_file(file_id)
        telegram_path = telegram_file.get("file_path")
        if not isinstance(telegram_path, str):
            return as_reply("Telegram не вернул путь для скачивания файла.")
        destination = materials.files_dir / str(user_id) / f"{int(time.time())}_{safe_filename(file_name)}"
        api.download_file(telegram_path, destination)
        content = extract_file_text(destination, file_name)
        material_id = materials.add_material(
            user_id,
            "file",
            file_name,
            content,
            file_path=destination,
        )
    except Exception as exc:
        return as_reply(f"Не удалось добавить файл в материалы проекта: {exc}", main_menu_keyboard())
    return as_reply(
        "\n".join(
            [
                "Файл добавлен в материалы проекта.",
                f"#{material_id}: {file_name}",
                "",
                "Теперь выбери специалиста и задай вопрос по этому файлу.",
            ]
        ),
        main_menu_keyboard(),
    )


def handle_callback(
    callback_data: str,
    agents: list[AgentProfile],
    *,
    mode: str,
    user_id: int | None,
    allowed_user_ids: set[int] | None,
    access_store: AccessStore | None = None,
    session: BotSession | None = None,
) -> BotReply:
    session = session or BotSession()
    if callback_data.startswith("post:"):
        callback_data = callback_data[len("post:") :]
    if callback_data == "menu:start":
        session.mode = "idle"
        session.selected_agent_id = None
        return as_reply(render_start(), main_menu_keyboard())
    if callback_data == "menu:help":
        return as_reply(HELP_TEXT, main_menu_keyboard())
    if callback_data == "menu:agents":
        session.mode = "idle"
        return as_reply(render_agents(agents), agents_keyboard(agents))
    if callback_data == "menu:status":
        return as_reply(render_status(mode, agents, allowed_user_ids, access_store), main_menu_keyboard())
    if callback_data.startswith("agent:"):
        agent_id = callback_data[len("agent:") :]
        agent = find_agent(agents, agent_id)
        if not agent:
            return as_reply(f"Неизвестный специалист: {agent_id}", agents_keyboard(agents))
        return as_reply(render_agent_profile(agent), agent_profile_keyboard(agent))
    if callback_data.startswith("chat:"):
        agent_id = callback_data[len("chat:") :]
        agent = find_agent(agents, agent_id)
        if not agent:
            return as_reply(f"Неизвестный специалист: {agent_id}", agents_keyboard(agents))
        session.mode = "agent"
        session.selected_agent_id = agent.id
        card = get_agent_card(agent)
        return as_reply(
            f"Чат со специалистом: {card.label}\n\nТеперь просто напиши вопрос обычным сообщением.",
            after_answer_keyboard(agent.id),
        )
    if callback_data == "meeting:start":
        session.mode = "meeting_select"
        if not session.meeting_agent_ids:
            session.meeting_agent_ids = {agent.id for agent in agents}
        return as_reply(render_meeting_selection(agents, session.meeting_agent_ids), meeting_keyboard(agents, session.meeting_agent_ids))
    if callback_data.startswith("meeting:toggle:"):
        session.mode = "meeting_select"
        agent_id = callback_data[len("meeting:toggle:") :]
        if agent_id in session.meeting_agent_ids:
            session.meeting_agent_ids.remove(agent_id)
        else:
            session.meeting_agent_ids.add(agent_id)
        return as_reply(render_meeting_selection(agents, session.meeting_agent_ids), meeting_keyboard(agents, session.meeting_agent_ids))
    if callback_data == "meeting:all":
        session.mode = "meeting_select"
        session.meeting_agent_ids = {agent.id for agent in agents}
        return as_reply(render_meeting_selection(agents, session.meeting_agent_ids), meeting_keyboard(agents, session.meeting_agent_ids))
    if callback_data == "meeting:clear":
        session.mode = "meeting_select"
        session.meeting_agent_ids.clear()
        return as_reply(render_meeting_selection(agents, session.meeting_agent_ids), meeting_keyboard(agents, session.meeting_agent_ids))
    if callback_data == "meeting:run":
        if not session.meeting_agent_ids:
            return as_reply("Выбери хотя бы одного участника совещания.", meeting_keyboard(agents, session.meeting_agent_ids))
        session.mode = "meeting_topic"
        return as_reply("Напиши тему совещания обычным сообщением.", meeting_keyboard(agents, session.meeting_agent_ids))
    return as_reply("Неизвестное действие кнопки.", main_menu_keyboard())


def parse_meeting_request(rest: str, agents: list[AgentProfile]) -> tuple[list[AgentProfile], str, str | None]:
    first, separator, possible_topic = rest.partition(" ")
    if separator and "," in first:
        selected_agents: list[AgentProfile] = []
        unknown: list[str] = []
        for raw_agent_id in first.split(","):
            agent = find_agent(agents, raw_agent_id)
            if agent:
                selected_agents.append(agent)
            else:
                unknown.append(raw_agent_id.strip())
        if unknown:
            return [], possible_topic, f"Неизвестные участники совещания: {', '.join(unknown)}"
        if not selected_agents:
            return [], possible_topic, "Не выбрано ни одного корректного специалиста для совещания."
        return selected_agents, possible_topic.strip(), None
    return agents, rest.strip(), None


def handle_admin_command(
    stripped: str,
    user_id: int | None,
    access_store: AccessStore | None,
) -> BotReply | None:
    if stripped == "/users":
        denied = require_admin(access_store, user_id)
        if denied:
            return as_reply(denied, main_menu_keyboard())
        return as_reply(render_users(access_store), main_menu_keyboard())
    if stripped.startswith("/allow "):
        denied = require_admin(access_store, user_id)
        if denied:
            return as_reply(denied, main_menu_keyboard())
        parts = stripped.split()
        if len(parts) not in {2, 3}:
            return as_reply("Используй: /allow <telegram_id> [owner|admin|member|viewer]", main_menu_keyboard())
        role = parts[2] if len(parts) == 3 else "member"
        if role not in ROLES:
            return as_reply(f"Неизвестная роль: {role}. Доступные роли: {', '.join(ROLES)}", main_menu_keyboard())
        assert access_store is not None
        access_store.ensure_user(int(parts[1]), role=role, is_active=True)
        return as_reply(f"Пользователь {parts[1]} добавлен с ролью {role}.", main_menu_keyboard())
    if stripped.startswith("/deny "):
        denied = require_admin(access_store, user_id)
        if denied:
            return as_reply(denied, main_menu_keyboard())
        parts = stripped.split()
        if len(parts) != 2:
            return as_reply("Используй: /deny <telegram_id>", main_menu_keyboard())
        assert access_store is not None
        access_store.set_active(int(parts[1]), False)
        return as_reply(f"Пользователь {parts[1]} отключен.", main_menu_keyboard())
    if stripped.startswith("/role "):
        denied = require_admin(access_store, user_id)
        if denied:
            return as_reply(denied, main_menu_keyboard())
        parts = stripped.split()
        if len(parts) != 3:
            return as_reply("Используй: /role <telegram_id> <owner|admin|member|viewer>", main_menu_keyboard())
        role = parts[2]
        if role not in ROLES:
            return as_reply(f"Неизвестная роль: {role}. Доступные роли: {', '.join(ROLES)}", main_menu_keyboard())
        assert access_store is not None
        access_store.set_role(int(parts[1]), role)
        return as_reply(f"Пользователю {parts[1]} назначена роль {role}.", main_menu_keyboard())
    return None


def handle_text(
    text: str,
    agents: list[AgentProfile],
    llm_client: LLMClient,
    prompts_path: Path | None,
    *,
    mode: str = "mock-llm",
    user_id: int | None = None,
    allowed_user_ids: set[int] | None = None,
    access_store: AccessStore | None = None,
    session: BotSession | None = None,
    memory: ConversationMemory | None = None,
    memory_depth: int = 10,
    materials: ProjectMaterials | None = None,
    materials_depth: int = 5,
) -> BotReply:
    session = session or BotSession()
    stripped = text.strip()
    if stripped == "/start":
        session.mode = "idle"
        session.selected_agent_id = None
        return as_reply(render_start(), main_menu_keyboard())
    if stripped == "/help":
        return as_reply(HELP_TEXT, main_menu_keyboard())
    if stripped == "/whoami":
        if user_id is None:
            return as_reply("Telegram user id недоступен в этом контексте.", main_menu_keyboard())
        return as_reply(f"Твой Telegram user id: {user_id}", main_menu_keyboard())
    if stripped == "/status":
        return as_reply(render_status(mode, agents, allowed_user_ids, access_store), main_menu_keyboard())
    if stripped == "/memory":
        return as_reply(render_memory_status(memory, user_id), main_menu_keyboard())
    if stripped == "/materials":
        return as_reply(render_materials_status(materials, user_id), main_menu_keyboard())
    if stripped == "/clear_materials":
        if materials is None:
            return as_reply("Материалы проекта не включены.", main_menu_keyboard())
        if user_id is None:
            return as_reply("Telegram user id недоступен.", main_menu_keyboard())
        materials.clear_user_materials(user_id)
        return as_reply("Твои материалы проекта очищены.", main_menu_keyboard())
    if stripped == "/forget":
        if memory is None:
            return as_reply("Память диалогов не включена.", main_menu_keyboard())
        if user_id is None:
            return as_reply("Telegram user id недоступен.", main_menu_keyboard())
        if not session.selected_agent_id:
            return as_reply("Сначала выбери специалиста, память которого нужно очистить.", agents_keyboard(agents))
        memory.clear_user_agent(user_id, session.selected_agent_id)
        return as_reply("Память выбранного специалиста очищена.", after_answer_keyboard(session.selected_agent_id))

    admin_reply = handle_admin_command(stripped, user_id, access_store)
    if admin_reply:
        return admin_reply

    if stripped == "/agents":
        return as_reply(render_agents(agents), agents_keyboard(agents))

    urls = extract_urls(stripped)
    if urls and materials is not None and user_id is not None:
        stored: list[str] = []
        failed: list[str] = []
        for url in urls[:3]:
            try:
                content = fetch_url_text(url)
                material_id = materials.add_material(user_id, "link", url, content, source_url=url)
                stored.append(f"#{material_id}: {url}")
            except Exception as exc:
                failed.append(f"{url}: {exc}")
        lines = ["Ссылки добавлены в материалы проекта."] if stored else ["Не удалось добавить ссылки."]
        if stored:
            lines.extend(stored)
        if failed:
            lines.append("\nОшибки:")
            lines.extend(failed)
        lines.append("\nТеперь выбери специалиста и задай вопрос по материалам.")
        return as_reply("\n".join(lines), main_menu_keyboard())

    if stripped.startswith("/ask "):
        rest = stripped[len("/ask ") :].strip()
        if " " not in rest:
            return as_reply("Используй: /ask <agent_id> <вопрос>", agents_keyboard(agents))
        agent_id, question = rest.split(" ", 1)
        agent = find_agent(agents, agent_id)
        if not agent:
            return as_reply(f"Неизвестный специалист: {agent_id}\n\n{render_agents(agents)}", agents_keyboard(agents))
        session.mode = "agent"
        session.selected_agent_id = agent.id
        memory_events = memory.get_recent_events(user_id, agent.id, memory_depth) if memory and user_id is not None else []
        recent_materials = materials.get_recent_materials(user_id, materials_depth) if materials and user_id is not None else []
        response = ask_agent(
            agent,
            question,
            llm_client,
            prompts_path,
            memory_events=memory_events,
            materials=recent_materials,
        )
        if memory and user_id is not None:
            memory.add_event(user_id, agent.id, "user", question)
            memory.add_event(user_id, agent.id, "assistant", response)
        return as_reply(response, after_answer_keyboard(agent.id))
    if stripped.startswith("/meeting "):
        rest = stripped[len("/meeting ") :].strip()
        meeting_agents, topic, error = parse_meeting_request(rest, agents)
        if error:
            return as_reply(f"{error}\n\n{render_agents(agents)}", agents_keyboard(agents))
        if not topic:
            return as_reply("Используй: /meeting <тема> или /meeting <agent_id,agent_id> <тема>", main_menu_keyboard())
        return as_reply(run_meeting(meeting_agents, topic, llm_client, prompts_path), after_answer_keyboard())

    if session.mode == "agent" and session.selected_agent_id:
        agent = find_agent(agents, session.selected_agent_id)
        if not agent:
            session.mode = "idle"
            session.selected_agent_id = None
            return as_reply("Выбранный специалист больше недоступен. Выбери специалиста заново.", agents_keyboard(agents))
        memory_events = memory.get_recent_events(user_id, agent.id, memory_depth) if memory and user_id is not None else []
        recent_materials = materials.get_recent_materials(user_id, materials_depth) if materials and user_id is not None else []
        response = ask_agent(
            agent,
            stripped,
            llm_client,
            prompts_path,
            memory_events=memory_events,
            materials=recent_materials,
        )
        if memory and user_id is not None:
            memory.add_event(user_id, agent.id, "user", stripped)
            memory.add_event(user_id, agent.id, "assistant", response)
        return as_reply(response, after_answer_keyboard(agent.id))

    if session.mode == "meeting_topic":
        meeting_agents = [agent for agent in agents if agent.id in session.meeting_agent_ids]
        if not meeting_agents:
            session.mode = "meeting_select"
            return as_reply("Участники совещания не выбраны.", meeting_keyboard(agents, session.meeting_agent_ids))
        session.mode = "idle"
        return as_reply(run_meeting(meeting_agents, stripped, llm_client, prompts_path), after_answer_keyboard())

    return as_reply(
        "Выбери специалиста кнопкой, а потом пиши ему обычным текстом.",
        main_menu_keyboard(),
    )


def is_user_allowed(access_store: AccessStore | None, allowed_user_ids: set[int] | None, user_id: int) -> bool:
    if access_store is not None:
        return access_store.is_allowed(user_id)
    if allowed_user_ids is not None:
        return user_id in allowed_user_ids
    return True


def run_bot(config: TelegramConfig) -> None:
    api = TelegramAPI(config.token)
    agents = load_agents(config.agents_path)
    llm_client = build_llm_client(config.mode)
    access_store = AccessStore(config.access_db_path) if config.access_db_path else None
    if access_store and config.owner_user_ids:
        seed_owner_users(access_store, config.owner_user_ids)
    memory = ConversationMemory(config.memory_db_path) if config.memory_db_path else None
    materials = (
        ProjectMaterials(config.materials_db_path, config.materials_files_dir)
        if config.materials_db_path and config.materials_files_dir
        else None
    )
    sessions: dict[int, BotSession] = {}
    offset: int | None = None
    print("Telegram bot is running. Press Ctrl+C to stop.")
    while True:
        try:
            updates = api.get_updates(offset)
        except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
            print(f"Telegram polling error: {exc}. Retrying in 10 seconds...")
            time.sleep(10)
            continue
        for update in updates:
            offset = int(update["update_id"]) + 1
            callback_query = update.get("callback_query")
            if isinstance(callback_query, dict):
                callback_id = callback_query.get("id")
                callback_data = callback_query.get("data")
                message = callback_query.get("message")
                from_user = callback_query.get("from")
                if (
                    isinstance(callback_id, str)
                    and isinstance(callback_data, str)
                    and isinstance(message, dict)
                    and isinstance(from_user, dict)
                    and isinstance(message.get("chat"), dict)
                    and isinstance(message.get("message_id"), int)
                ):
                    user_id = int(from_user["id"])
                    chat_id = int(message["chat"]["id"])
                    message_id = int(message["message_id"])
                    if not is_user_allowed(access_store, config.allowed_user_ids, user_id):
                        api.answer_callback_query(callback_id)
                        api.send_message(chat_id, f"Доступ запрещен. Твой Telegram user id: {user_id}")
                        continue
                    session = sessions.setdefault(user_id, BotSession())
                    try:
                        reply = handle_callback(
                            callback_data,
                            agents,
                            mode=config.mode,
                            user_id=user_id,
                            allowed_user_ids=config.allowed_user_ids,
                            access_store=access_store,
                            session=session,
                        )
                    except Exception as exc:
                        reply = as_reply(f"Ошибка: {exc}")
                    try:
                        api.answer_callback_query(callback_id)
                        if callback_data.startswith("post:"):
                            api.send_message(chat_id, reply.text, reply.reply_markup)
                        else:
                            api.edit_message_text(chat_id, message_id, reply.text, reply.reply_markup)
                    except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
                        print(f"Telegram callback handling error: {exc}.")
                continue

            message = update.get("message")
            if not isinstance(message, dict):
                continue
            chat = message.get("chat")
            from_user = message.get("from")
            text = message.get("text")
            document = message.get("document")
            if not isinstance(chat, dict) or not isinstance(from_user, dict):
                continue
            user_id = int(from_user["id"])
            chat_id = int(chat["id"])
            if not is_user_allowed(access_store, config.allowed_user_ids, user_id):
                api.send_message(chat_id, f"Доступ запрещен. Твой Telegram user id: {user_id}")
                continue
            if isinstance(document, dict):
                try:
                    reply = store_telegram_document(api, document, user_id, materials)
                except Exception as exc:
                    reply = as_reply(f"Ошибка: {exc}")
                try:
                    api.send_message(chat_id, reply.text, reply.reply_markup)
                except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
                    print(f"Telegram sendMessage error: {exc}.")
                continue
            if not isinstance(text, str):
                continue
            session = sessions.setdefault(user_id, BotSession())
            try:
                reply = handle_text(
                    text,
                    agents,
                    llm_client,
                    config.prompts_path,
                    mode=config.mode,
                    user_id=user_id,
                    allowed_user_ids=config.allowed_user_ids,
                    access_store=access_store,
                    session=session,
                    memory=memory,
                    memory_depth=config.memory_depth,
                    materials=materials,
                    materials_depth=config.materials_depth,
                )
            except Exception as exc:
                reply = as_reply(f"Ошибка: {exc}")
            try:
                api.send_message(chat_id, reply.text, reply.reply_markup)
            except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
                print(f"Telegram sendMessage error: {exc}.")
        time.sleep(config.poll_interval_seconds)


def check_bot(config: TelegramConfig) -> str:
    api = TelegramAPI(config.token)
    bot_info = api.get_me()
    username = bot_info.get("username", "<unknown>")
    bot_id = bot_info.get("id", "<unknown>")
    return f"Telegram bot connection OK: @{username} (id: {bot_id})"
