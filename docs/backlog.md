# Product Backlog

Этот backlog описывает первые этапы разработки AI Team of Engineers. Он специально написан как набор будущих GitHub Issues, чтобы CTO, разработчик или AI-агент могли брать задачи по одной и доводить их до результата.

## Milestone 0. Project Foundation

Цель: превратить идею в управляемый репозиторий с понятной структурой, документацией и минимальным работающим CLI.

### M0-01. Описать продуктовую концепцию

Status: done

Acceptance criteria:

- В репозитории есть описание назначения платформы.
- Описаны ключевые пользователи.
- Описаны ограничения ответственности AI.
- Описана связь разработки, производства, сервиса и сертификации.

### M0-02. Создать карту AI-агентов

Status: done

Acceptance criteria:

- Описаны основные инженерные агенты.
- Для каждого агента указан фокус.
- Есть первичный JSON-реестр агентов.

### M0-03. Создать CLI для readiness review

Status: done

Acceptance criteria:

- CLI принимает папку проекта.
- CLI загружает текстовые инженерные артефакты.
- CLI формирует Markdown-отчет.
- Есть demo project и базовый тест.

## Milestone 1. LLM Agent MVP

Цель: заменить простую эвристику первым настоящим LLM-контуром, где агенты анализируют документы и формируют инженерные выводы с источниками.

### M1-01. Добавить абстракцию LLM-провайдера

Priority: high

Status: done

Description:

Создать интерфейс, через который платформа сможет обращаться к LLM без привязки бизнес-логики к конкретному провайдеру.

Acceptance criteria:

- Есть `LLMClient` interface/protocol.
- Есть mock-клиент для тестов.
- Есть OpenAI-compatible клиент, который читает настройки из env.
- Код CLI не зависит напрямую от конкретного SDK.

### M1-02. Добавить промпты для MVP-агентов

Priority: high

Status: done

Description:

Создать промпты для Systems, Electrical, Manufacturing и Certification/Documentation агентов.

Acceptance criteria:

- Промпты лежат в отдельной папке.
- Каждый промпт описывает роль, вход, формат ответа и ограничения.
- Каждый агент обязан отделять факты, риски, вопросы и рекомендации.
- Каждый агент обязан ссылаться на исходные документы.

### M1-03. Реализовать LLM-анализ артефактов

Priority: high

Description:

Позволить агентам анализировать содержимое проектных документов через LLM.

Acceptance criteria:

- CLI имеет режим `--mode heuristic|llm`.
- В LLM-режиме каждый агент получает релевантный контекст.
- Результат сохраняется в Markdown.
- При отсутствии API key CLI объясняет, как запустить heuristic mode.

### M1-04. Добавить структурированный формат finding

Priority: high

Description:

Перейти от свободного текста к структуре, пригодной для dashboard и issue creation.

Acceptance criteria:

- Finding содержит `title`, `severity`, `area`, `source`, `evidence`, `recommendation`, `owner_role`, `approval_required`.
- Есть валидация обязательных полей.
- Markdown-отчет строится из структурированных findings.

## Milestone 2. Engineering Knowledge Base

Цель: добавить поиск по проектным артефактам и выбор релевантного контекста для агентов.

### M2-01. Индексировать документы проекта

Priority: high

Description:

Создать простой локальный индекс документов для поиска по тексту.

Acceptance criteria:

- Индексируются `.md`, `.txt`, `.csv`, `.json`, `.yaml`, исходный код и PLC-тексты.
- Можно искать по ключевым словам.
- Результат содержит путь к файлу и фрагмент текста.

### M2-02. Добавить retrieval для агентов

Priority: high

Description:

Передавать агенту только релевантные документы и фрагменты, а не весь проект целиком.

Acceptance criteria:

- Каждый агент имеет список retrieval queries.
- Orchestrator собирает контекст для каждого агента.
- В отчете видно, какие файлы использовались.

### M2-03. Добавить manifest проекта

Priority: medium

Description:

Позволить проекту описывать состав артефактов, версию, подсистему и ответственных.

Acceptance criteria:

- Поддерживается `project.yaml`.
- Manifest содержит project name, subsystem, version, artifact types, owners.
- CLI использует manifest при наличии.

## Milestone 3. Production Readiness

Цель: превратить отчет в инструмент оценки готовности к пилотной сборке.

### M3-01. Добавить readiness score

Priority: medium

Description:

Сформировать прозрачную оценку готовности подсистемы к пилотной сборке.

Acceptance criteria:

- Score строится по техническим, производственным, документальным и BOM-критериям.
- Отчет объясняет, почему выставлена такая оценка.
- Наличие high severity blocker снижает readiness до blocked.

### M3-02. Добавить BOM risk analyzer

Priority: high

Description:

Анализировать BOM на риски поставок, second source и критичность компонентов.

Acceptance criteria:

- CLI читает CSV BOM.
- Выявляются строки с unknown lead time, no second source, critical part.
- Результат попадает в общий report.

### M3-03. Добавить documentation completeness checklist

Priority: high

Description:

Проверять наличие минимального комплекта документов для пилотной сборки.

Acceptance criteria:

- Настраиваемый checklist хранится в config.
- Отчет показывает missing documents.
- Для каждого missing document указано, почему он нужен.

## Milestone 4. Product Interface

Цель: сделать платформу удобной для CTO и лидов без работы в терминале.

### M4-00. Создать Telegram bot MVP

Priority: high

Status: done

Description:

Создать первый Telegram-интерфейс, через который CTO может обращаться к AI-сотрудникам и собирать короткие совещания агентов.

Acceptance criteria:

- Бот запускается через `TELEGRAM_BOT_TOKEN`.
- Есть команды `/start`, `/agents`, `/ask`, `/meeting`.
- Есть mock-режим без API-ключа.
- Есть LLM-режим через OpenAI-compatible client.
- Есть опциональный whitelist по Telegram user id.
- Токены не коммитятся в репозиторий.

### M4-00A. Улучшить Telegram bot UX

Priority: high

Status: done

Description:

Добавить операционные команды и удобные обращения к AI-сотрудникам.

Acceptance criteria:

- Есть команда `/whoami`.
- Есть команда `/status`.
- Есть русские alias для ключевых агентов.
- `/meeting` поддерживает выбор участников.
- Ошибка LLM `429 Too Many Requests` возвращается пользователю понятным сообщением.

### M4-01. Создать web dashboard prototype

Priority: medium

Description:

Сделать простой интерфейс для загрузки проекта и просмотра readiness report.

Acceptance criteria:

- Есть web-приложение.
- Можно выбрать/загрузить папку или zip проекта.
- Можно запустить review.
- Можно посмотреть findings, risks и next actions.

### M4-02. Добавить role-based views

Priority: medium

Description:

Показывать каждому lead только релевантные ему замечания и задачи.

Acceptance criteria:

- Findings фильтруются по owner_role.
- Есть общий CTO view.
- Есть отдельные views для Electrical, Manufacturing и Documentation.

## Milestone 5. GitHub Workflow

Цель: вести разработку платформы прозрачно через Issues, PR и автоматические проверки.

### M5-01. Добавить GitHub Actions CI

Priority: medium

Description:

Запускать тесты при каждом PR.

Acceptance criteria:

- Workflow запускает `python -m unittest discover -s tests`.
- CI проходит на main.
- README показывает статус CI.

### M5-02. Перенести backlog в GitHub Issues

Priority: medium

Description:

Создать Issues из этого backlog после подключения GitHub App или GitHub CLI.

Acceptance criteria:

- Каждый backlog item создан как Issue.
- Issues размечены labels: `mvp`, `docs`, `agent`, `backend`, `frontend`, `production`.
- Issues привязаны к milestones.

## Ближайшие 5 задач

1. M1-01. Добавить абстракцию LLM-провайдера.
2. M1-02. Добавить промпты для MVP-агентов.
3. M1-04. Добавить структурированный формат finding.
4. M2-01. Индексировать документы проекта.
5. M3-02. Добавить BOM risk analyzer.
