from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .agents import AgentProfile
from .artifacts import Artifact


@dataclass(frozen=True)
class AgentFinding:
    agent_name: str
    focus: str
    matched_keywords: list[str]
    missing_artifacts: list[str]
    source_files: list[str]

    @property
    def risk_level(self) -> str:
        if len(self.missing_artifacts) >= 3:
            return "high"
        if self.missing_artifacts:
            return "medium"
        if not self.matched_keywords:
            return "medium"
        return "low"


def analyze_agent(agent: AgentProfile, artifacts: list[Artifact], project_dir: Path) -> AgentFinding:
    combined_text = "\n".join(f"{item.name}\n{item.text}" for item in artifacts).lower()
    matched_keywords = [keyword for keyword in agent.keywords if keyword.lower() in combined_text]

    file_names = " ".join(item.name.lower() for item in artifacts)
    missing_artifacts = [
        artifact_name
        for artifact_name in agent.expected_artifacts
        if artifact_name.lower() not in file_names and artifact_name.lower() not in combined_text
    ]

    source_files = []
    for item in artifacts:
        item_text = f"{item.name}\n{item.text}".lower()
        if any(keyword.lower() in item_text for keyword in agent.keywords):
            source_files.append(str(item.path.relative_to(project_dir)))

    return AgentFinding(
        agent_name=agent.name,
        focus=agent.focus,
        matched_keywords=matched_keywords,
        missing_artifacts=missing_artifacts,
        source_files=source_files,
    )


def build_readiness_report(project_dir: Path, artifacts: list[Artifact], agents: list[AgentProfile]) -> str:
    findings = [analyze_agent(agent, artifacts, project_dir) for agent in agents]
    high_or_medium = [item for item in findings if item.risk_level in {"high", "medium"}]

    lines = [
        "# Pilot Production Readiness Review",
        "",
        f"Project folder: `{project_dir}`",
        f"Artifacts analyzed: {len(artifacts)}",
        "",
        "## Executive Summary",
        "",
        f"- Agents involved: {len(agents)}",
        f"- High/medium risk areas: {len(high_or_medium)}",
        "- Final engineering approval required: yes",
        "",
        "## Agent Findings",
        "",
    ]

    for finding in findings:
        lines.extend(
            [
                f"### {finding.agent_name}",
                "",
                f"Focus: {finding.focus}",
                "",
                f"Risk level: `{finding.risk_level}`",
                "",
                "Matched signals:",
            ]
        )
        if finding.matched_keywords:
            lines.extend(f"- {keyword}" for keyword in finding.matched_keywords)
        else:
            lines.append("- No direct signals found in available text artifacts.")

        lines.extend(["", "Missing or weak artifacts:"])
        if finding.missing_artifacts:
            lines.extend(f"- {artifact}" for artifact in finding.missing_artifacts)
        else:
            lines.append("- No expected artifact gaps detected by the MVP heuristic.")

        lines.extend(["", "Source files:"])
        if finding.source_files:
            lines.extend(f"- `{source}`" for source in finding.source_files)
        else:
            lines.append("- No source file matched this agent's keyword set.")
        lines.append("")

    lines.extend(
        [
            "## CTO Questions",
            "",
            "- Which missing artifacts block pilot assembly?",
            "- Which findings require human safety review?",
            "- Which BOM items have no second source?",
            "- Which tests are mandatory before the next prototype build?",
            "",
            "## Next Actions",
            "",
            "- Assign each medium/high risk area to a responsible lead.",
            "- Add source documents for missing artifacts.",
            "- Run a human design review before making production decisions.",
        ]
    )
    return "\n".join(lines) + "\n"
