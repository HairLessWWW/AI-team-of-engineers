# Ubuntu Server Setup

This guide deploys the Telegram bot on an Ubuntu 24.04 VPS.

## 0. Security first

If the initial root password was shared in a screenshot or chat, rotate it immediately after first login.

```bash
passwd
```

Recommended next step: create a non-root deploy user and use SSH keys.

## 1. Connect to the server

```powershell
ssh root@<server-ip>
```

## 2. Update the OS

```bash
apt update
apt upgrade -y
```

## 3. Install packages

```bash
apt install -y git python3 python3-venv python3-pip ca-certificates
```

## 4. Clone the repository

```bash
cd /opt
git clone https://github.com/HairLessWWW/AI-team-of-engineers.git ai-team-of-engineers
cd /opt/ai-team-of-engineers
```

## 5. Create Python virtual environment

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
```

The current MVP has no external runtime dependencies.

## 6. Create environment file

```bash
mkdir -p /etc/ai-team-of-engineers
nano /etc/ai-team-of-engineers/telegram-bot.env
chmod 600 /etc/ai-team-of-engineers/telegram-bot.env
```

Example:

```bash
TELEGRAM_BOT_TOKEN=replace-with-botfather-token
TELEGRAM_ALLOWED_USER_IDS=123456789
TELEGRAM_OWNER_IDS=123456789
TELEGRAM_ACCESS_DB=/var/lib/ai-team-of-engineers/access.db
AI_ENGINEERING_BOT_MODE=mock-llm
PYTHONPATH=/opt/ai-team-of-engineers/src
```

For real LLM mode:

```bash
AI_ENGINEERING_BOT_MODE=llm
OPENAI_API_KEY=replace-with-openai-compatible-api-key
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

For DeepSeek mode:

```bash
AI_ENGINEERING_BOT_MODE=deepseek
DEEPSEEK_API_KEY=replace-with-deepseek-api-key
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

## 7. Check Telegram connectivity

```bash
cd /opt/ai-team-of-engineers
set -a
. /etc/ai-team-of-engineers/telegram-bot.env
set +a
.venv/bin/python -m ai_engineering_platform telegram-check
```

Expected result:

```text
Telegram bot connection OK: @ai_engineers_team_bot (id: ...)
```

## 8. Install systemd service

```bash
cp /opt/ai-team-of-engineers/deployment/systemd/ai-engineering-telegram-bot.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable ai-engineering-telegram-bot
systemctl start ai-engineering-telegram-bot
```

## 9. Check logs

```bash
systemctl status ai-engineering-telegram-bot
journalctl -u ai-engineering-telegram-bot -f
```

## 10. Update deployment

```bash
cd /opt/ai-team-of-engineers
git pull
systemctl restart ai-engineering-telegram-bot
```

## Firewall

For the current long-polling bot, inbound Telegram ports are not required.

Recommended open ports:

- `22/tcp` for SSH;
- `80/tcp` and `443/tcp` later for web dashboard/API.
