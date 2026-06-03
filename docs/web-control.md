# Web Control Center

Веб-кабинет - центр управления AI-командой.

## Разделы

- `Панель` - сводка по агентам, проектам, материалам и истории.
- `Агенты` - редактирование карточек ролей и prompt-файлов.
- `Штат` - текущая структура AI-команды.
- `Проекты` - цели, участники и заметки по проектам.
- `База знаний` - материалы, загруженные через Telegram-бота.
- `История` - последние запросы и ответы специалистов.
- `Правила` - глобальные правила работы AI-команды.
- `Настройки` - пути к базам и конфигам.

## Env

```bash
AI_ENGINEERING_WEB_HOST=127.0.0.1
AI_ENGINEERING_WEB_PORT=8080
AI_ENGINEERING_WEB_PASSWORD=...
AI_ENGINEERING_WEB_SESSION_SECRET=...
AI_ENGINEERING_WEB_DB=/var/lib/ai-team-of-engineers/control-center.db
AI_ENGINEERING_AGENTS_PATH=/opt/ai-team-of-engineers/configs/agents.json
AI_ENGINEERING_PROMPTS_PATH=/opt/ai-team-of-engineers/prompts
TELEGRAM_ACCESS_DB=/var/lib/ai-team-of-engineers/access.db
TELEGRAM_MEMORY_DB=/var/lib/ai-team-of-engineers/memory.db
TELEGRAM_MATERIALS_DB=/var/lib/ai-team-of-engineers/materials.db
```

## Запуск

```bash
python -m ai_engineering_platform web-control
```

На сервере веб-кабинет запускается systemd-сервисом:

```bash
systemctl status ai-engineering-web-control
```

## Безопасность MVP

При первом запуске создается пользователь `admin` с паролем из `AI_ENGINEERING_WEB_PASSWORD`.
Пароли хранятся в SQLite в виде PBKDF2-хеша, вход держится через подписанную cookie-сессию.

Роли веб-кабинета:

- `owner` - полный доступ;
- `admin` - управление агентами, правилами и пользователями;
- `member` - работа с проектами;
- `viewer` - просмотр.

Для production следующим шагом нужен HTTPS через Let's Encrypt.
