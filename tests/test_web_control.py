from pathlib import Path
import json
import tempfile
import unittest

from ai_engineering_platform.web_control import (
    WebConfig,
    ControlCenterHandler,
    authenticate_user,
    delete_org_position,
    delete_org_structure,
    hash_password,
    init_web_db,
    list_org_positions,
    list_org_structures,
    list_projects,
    list_rules,
    list_web_users,
    save_agent,
    save_agent_layout,
    save_org_structure,
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
        self.assertIn('class="drag-handle" draggable="true"', html)
        self.assertIn("/agents/layout", html)

    def test_render_org_contains_cto_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            agents_path = root / "agents.json"
            agents_path.write_text('{"agents": []}', encoding="utf-8")
            db_path = root / "web.db"
            init_web_db(db_path)
            config = WebConfig(password="secret", agents_path=agents_path, prompts_path=root / "prompts", web_db_path=db_path)
            handler = object.__new__(ControlCenterHandler)
            handler.config = config

            html = handler.render_org()

        self.assertIn("Структура технического директора", html)
        self.assertIn("Electrical Lead Engineer", html)
        self.assertIn("/org/structure/delete", html)
        self.assertIn("/org/position/delete", html)
        self.assertIn("Редактировать", html)
        self.assertIn("structure-edit-", html)
        self.assertIn("position-edit-", html)
        self.assertNotIn("inline-editor", html)
        self.assertIn("data-close-modal", html)

    def test_delete_org_position(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            position = list_org_positions(db_path)[0]

            delete_org_position(db_path, position["id"])
            positions = list_org_positions(db_path)

        self.assertEqual(len(positions), 12)

    def test_delete_org_structure_removes_positions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            structure = list_org_structures(db_path)[0]

            delete_org_structure(db_path, structure["id"])
            structures = list_org_structures(db_path)
            positions = list_org_positions(db_path)

        self.assertEqual(structures, [])
        self.assertEqual(positions, [])

    def test_delete_parent_org_structure_is_blocked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            parent = list_org_structures(db_path)[0]
            save_org_structure(
                db_path,
                {"name": ["Дочерняя"], "parent_id": [str(parent["id"])], "description": [""], "sort_order": ["1"]},
            )

            with self.assertRaises(ValueError):
                delete_org_structure(db_path, parent["id"])

    def test_save_agent_layout_updates_department_and_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            agents_path = Path(tmp) / "agents.json"
            agents_path.write_text(
                json.dumps(
                    {
                        "agents": [
                            {"id": "a", "name": "A", "focus": "", "department": "Old", "keywords": [], "expected_artifacts": []},
                            {"id": "b", "name": "B", "focus": "", "department": "Old", "keywords": [], "expected_artifacts": []},
                        ]
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            save_agent_layout(
                agents_path,
                [
                    {"id": "b", "department": "New", "order": 0},
                    {"id": "a", "department": "New", "order": 1},
                ],
            )
            data = json.loads(agents_path.read_text(encoding="utf-8"))

        self.assertEqual([agent["id"] for agent in data["agents"]], ["b", "a"])
        self.assertEqual(data["agents"][0]["department"], "New")
        self.assertEqual(data["agents"][1]["order"], 1)

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

    def test_seed_cto_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            structures = list_org_structures(db_path)
            positions = list_org_positions(db_path, structures[0]["id"])

        self.assertEqual(structures[0]["name"], "Структура технического директора")
        self.assertEqual(len(positions), 13)
        self.assertIn("Electrical Lead Engineer", [position["title"] for position in positions])

    def test_save_child_org_structure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "web.db"
            init_web_db(db_path)
            parent = list_org_structures(db_path)[0]
            save_org_structure(
                db_path,
                {
                    "name": ["Производственный блок"],
                    "parent_id": [str(parent["id"])],
                    "description": ["Сборка и качество"],
                    "sort_order": ["10"],
                },
            )
            structures = list_org_structures(db_path)

        child = next(item for item in structures if item["name"] == "Производственный блок")
        self.assertEqual(child["parent_id"], parent["id"])

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
