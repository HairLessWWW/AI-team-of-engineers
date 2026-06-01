# Telegram Bot MVP

Telegram Bot is the first lightweight frontend for AI Team of Engineers.

It lets the CTO:

- list available AI employees;
- ask one AI employee a direct question;
- gather a short multi-agent engineering meeting;
- run in mock mode before connecting a real LLM.

## Create a Telegram bot

1. Open Telegram and message `@BotFather`.
2. Run `/newbot`.
3. Choose a display name and username.
4. Copy the token.

Do not commit the token to GitHub.

## Recommended local setup

Set variables directly in PowerShell:

```powershell
$env:TELEGRAM_BOT_TOKEN = "token-from-botfather"
$env:AI_ENGINEERING_BOT_MODE = "mock-llm"
$env:PYTHONPATH = "src"
python -m ai_engineering_platform telegram-bot
```

## Limit access to your Telegram user

To avoid other people using the bot, set `TELEGRAM_ALLOWED_USER_IDS`.

You can get your user id by messaging a Telegram user-info bot.

```powershell
$env:TELEGRAM_ALLOWED_USER_IDS = "123456789"
```

Multiple users can be comma-separated:

```powershell
$env:TELEGRAM_ALLOWED_USER_IDS = "123456789,987654321"
```

## Commands

```text
/start
/agents
/ask <agent_id> <question>
/meeting <topic>
```

Examples:

```text
/ask electrical What blocks pilot assembly?
/ask manufacturing What do we need before a pilot batch?
/meeting Readiness of humanoid left arm for pilot production
```

## Modes

Mock mode is useful for checking the Telegram workflow without LLM costs.

```powershell
$env:AI_ENGINEERING_BOT_MODE = "mock-llm"
```

LLM mode uses the OpenAI-compatible API client.

```powershell
$env:AI_ENGINEERING_BOT_MODE = "llm"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-4.1-mini"
```

## Current limitations

- The bot uses long polling, not webhooks.
- Project memory and file uploads are not implemented yet.
- Meetings currently call all MVP agents from `configs/agents.json`.
- Human approval workflow is not implemented yet.
