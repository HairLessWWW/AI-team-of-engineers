from __future__ import annotations

import argparse
import os
from pathlib import Path

from .agents import load_agents
from .artifacts import load_artifacts
from .llm import MockLLMClient, OpenAICompatibleLLMClient
from .orchestrator import build_readiness_report
from .telegram_bot import TelegramConfig, check_bot, run_bot


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="AI engineering platform MVP tools.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    review = subparsers.add_parser("review", help="Generate a pilot production readiness report.")
    review.add_argument("--project", required=True, type=Path, help="Folder with engineering artifacts.")
    review.add_argument("--agents", default=Path("configs/agents.json"), type=Path, help="Agent registry JSON.")
    review.add_argument("--prompts", default=Path("prompts"), type=Path, help="Folder with role prompt templates.")
    review.add_argument("--output", required=True, type=Path, help="Markdown report output path.")
    review.add_argument(
        "--mode",
        choices=["heuristic", "mock-llm", "llm"],
        default="heuristic",
        help="Analysis mode. Use heuristic for offline runs, mock-llm for tests, llm for an OpenAI-compatible API.",
    )

    telegram_bot = subparsers.add_parser("telegram-bot", help="Run the Telegram bot frontend.")
    telegram_bot.add_argument("--agents", default=Path("configs/agents.json"), type=Path, help="Agent registry JSON.")
    telegram_bot.add_argument("--prompts", default=Path("prompts"), type=Path, help="Folder with role prompt templates.")
    telegram_bot.add_argument(
        "--mode",
        choices=["mock-llm", "llm"],
        default=os.getenv("AI_ENGINEERING_BOT_MODE", "mock-llm"),
        help="Bot analysis mode. Use mock-llm for local testing or llm for an OpenAI-compatible API.",
    )

    subparsers.add_parser("telegram-check", help="Check Telegram bot token and connectivity.")
    return parser


def run_review(project: Path, agents_path: Path, prompts_path: Path, output: Path, mode: str) -> None:
    agents = load_agents(agents_path)
    artifacts = load_artifacts(project)
    llm_client = None
    if mode == "mock-llm":
        llm_client = MockLLMClient()
    elif mode == "llm":
        llm_client = OpenAICompatibleLLMClient.from_env()
    report = build_readiness_report(project, artifacts, agents, llm_client=llm_client, prompts_dir=prompts_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(report, encoding="utf-8")
    print(f"Report written to {output}")


def main() -> None:
    args = build_parser().parse_args()
    if args.command == "review":
        run_review(args.project, args.agents, args.prompts, args.output, args.mode)
    elif args.command == "telegram-bot":
        config = TelegramConfig.from_env()
        config = TelegramConfig(
            token=config.token,
            agents_path=args.agents,
            prompts_path=args.prompts,
            mode=args.mode,
            allowed_user_ids=config.allowed_user_ids,
        )
        run_bot(config)
    elif args.command == "telegram-check":
        config = TelegramConfig.from_env()
        print(check_bot(config))
