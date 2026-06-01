from __future__ import annotations

import argparse
from pathlib import Path

from .agents import load_agents
from .artifacts import load_artifacts
from .llm import MockLLMClient, OpenAICompatibleLLMClient
from .orchestrator import build_readiness_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI engineering platform MVP tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Generate a pilot production readiness report.")
    review.add_argument("--project", required=True, type=Path, help="Folder with engineering artifacts.")
    review.add_argument("--agents", default=Path("configs/agents.json"), type=Path, help="Agent registry JSON.")
    review.add_argument("--output", required=True, type=Path, help="Markdown report output path.")
    review.add_argument(
        "--mode",
        choices=["heuristic", "mock-llm", "llm"],
        default="heuristic",
        help="Analysis mode. Use heuristic for offline runs, mock-llm for tests, llm for an OpenAI-compatible API.",
    )
    return parser


def run_review(project: Path, agents_path: Path, output: Path, mode: str) -> None:
    agents = load_agents(agents_path)
    artifacts = load_artifacts(project)
    llm_client = None
    if mode == "mock-llm":
        llm_client = MockLLMClient()
    elif mode == "llm":
        llm_client = OpenAICompatibleLLMClient.from_env()
    report = build_readiness_report(project, artifacts, agents, llm_client=llm_client)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Report written to {output}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "review":
        run_review(args.project, args.agents, args.output, args.mode)
