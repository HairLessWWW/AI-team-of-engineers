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

Commands:
/start - show this help
/whoami - show your Telegram user id
/status - show bot runtime status
/agents - list available AI employees
/ask <agent_id> <question> - ask one AI employee
/meeting <topic> - gather all MVP agents for a short engineering meeting
/meeting <agent_id,agent_id> <topic> - gather selected agents

Examples:
/ask electrical What blocks pilot assembly?
/ask электрик Что блокирует пилотную сборку?
/meeting Readiness of humanoid left arm for pilot production
/meeting systems,electrical,manufacturing Left arm pilot readiness
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

    def send_message(self, chat_id: int, text: str) -> None:
        for chunk in split_telegram_message(text):
            self.call("sendMessage", {"chat_id": chat_id, "text": chunk})


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
            "LLM provider returned 429 Too Many Requests. "
            "API quota, billing, or rate limit is not available right now. "
            "The bot itself is running; switch to mock mode or try a shorter/single-agent request later."
        )
    if isinstance(exc, HTTPError):
        return f"LLM provider HTTP error {exc.code}: {exc.reason}"
    if isinstance(exc, URLError):
        return f"LLM provider network error: {exc.reason}"
    return f"LLM provider error: {exc}"


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
    lines = ["Available AI employees:"]
    for agent in agents:
        lines.append(f"- {agent.id}: {agent.name}")
    lines.extend(["", "Aliases:", "- электрик -> electrical", "- производство / технолог -> manufacturing", "- сертификация / документация -> certification_docs", "- архитектор / системщик -> systems"])
    return "\n".join(lines)


def render_status(mode: str, agents: list[AgentProfile], allowed_user_ids: set[int] | None) -> str:
    access = "restricted" if allowed_user_ids else "open"
    return "\n".join(
        [
            "Bot status:",
            f"- mode: {mode}",
            f"- agents: {len(agents)}",
            f"- access: {access}",
            "- frontend: Telegram long polling",
        ]
    )


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
            return [], possible_topic, f"Unknown meeting agent(s): {', '.join(unknown)}"
        if not selected_agents:
            return [], possible_topic, "No valid meeting agents selected."
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
) -> str:
    stripped = text.strip()
    if stripped in {"/start", "/help"}:
        return HELP_TEXT
    if stripped == "/whoami":
        if user_id is None:
            return "Telegram user id is unavailable in this context."
        return f"Your Telegram user id: {user_id}"
    if stripped == "/status":
        return render_status(mode, agents, allowed_user_ids)
    if stripped == "/agents":
        return render_agents(agents)
    if stripped.startswith("/ask "):
        rest = stripped[len("/ask ") :].strip()
        if " " not in rest:
            return "Use: /ask <agent_id> <question>"
        agent_id, question = rest.split(" ", 1)
        agent = find_agent(agents, agent_id)
        if not agent:
            return f"Unknown agent: {agent_id}\n\n{render_agents(agents)}"
        return ask_agent(agent, question, llm_client, prompts_path)
    if stripped.startswith("/meeting "):
        rest = stripped[len("/meeting ") :].strip()
        meeting_agents, topic, error = parse_meeting_request(rest, agents)
        if error:
            return f"{error}\n\n{render_agents(agents)}"
        if not topic:
            return "Use: /meeting <topic> or /meeting <agent_id,agent_id> <topic>"
        return run_meeting(meeting_agents, topic, llm_client, prompts_path)
    return "I did not understand the command.\n\n" + HELP_TEXT


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
                api.send_message(chat_id, "Access denied.")
                continue
            try:
                response = handle_text(
                    text,
                    agents,
                    llm_client,
                    config.prompts_path,
                    mode=config.mode,
                    user_id=user_id,
                    allowed_user_ids=config.allowed_user_ids,
                )
            except Exception as exc:
                response = f"Error: {exc}"
            try:
                api.send_message(chat_id, response)
            except (HTTPError, URLError, TimeoutError, SocketTimeout) as exc:
                print(f"Telegram sendMessage error: {exc}.")
        time.sleep(config.poll_interval_seconds)


def check_bot(config: TelegramConfig) -> str:
    api = TelegramAPI(config.token)
    bot_info = api.get_me()
    username = bot_info.get("username", "<unknown>")
    bot_id = bot_info.get("id", "<unknown>")
    return f"Telegram bot connection OK: @{username} (id: {bot_id})"
