from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TEXT_SUFFIXES = {".md", ".txt", ".csv", ".json", ".yaml", ".yml", ".st", ".c", ".cpp", ".h", ".py"}


@dataclass(frozen=True)
class Artifact:
    path: Path
    text: str

    @property
    def name(self) -> str:
        return self.path.name


def load_artifacts(project_dir: Path) -> list[Artifact]:
    artifacts: list[Artifact] = []
    for path in sorted(project_dir.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        if path.suffix.lower() in TEXT_SUFFIXES:
            artifacts.append(Artifact(path=path, text=path.read_text(encoding="utf-8", errors="ignore")))
        else:
            artifacts.append(Artifact(path=path, text=""))
    return artifacts
