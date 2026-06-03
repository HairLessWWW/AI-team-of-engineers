from pathlib import Path
import tempfile
import unittest

from ai_engineering_platform.access_control import AccessStore, seed_owner_users


class AccessControlTest(unittest.TestCase):
    def test_seed_owner_allows_admin_actions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "access.db")
            seed_owner_users(store, {100})

            user = store.get_user(100)

        self.assertIsNotNone(user)
        assert user is not None
        self.assertEqual(user.role, "owner")
        self.assertTrue(user.is_active)

    def test_member_can_be_disabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "access.db")
            store.ensure_user(200, role="member")
            self.assertTrue(store.is_allowed(200))

            store.set_active(200, False)

            self.assertFalse(store.is_allowed(200))

    def test_admin_detection(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AccessStore(Path(tmp) / "access.db")
            store.ensure_user(1, role="admin")
            store.ensure_user(2, role="member")

            self.assertTrue(store.is_admin(1))
            self.assertFalse(store.is_admin(2))


if __name__ == "__main__":
    unittest.main()
