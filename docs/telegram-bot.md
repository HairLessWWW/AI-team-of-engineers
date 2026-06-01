# Telegram Bot MVP

Telegram-бот - первый легкий интерфейс к AI Team of Engineers.

Он позволяет CTO:

- смотреть список доступных AI-сотрудников;
- задавать вопрос одному AI-сотруднику;
- собирать короткое инженерное совещание нескольких агентов;
- пользоваться кнопками для частых действий;
- запускать mock-режим до подключения настоящего LLM.

## Создание Telegram-бота

1. Открой Telegram и напиши `@BotFather`.
2. Выполни `/newbot`.
3. Выбери имя и username.
4. Скопируй token.

Не коммить token в GitHub и не показывай его на скриншотах.

## Локальный запуск

```powershell
$env:TELEGRAM_BOT_TOKEN = "token-from-botfather"
$env:AI_ENGINEERING_BOT_MODE = "mock-llm"
$env:PYTHONPATH = "src"
python -m ai_engineering_platform telegram-bot
```

Перед запуском долгоживущего бота можно проверить подключение к Telegram:

```powershell
$env:PYTHONPATH = "src"
$env:TELEGRAM_BOT_TOKEN = "token-from-botfather"
python -m ai_engineering_platform telegram-check
```

Если команда уходит в timeout, машина не может достучаться до `api.telegram.org`. Проверь VPN, proxy, firewall, настройки хостинга или доступность Telegram из текущей сети.

## Ограничение доступа

Чтобы бот отвечал только тебе, используй `TELEGRAM_ALLOWED_USER_IDS`.

Свой user id можно узнать командой:

```text
/whoami
```

Затем на сервере:

```powershell
$env:TELEGRAM_ALLOWED_USER_IDS = "123456789"
```

Несколько пользователей можно указать через запятую:

```powershell
$env:TELEGRAM_ALLOWED_USER_IDS = "123456789,987654321"
```

## Команды

```text
/start
/whoami
/status
/agents
/ask <agent_id> <вопрос>
/meeting <тема>
/meeting <agent_id,agent_id> <тема>
```

## Кнопки

Бот показывает inline-кнопки для:

- списка AI-сотрудников;
- статуса;
- выбора агента;
- совещания;
- Telegram user id;
- возврата в меню.

Кнопки агентов пока не хранят черновик вопроса. Они показывают точную команду `/ask <agent_id> <вопрос>`, которую нужно отправить следующим сообщением.

Примеры:

```text
/ask electrical Что может заблокировать пилотную сборку?
/ask электрик Что блокирует пилотную сборку?
/ask manufacturing Что нужно подготовить перед пилотной партией?
/meeting Готовность руки антропоморфного робота к пилотной партии
/meeting systems,electrical,manufacturing Готовность руки к пилотной сборке
```

## Псевдонимы агентов

Поддерживаются псевдонимы:

- `электрик`, `электрика` -> `electrical`
- `производство`, `технолог` -> `manufacturing`
- `сертификация`, `документация` -> `certification_docs`
- `архитектор`, `системщик` -> `systems`

## Операционные команды

`/whoami` показывает Telegram user id для настройки `TELEGRAM_ALLOWED_USER_IDS`.

`/status` показывает:

- режим бота;
- количество загруженных агентов;
- открыт ли доступ или включен whitelist;
- режим Telegram-интерфейса.

## Режимы

Mock-режим полезен для проверки UX без расходов на LLM:

```powershell
$env:AI_ENGINEERING_BOT_MODE = "mock-llm"
```

LLM-режим использует OpenAI-compatible API client:

```powershell
$env:AI_ENGINEERING_BOT_MODE = "llm"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-4.1-mini"
```

## Текущие ограничения

- Бот использует long polling, а не webhooks.
- Сетевые timeout во время polling повторяются автоматически.
- Ошибка LLM-провайдера `429 Too Many Requests` показывается понятным сообщением.
- Inline-кнопки пока являются быстрыми переходами к командам; полноценная память многошаговой сессии еще не реализована.
- Project memory и загрузка файлов еще не реализованы.
- Совещание по умолчанию вызывает всех MVP-агентов, либо выбранных агентов, если они указаны.
- Human approval workflow еще не реализован.
