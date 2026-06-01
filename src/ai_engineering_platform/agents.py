from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path


@dataclass(frozen=True)
class AgentProfile:
    id: str
    name: str
    focus: str
    keywords: list[str]
    expected_artifacts: list[str]


def load_agents(config_path: Path) -> list[AgentProfile]:
    data = json.loads(config_path.read_text(encoding="utf-8"))
    return [
        AgentProfile(
            id=item["id"],
            name=item["name"],
            focus=item["focus"],
            keywords=item.get("keywords", []),
            expected_artifacts=item.get("expected_artifacts", []),
        )
        for item in data["agents"]
    ]
