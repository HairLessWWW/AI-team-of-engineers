from __future__ import annotations

from dataclasses import dataclass
import json
import os
import time
from pathlib import Path
from socket import timeout as SocketTimeout
from urllib import parse, request
from urllib.error import HTTPError, URLError

from .agents import AgentProfile, load_agents
from .llm import LLMClient, MockLLMClient, OpenAICompatibleLLMClient
from .prompts import load_agent_prompt


HELP_TEXT = """AI Team of Engineers

Команды:
/start - показать меню
/whoami - показать твой Telegram user id
/status - статус бота
/agents - список AI-сотрудников
/ask <agent_id> <вопрос> - задать вопрос одному AI-сотруднику
/meeting <тема> - собрать совещание всех MVP-агентов
/meeting <agent_id,agent_id> <тема> - собрать выбранных агентов

Примеры:
/ask electrical Что может заблокировать пилотную сборку?
/ask электрик Что блокирует пилотную сборку?
/meeting Готовность руки антропоморфного робота к пилотной партии
/meeting systems,electrical,manufacturing Готовность руки к пилотной сборке
"""


AGENT_ALIASES = {
    "system": "systems",
    "systems": "systems",
    "architect": "systems",
    "архитектор": "systems",
    "системщик": "systems",
    "системный": "systems",
    "electrical": "electrical",
    "electric": "electrical",
    "электрик": "electrical",
    "электрика": "electrical",
    "manufacturing": "manufacturing",
    "production": "manufacturing",
    "производство": "manufacturing",
    "технолог": "manufacturing",
    "certification": "certification_docs",
    "docs": "certification_docs",
    "documentation": "certification_docs",
    "сертификация": "certification_docs",
    "документация": "certification_docs",
}


@dataclass(frozen=True)
class TelegramConfig:
    token: str
    agents_path: Path = Path("configs/agents.json")
    prompts_path: Path = Path("prompts")
    mode: str = "mock-llm"
    allowed_user_ids: set[int] | None = None
    poll_interval_seconds: float = 1.0

    @classmethod
    def from_env(cls) -> "TelegramConfig":
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN is required to run the Telegram bot.")
        allowed_ids_raw = os.getenv("TELEGRAM_ALLOWED_USER_IDS", "").strip()
        allowed_user_ids = None
        if allowed_ids_raw:
            allowed_user_ids = {int(item.strip()) for item in allowed_ids_raw.split(",") if item.strip()}
        return cls(
            token=token,
            mode=os.getenv("AI_ENGINEERING_BOT_MODE", "mock-llm"),
            allowed_user_ids=allowed_user_ids,
        )


@dataclass(frozen=True)
class BotReply:
    text: str
    reply_markup: dict[str, object] | None = None


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

    def send_message(self, chat_id: int, text: str, reply_markup: dict[str, object] | None = None) -> None:
        for chunk in split_telegram_message(text):
            payload: dict[str, object] = {"chat_id": chat_id, "text": chunk}
            if reply_markup and chunk == text:
                payload["reply_markup"] = reply_markup
            self.call("sendMessage", payload)

    def answer_callback_query(self, callback_query_id: str) -> None:
        self.call("answerCallbackQuery", {"callback_query_id": callback_query_id})


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


def llm_error_message(exc: Exception) -> str:
    if isinstance(exc, HTTPError) and exc.code == 429:
        return (
            "LLM-провайдер вернул 429 Too Many Requests. "
            "Сейчас недоступна квота, биллинг или rate limit. "
            "Сам бот работает; можно временно перейти в mock-режим или попробовать короткий запрос к одному агенту позже."
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


def ask_agent(agent: AgentProfile, question: str, llm_client: LLMClient, prompts_path: Path | None) -> str:
    role_prompt = load_agent_prompt(agent.id, prompts_path)
    system_prompt = (
        "You are an AI engineering employee in a robotics company. "
        "Answer as a lead specialist. Separate facts, assumptions, risks, questions, and recommendations. "
        "Do not approve safety-critical or production decisions."
    )
    if role_prompt:
        system_prompt = f"{system_prompt}\n\nRole-specific instructions:\n{role_prompt}"
    return complete_safely(
        llm_client,
        [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Agent: {agent.name}\nFocus: {agent.focus}\nQuestion: {question}"},
        ],
    )


def run_meeting(agents: list[AgentProfile], topic: str, llm_client: LLMClient, prompts_path: Path | None) -> str:
    sections = [f"# Engineering Meeting\n\nTopic: {topic}\n"]
    for agent in agents:
        response = ask_agent(agent, f"Give your position for this engineering meeting: {topic}", llm_client, prompts_path)
        sections.append(f"## {agent.name}\n\n{response}\n")
    summary_prompt = (
        "Summarize this engineering meeting for the CTO. Include consensus, disagreements, risks, open questions, "
        "and next actions. Do not claim final approval.\n\n"
        + "\n\n".join(sections)
    )
    summary = complete_safely(
        llm_client,
        [
            {"role": "system", "content": "You are CTO Control Tower for a robotics engineering organization."},
            {"role": "user", "content": summary_prompt},
        ],
    )
    sections.append(f"## CTO Control Tower Summary\n\n{summary}")
    return "\n".join(sections)


def render_agents(agents: list[AgentProfile]) -> str:
    lines = ["Доступные AI-сотрудники:"]
    for agent in agents:
        lines.append(f"- {agent.id}: {agent.name}")
    lines.extend(
        [
            "",
            "Псевдонимы:",
            "- электрик -> electrical",
            "- производство / технолог -> manufacturing",
            "- сертификация / документация -> certification_docs",
            "- архитектор / системщик -> systems",
        ]
    )
    return "\n".join(lines)


def main_menu_keyboard() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "AI-сотрудники", "callback_data": "menu:agents"},
                {"text": "Статус", "callback_data": "menu:status"},
            ],
            [
                {"text": "Задать вопрос", "callback_data": "menu:ask"},
                {"text": "Совещание", "callback_data": "menu:meeting"},
            ],
            [{"text": "Мой Telegram ID", "callback_data": "menu:whoami"}],
        ]
    }


def agents_keyboard(agents: list[AgentProfile]) -> dict[str, object]:
    rows = []
    for agent in agents:
        rows.append([{"text": agent.id, "callback_data": f"agent:{agent.id}"}])
    rows.append([{"text": "Назад в меню", "callback_data": "menu:start"}])
    return {"inline_keyboard": rows}


def after_answer_keyboard() -> dict[str, object]:
    return {
        "inline_keyboard": [
            [
                {"text": "Спросить другого", "callback_data": "menu:ask"},
                {"text": "Начать совещание", "callback_data": "menu:meeting"},
            ],
            [{"text": "Статус", "callback_data": "menu:status"}],
        ]
    }


def render_status(mode: str, agents: list[AgentProfile], allowed_user_ids: set[int] | None) -> str:
    access = "restricted" if allowed_user_ids else "open"
    return "\n".join(
        [
            "Статус бота:",
            f"- режим: {mode}",
            f"- агентов загружено: {len(agents)}",
            f"- доступ: {access}",
            "- интерфейс: Telegram long polling",
        ]
    )


def as_reply(text: str, reply_markup: dict[str, object] | None = None) -> BotReply:
    return BotReply(text=text, reply_markup=reply_markup)


def handle_callback(
    callback_data: str,
    agents: list[AgentProfile],
    *,
    mode: str,
    user_id: int | None,
    allowed_user_ids: set[int] | None,
) -> BotReply:
    if callback_data == "menu:start":
        return as_reply(HELP_TEXT, main_menu_keyboard())
    if callback_data == "menu:agents":
        return as_reply(render_agents(agents), agents_keyboard(agents))
    if callback_data == "menu:status":
        return as_reply(render_status(mode, agents, allowed_user_ids), main_menu_keyboard())
    if callback_data == "menu:whoami":
        if user_id is None:
            return as_reply("Telegram user id недоступен.", main_menu_keyboard())
        return as_reply(f"Твой Telegram user id: {user_id}", main_menu_keyboard())
    if callback_data == "menu:ask":
        return as_reply("Выбери AI-сотрудника, затем отправь: /ask <agent_id> <вопрос>", agents_keyboard(agents))
    if callback_data == "menu:meeting":
        return as_reply(
            "Отправь одну из команд:\n/meeting <тема>\n/meeting systems,electrical,manufacturing <тема>",
            main_menu_keyboard(),
        )
    if callback_data.startswith("agent:"):
        agent_id = callback_data[len("agent:") :]
        agent = find_agent(agents, agent_id)
        if not agent:
            return as_reply(f"Неизвестный агент: {agent_id}", agents_keyboard(agents))
        return as_reply(
            f"{agent.name}\n\nФокус: {agent.focus}\n\nОтправь:\n/ask {agent.id} <твой вопрос>",
            after_answer_keyboard(),
        )
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
            return [], possible_topic, "Не выбрано ни одного корректного агента для совещания."
        return selected_agents, possible_topic.strip(), None
    return agents, rest.strip(), None


def handle_text(
    text: str,
    agents: list[AgentProfile],
    llm_client: LLMClient,
    prompts_path: Path | None,
    *,
    mode: str = "mock-llm",
    user_id: int | None = None,
    allowed_user_ids: set[int] | None = None,
) -> BotReply:
    stripped = text.strip()
    if stripped in {"/start", "/help"}:
        return as_reply(HELP_TEXT, main_menu_keyboard())
    if stripped == "/whoami":
        if user_id is None:
            return as_reply("Telegram user id недоступен в этом контексте.", main_menu_keyboard())
        return as_reply(f"Твой Telegram user id: {user_id}", main_menu_keyboard())
    if stripped == "/status":
        return as_reply(render_status(mode, agents, allowed_user_ids), main_menu_keyboard())
    if stripped == "/agents":
        return as_reply(render_agents(agents), agents_keyboard(agents))
    if stripped.startswith("/ask "):
        rest = stripped[len("/ask ") :].strip()
        if " " not in rest:
            return as_reply("Используй: /ask <agent_id> <вопрос>", agents_keyboard(agents))
        agent_id, question = rest.split(" ", 1)
        agent = find_agent(agents, agent_id)
        if not agent:
            return as_reply(f"Неизвестный агент: {agent_id}\n\n{render_agents(agents)}", agents_keyboard(agents))
        return as_reply(ask_agent(agent, question, llm_client, prompts_path), after_answer_keyboard())
    if stripped.startswith("/meeting "):
        rest = stripped[len("/meeting ") :].strip()
        meeting_agents, topic, error = parse_meeting_request(rest, agents)
        if error:
            return as_reply(f"{error}\n\n{render_agents(agents)}", agents_keyboard(agents))
        if not topic:
            return as_reply("Используй: /meeting <тема> или /meeting <agent_id,agent_id> <тема>", main_menu_keyboard())
        return as_reply(run_meeting(meeting_agents, topic, llm_client, prompts_path), after_answer_keyboard())
    return as_reply("Я не понял команду.\n\n" + HELP_TEXT, main_menu_keyboard())


def run_bot(config: TelegramConfig) -> None:
    api = TelegramAPI(config.token)
    agents = load_agents(config.agents_path)
    llm_client = build_llm_client(config.mode)
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
                ):
                    user_id = int(from_user["id"])
                    chat_id = int(message["chat"]["id"])
                    if config.allowed_user_ids is not None and user_id not in config.allowed_user_ids:
                        api.answer_callback_query(callback_id)
                        api.send_message(chat_id, "Доступ запрещен.")
                        continue
                    try:
                        reply = handle_callback(
                            callback_data,
                            agents,
                            mode=config.mode,
                            user_id=user_id,
                            allowed_user_ids=config.allowed_user_ids,
                        )
                    except Exception as exc:
                        reply = as_reply(f"Ошибка: {exc}")
                    try:
                        api.answer_callback_query(callback_id)
                        api.send_message(chat_id, reply.text, reply.reply_markup)
                    except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
                        print(f"Telegram callback handling error: {exc}.")
                continue
            message = update.get("message")
            if not isinstance(message, dict):
                continue
            chat = message.get("chat")
            from_user = message.get("from")
            text = message.get("text")
            if not isinstance(chat, dict) or not isinstance(from_user, dict) or not isinstance(text, str):
                continue
            user_id = int(from_user["id"])
            chat_id = int(chat["id"])
            if config.allowed_user_ids is not None and user_id not in config.allowed_user_ids:
                api.send_message(chat_id, "Доступ запрещен.")
                continue
            try:
                reply = handle_text(
                    text,
                    agents,
                    llm_client,
                    config.prompts_path,
                    mode=config.mode,
                    user_id=user_id,
                    allowed_user_ids=config.allowed_user_ids,
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
