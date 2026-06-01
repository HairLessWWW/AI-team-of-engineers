from __future__ import annotations

from pathlib import Path


def load_agent_prompt(agent_id: str, prompts_dir: Path | None) -> str | None:
    if prompts_dir is None:
        return None
    prompt_path = prompts_dir / f"{agent_id}.md"
    if not prompt_path.exists():
        return None
    return prompt_path.read_text(encoding="utf-8")
