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

Before starting the long-running bot, check Telegram connectivity:

```powershell
$env:PYTHONPATH = "src"
$env:TELEGRAM_BOT_TOKEN = "token-from-botfather"
python -m ai_engineering_platform telegram-check
```

If this command times out, the machine cannot reach `api.telegram.org`. Check VPN, proxy, firewall, hosting network rules, or Telegram availability from the current network.

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
/whoami
/status
/agents
/ask <agent_id> <question>
/meeting <topic>
/meeting <agent_id,agent_id> <topic>
```

Examples:

```text
/ask electrical What blocks pilot assembly?
/ask электрик Что блокирует пилотную сборку?
/ask manufacturing What do we need before a pilot batch?
/meeting Readiness of humanoid left arm for pilot production
/meeting systems,electrical,manufacturing Readiness of humanoid left arm for pilot production
```

## Agent aliases

Supported aliases:

- `электрик`, `электрика` -> `electrical`
- `производство`, `технолог` -> `manufacturing`
- `сертификация`, `документация` -> `certification_docs`
- `архитектор`, `системщик` -> `systems`

## Operational commands

Use `/whoami` to get your Telegram user id for `TELEGRAM_ALLOWED_USER_IDS`.

Use `/status` to check:

- current bot mode;
- number of loaded agents;
- whether access is open or restricted;
- Telegram frontend mode.

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
- Network timeouts are retried during polling.
- LLM provider `429 Too Many Requests` errors are reported as a readable fallback message.
- Project memory and file uploads are not implemented yet.
- Meetings call all MVP agents by default, or selected agents when provided.
- Human approval workflow is not implemented yet.
