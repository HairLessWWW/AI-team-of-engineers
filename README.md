# AI Team of Engineers

Платформа AI-агентов для инженерии, робототехники и подготовки производственной площадки.

Цель проекта - создать цифровой контур, который помогает CTO и ведущим инженерам проектировать антропоморфных и других роботов, готовить производство в РФ, управлять инженерными рисками, документацией, испытаниями, сервисом и ростом команды.

AI-агенты в этом проекте не заменяют инженеров. Они дублируют часть аналитической, проверочной, документационной и организационной работы ведущих специалистов, оставляя финальные технические и safety-critical решения людям.

## Что будет строиться

- CTO Control Tower для управления инженерно-производственной зрелостью.
- Project Orchestrator для раздачи задач ролевым агентам.
- Ролевые агенты для электрики, механики, embedded, PLC, firmware, robotics software, производства, качества, сервиса и сертификации.
- Engineering Knowledge Base для проектных документов, BOM, схем, кода, протоколов испытаний и сервисных отчетов.
- Workflow для design review, pilot production readiness review, BOM risk review и documentation completeness review.

## Первый MVP

Первый MVP проверяет папку с инженерными артефактами и формирует первичный отчет готовности к пилотной сборке:

- технические риски;
- производственные риски;
- пробелы в документации;
- BOM-риски;
- вопросы к ответственным инженерам.

Запуск локально:

```powershell
$env:PYTHONPATH = "src"
python -m ai_engineering_platform review --project examples/demo_project --output outputs/demo-readiness-report.md
```

Режим с mock LLM, полезный для проверки агентного контура без API-ключа:

```powershell
$env:PYTHONPATH = "src"
python -m ai_engineering_platform review --project examples/demo_project --output outputs/demo-llm-report.md --mode mock-llm
```

Режим с OpenAI-compatible API:

```powershell
$env:PYTHONPATH = "src"
$env:OPENAI_API_KEY = "..."
$env:OPENAI_MODEL = "gpt-4.1-mini"
python -m ai_engineering_platform review --project examples/demo_project --output outputs/demo-llm-report.md --mode llm
```

## Структура репозитория

```text
.github/                 Шаблоны Issues и Pull Requests
configs/                 Реестр AI-агентов
docs/                    Концепция, MVP specification, backlog, roadmap
examples/demo_project/   Пример входных инженерных данных
prompts/                 Ролевые инструкции для LLM-агентов
src/                     Python MVP-скелет платформы
tests/                   Тесты базовой логики
```

## Главные документы

- [Концепция платформы](docs/platform-concept.md)
- [Карта AI-агентов](docs/agents.md)
- [MVP specification](docs/mvp-spec.md)
- [Product backlog](docs/backlog.md)
- [Agent prompting guide](docs/prompting.md)
- [Roadmap](docs/roadmap.md)

## Принципы

- Выводы агентов должны ссылаться на источники.
- Для критических решений нужен human approval.
- Платформа должна работать с реальными инженерными артефактами, а не быть только чатом.
- Каждый агент описывает будущую функцию отдела, а не только одного исполнителя.
- Проектирование должно быть связано с производством, сервисом и сертификацией.
