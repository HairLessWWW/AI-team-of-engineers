from pathlib import Path
import json
import tempfile
import unittest

from ai_engineering_platform.web_control import (
    WebConfig,
    ControlCenterHandler,
    authenticate_user,
    hash_password,
    init_web_db,
    list_projects,
    list_rules,
    list_web_users,
    save_agent,
    save_project,
    save_rule,
    save_web_user,
    seed_admin_user,
    verify_password,
)


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
                    "department": ["Инженерия продукта"],
                    "focus": ["Питание и защиты"],
                    "keywords": ["power, cable"],
                    "expected_artifacts": ["bom, схемы"],
                    "prompt": ["Отвечай строго в роли электрика."],
                },
            )

            data = json.loads(agents_path.read_text(encoding="utf-8"))
            prompt = (prompts_path / "electrical.md").read_text(encoding="utf-8")

        self.assertEqual(data["agents"][0]["id"], "electrical")
        self.assertEqual(data["agents"][0]["department"], "Инженерия продукта")
        self.assertEqual(data["agents"][0]["keywords"], ["power", "cable"])
        self.assertIn("роли электрика", prompt)

    def test_render_agents_uses_grouped_cards_and_modals(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_path = root / "agents.json"
            prompts_path = root / "prompts"
            agents_path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {
                                "id": "electrical",
                                "name": "Ведущий электрик",
                                "department": "Инженерия продукта",
                                "focus": "Питание и защиты",
                                "keywords": ["power"],
                                "expected_artifacts": ["bom"],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            config = WebConfig(password="secret", agents_path=agents_path, prompts_path=prompts_path, web_db_path=root / "web.db")
            handler = object.__new__(ControlCenterHandler)
            handler.config = config

            html = handler.render_agents()

        self.assertIn("Инженерия продукта", html)
        self.assertIn("agent-card", html)
        self.assertIn("modal-card", html)

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

    def test_password_hash_roundtrip(self) -> None:
        stored = hash_password("secret")

        self.assertTrue(verify_password("secret", stored))
        self.assertFalse(verify_password("wrong", stored))
        self.assertNotIn("secret", stored)

    def test_seed_admin_and_authenticate(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            seed_admin_user(db_path, "secret")
            user = authenticate_user(db_path, "admin", "secret")
            users = list_web_users(db_path)

        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["role"], "owner")
        self.assertEqual(len(users), 1)

    def test_save_web_user(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            save_web_user(db_path, {"username": ["engineer"], "password": ["pw"], "role": ["member"], "is_active": ["1"]})
            user = authenticate_user(db_path, "engineer", "pw")

        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user["role"], "member")


if __name__ == "__main__":
    unittest.main()
