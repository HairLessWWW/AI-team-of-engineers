from pathlib import Path
import json
import tempfile
import unittest

from ai_engineering_platform.web_control import init_web_db, list_projects, save_agent, save_project, save_rule, list_rules


class WebControlTest(unittest.TestCase):
    def test_save_agent_updates_config_and_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_path = root / "agents.json"
            prompts_path = root / "prompts"
            agents_path.write_text('{"agents": []}', encoding="utf-8")

            save_agent(
                agents_path,
                prompts_path,
                {
                    "id": ["electrical"],
                    "name": ["Ведущий электрик"],
                    "focus": ["Питание и защиты"],
                    "keywords": ["power, cable"],
                    "expected_artifacts": ["bom, схемы"],
                    "prompt": ["Отвечай строго в роли электрика."],
                },
            )

            data = json.loads(agents_path.read_text(encoding="utf-8"))
            prompt = (prompts_path / "electrical.md").read_text(encoding="utf-8")

        self.assertEqual(data["agents"][0]["id"], "electrical")
        self.assertEqual(data["agents"][0]["keywords"], ["power", "cable"])
        self.assertIn("роли электрика", prompt)

    def test_save_project_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            save_project(
                db_path,
                {
                    "name": ["Антропоморфный робот V1"],
                    "status": ["active"],
                    "goal": ["Пилотная сборка"],
                    "agents": ["electrical", "manufacturing"],
                    "notes": ["Стартовый проект"],
                },
            )
            projects = list_projects(db_path)

        self.assertEqual(len(projects), 1)
        self.assertEqual(projects[0]["agents"], ["electrical", "manufacturing"])

    def test_save_rule_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            save_rule(db_path, {"title": ["Human approval"], "scope": ["safety"], "content": ["Не утверждать safety-critical решения."]})
            rules = list_rules(db_path)

        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0]["scope"], "safety")


if __name__ == "__main__":
    unittest.main()
