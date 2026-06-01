from pathlib import Path
import tempfile
import unittest

from ai_engineering_platform.agents import AgentProfile
from ai_engineering_platform.artifacts import load_artifacts
from ai_engineering_platform.orchestrator import build_readiness_report


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


if __name__ == "__main__":
    unittest.main()
