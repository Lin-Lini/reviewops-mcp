# ReviewOps MCP — платформа аналитики отзывов через MCP + LLM (self-hosted MVP)

**ReviewOps MCP** — микросервисная платформа для анализа текстовых отзывов об организациях. Проект помогает получать **структурированные причины негатива с подтверждением (цитатами)**, выполнять полнотекстовый поиск и формировать сравнительную аналитику по рубрикам и регионам. Инструменты доступны как через REST API, так и через **MCP (Model Context Protocol)** для интеграции с LLM-агентами.

---

## Возможности

### Инструменты (REST API + MCP)
- **Справочники**: топ рубрик и регионов для фильтрации.
- **Полнотекстовый поиск по отзывам**: русский `tsvector`, релевантные фрагменты.
- **Negative insights**: причины негатива по рубрике/региону + примеры цитат + рекомендации по улучшениям.
- **Leaders**: лидеры и антилидеры среди организаций по рубрике (и региону) с порогом по числу отзывов.
- **Org drilldown**: разбор негатива для конкретной организации по `org_key`.
- **Compare**: сравнение двух регионов по пересечению и различиям причин негатива.

### LLM-слой (локально или через прокси)
- **Локально**: `llama.cpp server` с GGUF-моделью (OpenAI-compatible `/v1/chat/completions`).
- **Удаленно**: LLM gateway проксирует запросы в OpenAI-compatible endpoint (например ProxyAPI).
- Orchestrator использует LLM **точечно** (summary/compare), а вычисление причин и выбор evidence выполняется детерминированно на базе данных (для снижения риска галлюцинаций).

### Инженерные характеристики
- **MCP-first**: инструменты доступны для MCP-клиентов/агентов.
- **Fallback**: Orchestrator вызывает инструменты через MCP и при необходимости переходит на прямой REST API.
- **Observability**: события/трассировка с `trace_id` в Postgres.
- **Security (опционально)**: выдача JWT и проверка bearer-токена.
- **Moderation (опционально)**: защита от prompt-injection и редактирование секретов.

---

## Архитектура

```
                ┌─────────────────────────────────────┐
Client / User → │ Orchestrator (FastAPI) :9000         │
                │  - routing (auto/search/...)         │
                │  - tool calls (MCP → fallback REST)  │
                │  - optional JWT auth                 │
                │  - optional moderation               │
                └───────────────┬─────────────────────┘
                                │
                                │ tool calls
                                ▼
                    ┌───────────────────────────┐
                    │ MCP server (FastMCP) :8787 │
                    │ tools → wraps Data API     │
                    └─────────────┬─────────────┘
                                  │
                                  ▼
                    ┌───────────────────────────┐
                    │ Data+Analytics API :8000   │
                    │  - search                  │
                    │  - leaders                 │
                    │  - insights                │
                    └─────────────┬─────────────┘
                                  │ SQL
                                  ▼
                    ┌───────────────────────────┐
                    │ Postgres 16 :5432          │
                    │  org / rev / log_event     │
                    └───────────────────────────┘

LLM side:
┌───────────────────────────┐        ┌───────────────────────────┐
│ LLM Gateway :8080          │  →    │ llama.cpp server :8081     │
│ /v1/chat/completions       │       │ (local GGUF)               │
│ backend=local|proxyapi     │       └───────────────────────────┘
└───────────────────────────┘

Optional:
- logsvc :9100  (event log API -> log_event)
- security :9200 (JWT mint/verify)
- moderator :9300 (input/output moderation)
- loader (one-shot) (HF parquet -> DB)
```

---

## Данные и схема

### Источник данных (по умолчанию)
Лоадер загружает parquet-файл из HuggingFace dataset и импортирует данные в Postgres.

По умолчанию (см. `.env` / `docker-compose.yml`):
- `HF_REPO=d0rj/geo-reviews-dataset-2023`
- `HF_FILE=data/train-00000-of-00001-49261e4e5a35a5a0.parquet`

### Таблицы
- `org`: организация (ключ, имя, адрес, регионы `a0/a1`, рубрики `rub[]`)
- `rev`: отзыв (id, org_key, rating, text, `tsvector` по русскому)
- `log_event`: события трассировки (trace_id, service, event, payload jsonb)

---

## Быстрый старт (Docker Compose)

### Требования
- Docker + Docker Compose
- Достаточно дискового пространства под модель GGUF и кэш датасета

### 1) Клонирование и env
```bash
git clone https://github.com/Lin-Lini/reviewops-mcp
cd reviewops-mcp
cp .env.example .env
```

### 2) Выбор LLM-режима

#### Вариант A: локальная модель (по умолчанию)
Разместите GGUF файл модели по пути:
```
models/qwen2.5-1.5b/qwen2.5-1.5b-instruct-q4_k_m.gguf
```

Проверьте (или оставьте) в `.env`:
```env
LLM_BACKEND=local
LLM_MODEL=qwen2.5-1.5b
```

#### Вариант B: удаленный LLM через прокси (gateway)
Укажите в `.env`:
```env
LLM_BACKEND=proxyapi
PROXYAPI_OPENAI_BASE=https://openai.api.proxyapi.ru/v1
PROXYAPI_KEY=***secret***
PROXYAPI_MODEL=gemini/gemini-2.5-flash-lite
```

### 3) Поднятие базы и загрузка данных
```bash
docker compose up -d db
docker compose run --rm loader
```

### 4) Запуск сервисов
Минимально необходимый набор:
```bash
docker compose up -d api mcp llm orch
```

Полный набор (включая logsvc, security, moderator):
```bash
docker compose up -d
```

---

## Проверка работоспособности

- API docs: http://localhost:8000/docs  
- Orchestrator health: http://localhost:9000/health  
- Logs: http://localhost:9100/events  
- LLM gateway health: http://localhost:8080/health  

---

## Использование

### Orchestrator (основная точка входа)
Endpoint:
- `POST http://localhost:9000/chat`

Тело:
```json
{
  "message": "Разбери негатив по кафе в Москве: причины, примеры, что улучшить",
  "mode": "auto"
}
```

`mode`:
- `auto` (по умолчанию)
- `search` — поиск/подбор релевантных фрагментов
- `insights` — причины негатива + цитаты + рекомендации
- `leaders` — лидеры/антилидеры
- `compare` — сравнение двух регионов

Пример (insights):
```bash
curl -s http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"негатив по ресторанам в Санкт-Петербурге: причины и цитаты","mode":"insights"}'
```

Пример (leaders):
```bash
curl -s http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"худшие кафе в Москве","mode":"leaders"}'
```

Пример (compare):
```bash
curl -s http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -d '{"message":"сравни кафе Москва vs Санкт-Петербург","mode":"compare"}'
```

---

## MCP Tools

MCP endpoint:
- `http://localhost:8787/mcp`

Доступные tools:
- `top_rubrics(n=50)`
- `top_regions(n=50)`
- `text_search(qs, n=20)`
- `negative_insights(rubric, a0=None, n_terms=20, n_samples=5, max_docs=3000)`
- `leaders_worst(rubric, a0=None, min_reviews=20, n=10)`
- `leaders_best(rubric, a0=None, min_reviews=20, n=10)`
- `org_negative_insights(org_key, n_terms=20, n_samples=5, max_docs=3000)`

> Примечание: транспорт MCP использует SSE. Для корректной работы MCP-клиента требуется заголовок `Accept: text/event-stream`.

---

## REST API (краткая карта)

Base:
- `http://localhost:8000`

Методы:
- `GET /health`
- `GET /rubrics/top?n=50`
- `GET /regions/top?n=50`
- `GET /search/text?qs=...&n=20`
- `GET /leaders/worst?rubric=...&a0=...&min_reviews=20&n=20`
- `GET /leaders/best?rubric=...&a0=...&min_reviews=20&n=20`
- `GET /insights/negative?rubric=...&a0=...&n_terms=30&n_samples=10&max_docs=5000`
- `GET /org/search?qs=...&n=20`
- `GET /org/{org_key}`
- `GET /org/{org_key}/reviews?rmin=0&rmax=5&n=50`
- `GET /org/{org_key}/insights/negative?n_terms=20&n_samples=5&max_docs=3000`

---

## Конфигурация (ENV)

### MCP + API
- `MCP_URL=http://mcp:8787/mcp`
- `DATA_API=http://api:8000`
- `MCP_STRICT=1` — при недоступности MCP отключает fallback на REST (удобно для отладки).

### Параметры аналитики
- `INS_N_TERMS=20`
- `INS_N_SAMPLES=5`
- `INS_MAX_DOCS=3000`
- `LEADERS_N=10`
- `LEADERS_MIN_REVIEWS=20`

### LLM gateway
- `LLM_BACKEND=local|proxyapi`
- `LLM_MODEL=qwen2.5-1.5b`
- `LLM_TIMEOUT_S=120`
- `LOCAL_LLM_CHAT_URL=http://llm_local:8080/v1/chat/completions`

### Observability
- `LOG_ENABLED=1`
- `LOG_URL=http://logsvc:9100`

### Moderator
- `MOD_ENABLED=1`
- `MOD_URL=http://moderator:9300`
- `MOD_SEMANTIC_INJECTION=1`
- `MOD_SEMANTIC_THRESHOLD=0.78`
- `MOD_BLOCK_ON_SYS_PROMPT=1`
- `MOD_REDACT_SECRETS=1`

### Security
- `AUTH_ENABLED=0|1`
- `SECURITY_URL=http://security:9200`
- `ROOT_API_KEY=...`
- `JWT_SECRET=...`

---

## Auth (опционально)

Если включено:
```env
AUTH_ENABLED=1
```
то Orchestrator ожидает заголовок:
```
Authorization: Bearer <token>
```

### Получение токена
1) Укажите параметры в `.env`:
```env
ROOT_API_KEY=change-me
JWT_SECRET=dev-secret
```

2) Запросите токен:
```bash
curl -s http://localhost:9200/token -H "X-API-Key: change-me"
```

3) Используйте токен:
```bash
curl -s http://localhost:9000/chat \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <token>" \
  -d '{"message":"найди отзывы про парковку","mode":"search"}'
```

---

## Troubleshooting

**LLM не стартует в локальном режиме**
- Проверьте наличие файла модели по пути `models/qwen2.5-1.5b/...gguf`.
- Проверьте переменные окружения `LLM_BACKEND=local` и `LOCAL_LLM_CHAT_URL`.

**/mcp возвращает 406**
- Используйте MCP-клиент с `Accept: text/event-stream` (SSE).

**Insights/compare работают медленно**
- Убедитесь, что загрузчик выполнил `ANALYZE` (включено по умолчанию в init/loader).
- Проверьте наличие индексов (см. `db/init.sql`).

**/chat возвращает 401**
- Включен `AUTH_ENABLED=1`, но запрос отправлен без токена. Либо выключите auth, либо получите JWT через `security`.

---

## Resume highlights

- Микросервисная архитектура (FastAPI + Postgres) с Docker Compose окружением
- MCP-интеграция: инструменты аналитики доступны LLM-агентам через Model Context Protocol
- LLM как заменяемый backend: локальная GGUF модель через `llama.cpp` или внешний OpenAI-compatible endpoint
- Детерминированная аналитика и evidence из БД, LLM используется точечно для summary
- Опциональные подсистемы: auth (JWT), moderation, event logging / tracing

---

## License
Лицензия MIT
