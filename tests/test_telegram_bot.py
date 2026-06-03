from pathlib import Path
import tempfile
import unittest
from urllib.error import HTTPError

from ai_engineering_platform.access_control import AccessStore
from ai_engineering_platform.agents import AgentProfile
from ai_engineering_platform.conversation_memory import ConversationMemory
from ai_engineering_platform.llm import MockLLMClient
from ai_engineering_platform.project_materials import ProjectMaterials
from ai_engineering_platform.telegram_bot import (
    BotSession,
    TelegramConfig,
    build_llm_client,
    find_agent,
    handle_callback,
    handle_text,
    main_menu_keyboard,
    parse_meeting_request,
    render_agents,
    split_telegram_message,
)


class RateLimitedLLMClient:
    def complete(self, messages: list[dict[str, str]]) -> str:
        raise HTTPError(url="https://api.example.test", code=429, msg="Too Many Requests", hdrs=None, fp=None)


class RecordingLLMClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "Recorded response"


class TelegramBotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agents = [
            AgentProfile(
                id="electrical",
                name="Electrical Lead Engineer Agent",
                focus="Electrical systems",
                keywords=[],
                expected_artifacts=[],
            ),
            AgentProfile(
                id="manufacturing",
                name="Manufacturing Engineering Agent",
                focus="Production readiness",
                keywords=[],
                expected_artifacts=[],
            ),
        ]

    def test_find_agent_by_id(self) -> None:
        self.assertEqual(find_agent(self.agents, "electrical"), self.agents[0])
        self.assertIsNone(find_agent(self.agents, "mechanical"))

    def test_find_agent_by_russian_alias(self) -> None:
        self.assertEqual(find_agent(self.agents, "электрик"), self.agents[0])
        self.assertEqual(find_agent(self.agents, "производство"), self.agents[1])

    def test_render_agents_has_friendly_roles(self) -> None:
        rendered = render_agents(self.agents)
        self.assertIn("Специалисты", rendered)
        self.assertIn("Ведущий электрик", rendered)
        self.assertIn("Технолог производства", rendered)

    def test_start_returns_menu_keyboard(self) -> None:
        response = handle_text("/start", self.agents, MockLLMClient(), prompts_path=None)
        self.assertIn("Выбери специалиста", response.text)
        self.assertIsNotNone(response.reply_markup)

    def test_help_contains_commands(self) -> None:
        response = handle_text("/help", self.agents, MockLLMClient(), prompts_path=None)
        self.assertIn("/allow", response.text)
        self.assertIsNotNone(response.reply_markup)

    def test_handle_whoami_command(self) -> None:
        response = handle_text("/whoami", self.agents, MockLLMClient(), prompts_path=None, user_id=123)
        self.assertIn("123", response.text)
        self.assertIsNotNone(response.reply_markup)

    def test_handle_status_command(self) -> None:
        response = handle_text(
            "/status",
            self.agents,
            MockLLMClient(),
            prompts_path=None,
            mode="mock-llm",
            allowed_user_ids={123},
        )
        self.assertIn("Статус бота", response.text)
        self.assertIn("mock-llm", response.text)

    def test_handle_ask_command(self) -> None:
        response = handle_text(
            "/ask electrical What blocks pilot production?",
            self.agents,
            MockLLMClient(response_prefix="Bot test"),
            prompts_path=None,
        )
        self.assertIn("Bot test", response.text)
        self.assertIn("What blocks pilot production", response.text)
        self.assertIsNotNone(response.reply_markup)
        self.assertIn("post:menu:agents", str(response.reply_markup))

    def test_plain_text_goes_to_selected_agent(self) -> None:
        session = BotSession(mode="agent", selected_agent_id="electrical")
        response = handle_text(
            "Что блокирует пилотную сборку?",
            self.agents,
            MockLLMClient(response_prefix="Bot test"),
            prompts_path=None,
            session=session,
        )
        self.assertIn("Bot test", response.text)
        self.assertIn("Что блокирует пилотную сборку", response.text)

    def test_agent_prompt_contains_role_boundary(self) -> None:
        client = RecordingLLMClient()
        response = handle_text(
            "/ask electrical Как выбрать материал корпуса?",
            self.agents,
            client,
            prompts_path=None,
        )

        self.assertIn("Recorded response", response.text)
        self.assertIn("Граница твоей роли", client.messages[0]["content"])
        self.assertIn("Фильтр выхода за роль", client.messages[0]["content"])
        self.assertIn("вне роли электрика", client.messages[0]["content"])

    def test_agent_receives_recent_memory_context(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = ConversationMemory(Path(tmp) / "memory.db")
            memory.add_event(123, "electrical", "user", "Первый вопрос про питание")
            memory.add_event(123, "electrical", "assistant", "Первый ответ про питание")
            client = RecordingLLMClient()

            response = handle_text(
                "/ask electrical Продолжи мысль",
                self.agents,
                client,
                prompts_path=None,
                user_id=123,
                memory=memory,
                memory_depth=4,
            )

            events_count = memory.count_events(123)

        self.assertIn("Recorded response", response.text)
        self.assertIn("Первый вопрос про питание", client.messages[1]["content"])
        self.assertIn("Первый ответ про питание", client.messages[1]["content"])
        self.assertEqual(events_count, 4)

    def test_agent_receives_recent_project_materials(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            materials = ProjectMaterials(Path(tmp) / "materials.db", Path(tmp) / "files")
            materials.add_material(123, "file", "tz.docx", "Требование: проверить питание 48В")
            client = RecordingLLMClient()

            response = handle_text(
                "/ask electrical Что важно проверить?",
                self.agents,
                client,
                prompts_path=None,
                user_id=123,
                materials=materials,
                materials_depth=3,
            )

        self.assertIn("Recorded response", response.text)
        self.assertIn("Материалы проекта", client.messages[1]["content"])
        self.assertIn("Требование: проверить питание 48В", client.messages[1]["content"])

    def test_forget_clears_selected_agent_memory(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = ConversationMemory(Path(tmp) / "memory.db")
            memory.add_event(123, "electrical", "user", "Вопрос")
            session = BotSession(mode="agent", selected_agent_id="electrical")

            response = handle_text(
                "/forget",
                self.agents,
                MockLLMClient(),
                prompts_path=None,
                user_id=123,
                session=session,
                memory=memory,
            )

            events_count = memory.count_events(123)

        self.assertIn("очищена", response.text)
        self.assertEqual(events_count, 0)

    def test_handle_ask_429_fallback(self) -> None:
        response = handle_text(
            "/ask electrical What blocks pilot production?",
            self.agents,
            RateLimitedLLMClient(),
            prompts_path=None,
        )
        self.assertIn("429 Too Many Requests", response.text)
        self.assertIn("Сам бот работает", response.text)

    def test_main_menu_keyboard_contains_friendly_actions(self) -> None:
        keyboard = main_menu_keyboard()
        rendered = str(keyboard)
        self.assertIn("menu:agents", rendered)
        self.assertIn("meeting:start", rendered)
        self.assertIn("Специалисты", rendered)

    def test_handle_callback_agent_menu(self) -> None:
        response = handle_callback(
            "menu:agents",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
        )
        self.assertIn("Специалисты", response.text)
        self.assertIn("agent:electrical", str(response.reply_markup))

    def test_handle_callback_agent_profile(self) -> None:
        response = handle_callback(
            "agent:electrical",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
        )
        self.assertIn("Ведущий электрик", response.text)
        self.assertIn("chat:electrical", str(response.reply_markup))

    def test_handle_callback_chat_selects_agent(self) -> None:
        session = BotSession()
        response = handle_callback(
            "chat:electrical",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
            session=session,
        )
        self.assertEqual(session.mode, "agent")
        self.assertEqual(session.selected_agent_id, "electrical")
        self.assertIn("Чат со специалистом", response.text)

    def test_post_callback_uses_same_logic_for_new_navigation_message(self) -> None:
        response = handle_callback(
            "post:menu:agents",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
        )
        self.assertIn("Специалисты", response.text)
        self.assertIn("agent:electrical", str(response.reply_markup))

    def test_meeting_selection_toggle(self) -> None:
        session = BotSession()
        handle_callback(
            "meeting:start",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
            session=session,
        )
        response = handle_callback(
            "meeting:toggle:electrical",
            self.agents,
            mode="mock-llm",
            user_id=123,
            allowed_user_ids=None,
            session=session,
        )
        self.assertNotIn("electrical", session.meeting_agent_ids)
        self.assertIn("Совещание", response.text)

    def test_meeting_topic_runs_selected_agents(self) -> None:
        session = BotSession(mode="meeting_topic", meeting_agent_ids={"electrical"})
        response = handle_text(
            "Готовность руки к пилотной сборке",
            self.agents,
            MockLLMClient(response_prefix="Bot test"),
            prompts_path=None,
            session=session,
        )
        self.assertIn("Инженерное совещание", response.text)
        self.assertIn("Bot test", response.text)

    def test_parse_meeting_request_with_selected_agents(self) -> None:
        selected, topic, error = parse_meeting_request("electrical,manufacturing Pilot readiness", self.agents)
        self.assertIsNone(error)
        self.assertEqual([agent.id for agent in selected], ["electrical", "manufacturing"])
        self.assertEqual(topic, "Pilot readiness")

    def test_split_telegram_message(self) -> None:
        chunks = split_telegram_message("a" * 5000, limit=1000)
        self.assertEqual(len(chunks), 5)
        self.assertTrue(all(len(chunk) <= 1000 for chunk in chunks))

    def test_allowed_user_ids_from_env(self) -> None:
        with unittest.mock.patch.dict(
            "os.environ",
            {"TELEGRAM_BOT_TOKEN": "token", "TELEGRAM_ALLOWED_USER_IDS": "1, 2"},
            clear=True,
        ):
            config = TelegramConfig.from_env()

        self.assertEqual(config.allowed_user_ids, {1, 2})

    def test_build_deepseek_client_requires_key(self) -> None:
        with unittest.mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(RuntimeError):
                build_llm_client("deepseek")

    def test_users_command_requires_admin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "access.db")
            store.ensure_user(1, role="member")

            response = handle_text(
                "/users",
                self.agents,
                MockLLMClient(),
                prompts_path=None,
                user_id=1,
                access_store=store,
            )

        self.assertIn("Недостаточно прав", response.text)

    def test_allow_command_adds_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "access.db")
            store.ensure_user(1, role="owner")

            response = handle_text(
                "/allow 2 admin",
                self.agents,
                MockLLMClient(),
                prompts_path=None,
                user_id=1,
                access_store=store,
            )
            added = store.get_user(2)

        self.assertIn("добавлен", response.text)
        self.assertIsNotNone(added)
        assert added is not None
        self.assertEqual(added.role, "admin")


if __name__ == "__main__":
    unittest.main()
