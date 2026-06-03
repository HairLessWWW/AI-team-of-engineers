# Telegram Bot MVP

Telegram-бот - первый дружелюбный интерфейс к AI Team of Engineers.

## Основной сценарий

1. Пользователь нажимает `/start`.
2. Бот показывает главное меню.
3. Пользователь выбирает специалиста кнопкой.
4. Бот показывает краткую роль специалиста.
5. Пользователь нажимает `Начать чат`.
6. После этого можно писать обычным текстом, без команд.

Для совещания:

1. Нажать `Собрать совещание`.
2. Выбрать участников кнопками.
3. Нажать `Дальше: написать тему`.
4. Написать тему обычным сообщением.

При кликах по меню бот редактирует предыдущее сообщение, чтобы чат не разрастался от каждого выбора.

## Специалисты

- `systems` - Системный архитектор.
- `electrical` - Ведущий электрик.
- `manufacturing` - Технолог производства.
- `certification_docs` - Документация и сертификация.

## Псевдонимы

- `электрик`, `электрика` -> `electrical`
- `производство`, `технолог` -> `manufacturing`
- `сертификация`, `документация` -> `certification_docs`
- `архитектор`, `системщик` -> `systems`

## Команды

Команды остаются для быстрого доступа и администрирования:

```text
/start
/help
/whoami
/status
/agents
/ask <agent_id> <вопрос>
/meeting <тема>
/meeting <agent_id,agent_id> <тема>
```

Администрирование:

```text
/users
/allow <telegram_id> [owner|admin|member|viewer]
/deny <telegram_id>
/role <telegram_id> <owner|admin|member|viewer>
```

## База пользователей и роли

Для нескольких уровней доступа используется SQLite:

```bash
TELEGRAM_ACCESS_DB=/var/lib/ai-team-of-engineers/access.db
TELEGRAM_OWNER_IDS=123456789
```

Роли:

- `owner` - полный доступ и управление пользователями.
- `admin` - управление пользователями.
- `member` - обычное использование бота.
- `viewer` - зарезервирован для будущего read-only режима.

Если база не включена, используется fallback `TELEGRAM_ALLOWED_USER_IDS`.

## Режимы LLM

Mock:

```bash
AI_ENGINEERING_BOT_MODE=mock-llm
```

DeepSeek:

```bash
AI_ENGINEERING_BOT_MODE=deepseek
DEEPSEEK_API_KEY=...
DEEPSEEK_MODEL=deepseek-v4-flash
DEEPSEEK_BASE_URL=https://api.deepseek.com
```

OpenAI-compatible:

```bash
AI_ENGINEERING_BOT_MODE=llm
OPENAI_API_KEY=...
OPENAI_MODEL=gpt-4.1-mini
OPENAI_BASE_URL=https://api.openai.com/v1
```

## Текущие ограничения

- Сессии пользователя пока хранятся в памяти процесса и сбрасываются при restart сервиса.
- Загрузка файлов и project memory еще не реализованы.
- `viewer` пока технически имеет доступ как обычный пользователь; read-only поведение будет добавлено позже.
- Human approval workflow еще не реализован.
