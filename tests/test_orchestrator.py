from pathlib import Path
import tempfile
import unittest

from ai_engineering_platform.agents import AgentProfile
from ai_engineering_platform.artifacts import load_artifacts
from ai_engineering_platform.llm import MockLLMClient
from ai_engineering_platform.orchestrator import build_readiness_report


class RecordingLLMClient:
    def __init__(self) -> None:
        self.messages: list[dict[str, str]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages = messages
        return "Recorded analysis"


class OrchestratorTest(unittest.TestCase):
    def test_report_contains_agent_finding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "requirements.md").write_text("power safety interface", encoding="utf-8")
            agents = [
                AgentProfile(
                    id="systems",
                    name="Systems Engineering Agent",
                    focus="Architecture",
                    keywords=["safety", "interface"],
                    expected_artifacts=["requirements"],
                )
            ]

            report = build_readiness_report(project, load_artifacts(project), agents)

        self.assertIn("Systems Engineering Agent", report)
        self.assertIn("safety", report)
        self.assertIn("Risk level", report)

    def test_report_can_include_mock_llm_analysis(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / "requirements.md").write_text("power safety interface", encoding="utf-8")
            agents = [
                AgentProfile(
                    id="systems",
                    name="Systems Engineering Agent",
                    focus="Architecture",
                    keywords=["safety"],
                    expected_artifacts=["requirements"],
                )
            ]

            report = build_readiness_report(
                project,
                load_artifacts(project),
                agents,
                llm_client=MockLLMClient(response_prefix="Test analysis"),
            )

        self.assertIn("LLM analysis", report)
        self.assertIn("Test analysis", report)

    def test_report_includes_role_prompt_in_llm_messages(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            prompts = root / "prompts"
            project.mkdir()
            prompts.mkdir()
            (project / "requirements.md").write_text("power safety interface", encoding="utf-8")
            (prompts / "systems.md").write_text("Always include source references.", encoding="utf-8")
            agents = [
                AgentProfile(
                    id="systems",
                    name="Systems Engineering Agent",
                    focus="Architecture",
                    keywords=["safety"],
                    expected_artifacts=["requirements"],
                )
            ]
            client = RecordingLLMClient()

            report = build_readiness_report(
                project,
                load_artifacts(project),
                agents,
                llm_client=client,
                prompts_dir=prompts,
            )

        self.assertIn("Recorded analysis", report)
        self.assertIn("Always include source references.", client.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
