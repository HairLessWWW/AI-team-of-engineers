import os
import unittest
from unittest.mock import patch

from ai_engineering_platform.llm import DeepSeekLLMClient, MockLLMClient, OpenAICompatibleLLMClient


class LLMClientTest(unittest.TestCase):
    def test_mock_client_returns_deterministic_response(self) -> None:
        client = MockLLMClient(response_prefix="Mock")
        response = client.complete([{"role": "user", "content": "Analyze safety requirements."}])

        self.assertIn("Mock", response)
        self.assertIn("Analyze safety requirements", response)

    def test_openai_compatible_client_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                OpenAICompatibleLLMClient.from_env()

    def test_openai_compatible_client_reads_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "OPENAI_API_KEY": "test-key",
                "OPENAI_MODEL": "test-model",
                "OPENAI_BASE_URL": "https://example.test/v1",
            },
            clear=True,
        ):
            client = OpenAICompatibleLLMClient.from_env()

        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(client.model, "test-model")
        self.assertEqual(client.base_url, "https://example.test/v1")

    def test_deepseek_client_requires_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaises(RuntimeError):
                DeepSeekLLMClient.from_env()

    def test_deepseek_client_reads_env(self) -> None:
        with patch.dict(
            os.environ,
            {
                "DEEPSEEK_API_KEY": "test-key",
                "DEEPSEEK_MODEL": "deepseek-v4-pro",
                "DEEPSEEK_BASE_URL": "https://api.deepseek.com",
            },
            clear=True,
        ):
            client = DeepSeekLLMClient.from_env()

        self.assertEqual(client.api_key, "test-key")
        self.assertEqual(client.model, "deepseek-v4-pro")
        self.assertEqual(client.base_url, "https://api.deepseek.com")


if __name__ == "__main__":
    unittest.main()
