# MVP Specification

## Цель MVP

Создать первый рабочий контур AI-assisted engineering review для робототехнической подсистемы.

MVP должен помогать CTO и ведущим инженерам быстро понять:

- какие инженерные риски есть в проекте;
- какие документы отсутствуют;
- какие производственные вопросы блокируют пилотную сборку;
- какие BOM-позиции требуют внимания;
- какие вопросы нужно вынести на технический совет.

## Пользовательский сценарий

1. Пользователь кладет документы подсистемы в папку проекта.
2. Пользователь запускает review.
3. Платформа загружает артефакты.
4. Orchestrator выбирает MVP-агентов.
5. Агенты анализируют документы.
6. Платформа формирует Markdown-отчет.
7. CTO использует отчет для design review или pilot readiness review.

## MVP-агенты

- Systems Engineering Agent.
- Electrical Lead Engineer Agent.
- Manufacturing Engineering Agent.
- Certification and Technical Documentation Agent.

## Входные данные

Минимальный набор:

- `requirements.md` или аналог ТЗ;
- `bom.csv`;
- электрические схемы или их текстовое описание;
- сборочные инструкции;
- test plan;
- risk assessment, если есть;
- документация по эксплуатации, если есть.

## Выходные данные

Основной результат: `readiness-report.md`.

Отчет должен содержать:

- executive summary;
- список агентов;
- findings по каждому агенту;
- severity;
- missing artifacts;
- source files;
- CTO questions;
- next actions.

## Режимы анализа

- `heuristic`: offline-режим без LLM, использует ключевые слова и наличие ожидаемых артефактов.
- `mock-llm`: детерминированный режим для тестирования агентного контура без API-ключей.
- `llm`: режим OpenAI-compatible API, использует `OPENAI_API_KEY`, `OPENAI_MODEL` и опционально `OPENAI_BASE_URL`.

## Классы severity

- `low`: замечание полезно, но не блокирует работу.
- `medium`: требуется внимание ответственного lead.
- `high`: может блокировать pilot readiness.
- `critical`: требует human review до продолжения работ.

## Принципы human approval

AI может:

- находить риски;
- задавать вопросы;
- предлагать исправления;
- готовить отчеты;
- группировать замечания.

AI не может:

- утверждать safety-critical решения;
- выпускать КД/ЭД;
- менять production BOM без человека;
- принимать решение о готовности к серии.

## Definition of Done для MVP

- CLI запускается локально.
- Есть demo project.
- Есть отчет по demo project.
- Есть тесты.
- Есть backlog.
- Есть понятный следующий шаг к LLM-интеграции.
