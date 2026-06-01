from __future__ import annotations

import argparse
from pathlib import Path

from .agents import load_agents
from .artifacts import load_artifacts
from .orchestrator import build_readiness_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI engineering platform MVP tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Generate a pilot production readiness report.")
    review.add_argument("--project", required=True, type=Path, help="Folder with engineering artifacts.")
    review.add_argument("--agents", default=Path("configs/agents.json"), type=Path, help="Agent registry JSON.")
    review.add_argument("--output", required=True, type=Path, help="Markdown report output path.")
    return parser


def run_review(project: Path, agents_path: Path, output: Path) -> None:
    agents = load_agents(agents_path)
    artifacts = load_artifacts(project)
    report = build_readiness_report(project, artifacts, agents)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Report written to {output}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "review":
        run_review(args.project, args.agents, args.output)
