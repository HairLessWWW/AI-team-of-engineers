from pathlib import Path
import tempfile
import unittest

from ai_engineering_platform.conversation_memory import ConversationMemory


class ConversationMemoryTest(unittest.TestCase):
    def test_recent_events_are_agent_scoped_and_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = ConversationMemory(Path(tmp) / "memory.db")
            memory.add_event(1, "electrical", "user", "one")
            memory.add_event(1, "manufacturing", "user", "other")
            memory.add_event(1, "electrical", "assistant", "two")

            events = memory.get_recent_events(1, "electrical", 10)

        self.assertEqual([event.content for event in events], ["one", "two"])

    def test_clear_user_agent_deletes_only_selected_agent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            memory = ConversationMemory(Path(tmp) / "memory.db")
            memory.add_event(1, "electrical", "user", "one")
            memory.add_event(1, "manufacturing", "user", "other")

            memory.clear_user_agent(1, "electrical")

            electrical = memory.get_recent_events(1, "electrical", 10)
            manufacturing = memory.get_recent_events(1, "manufacturing", 10)

        self.assertEqual(electrical, [])
        self.assertEqual([event.content for event in manufacturing], ["other"])


if __name__ == "__main__":
    unittest.main()
