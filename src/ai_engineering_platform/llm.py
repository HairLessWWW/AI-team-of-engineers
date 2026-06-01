from __future__ import annotations

from dataclasses import dataclass
import json
import os
from typing import Protocol
from urllib import request


class LLMClient(Protocol):
    """Minimal LLM client interface used by platform workflows."""

    def complete(self, messages: list[dict[str, str]]) -> str:
        """Return a text completion for chat-style messages."""


@dataclass(frozen=True)
class MockLLMClient:
    """Deterministic test client for local development and CI."""

    response_prefix: str = "Mock LLM analysis"

    def complete(self, messages: list[dict[str, str]]) -> str:
        user_messages = [message["content"] for message in messages if message.get("role") == "user"]
        last_user_message = user_messages[-1] if user_messages else ""
        preview = " ".join(last_user_message.split())[:240]
        return f"{self.response_prefix}: {preview}"


@dataclass(frozen=True)
class OpenAICompatibleLLMClient:
    """Small OpenAI-compatible chat completions client.

    This avoids adding an SDK dependency in the early MVP. It works with APIs
    that expose `/chat/completions` and accept OpenAI-style payloads.
    """

    api_key: str
    model: str
    base_url: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60

    @classmethod
    def from_env(cls) -> "OpenAICompatibleLLMClient":
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is required for --mode llm.")
        return cls(
            api_key=api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),
            base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1").rstrip("/"),
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        payload = json.dumps({"model": self.model, "messages": messages, "temperature": 0.2}).encode("utf-8")
        http_request = request.Request(
            url=f"{self.base_url}/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        with request.urlopen(http_request, timeout=self.timeout_seconds) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"]
