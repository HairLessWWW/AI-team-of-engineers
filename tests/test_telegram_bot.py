import unittest

from ai_engineering_platform.agents import AgentProfile
from ai_engineering_platform.llm import MockLLMClient
from ai_engineering_platform.telegram_bot import TelegramConfig, find_agent, handle_text, render_agents, split_telegram_message


class TelegramBotTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agents = [
            AgentProfile(
                id="electrical",
                name="Electrical Lead Engineer Agent",
                focus="Electrical systems",
                keywords=[],
                expected_artifacts=[],
            )
        ]

    def test_find_agent_by_id(self) -> None:
        self.assertEqual(find_agent(self.agents, "electrical"), self.agents[0])
        self.assertIsNone(find_agent(self.agents, "mechanical"))

    def test_render_agents(self) -> None:
        rendered = render_agents(self.agents)
        self.assertIn("electrical", rendered)
        self.assertIn("Electrical Lead Engineer Agent", rendered)

    def test_handle_agents_command(self) -> None:
        response = handle_text("/agents", self.agents, MockLLMClient(), prompts_path=None)
        self.assertIn("electrical", response)

    def test_handle_ask_command(self) -> None:
        response = handle_text(
            "/ask electrical What blocks pilot production?",
            self.agents,
            MockLLMClient(response_prefix="Bot test"),
            prompts_path=None,
        )
        self.assertIn("Bot test", response)
        self.assertIn("What blocks pilot production", response)

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


if __name__ == "__main__":
    unittest.main()
