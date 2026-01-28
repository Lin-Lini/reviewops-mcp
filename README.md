# ReviewOps MCP + Local LLM (MVP)

Микросервисное MVP: Postgres + API (данные/аналитика) + MCP tools + локальный LLM (llama.cpp/Qwen GGUF) + Orchestrator (LLM gateway).

## Сервисы
- **db**: PostgreSQL (schema + индексы в `db/init.sql`)
- **loader**: скачивает parquet с HuggingFace и заливает в db
- **api**: Data+Analytics API (FastAPI + psycopg pool)
- **mcp**: MCP server (FastMCP) экспортирует tools поверх `api`
- **llm**: llama.cpp server (OpenAI-compatible `/v1/chat/completions`)
- **orch**: orchestrator (вызывает tools через MCP, затем формирует ответ через LLM)
- **logsvc**: событийный лог (trace_id, события, payload)
- **security**: выдача/проверка JWT (опционально)
- **moderator**: модерация входа/выхода (опционально, по ENV `MOD_ENABLED=1`)

## Быстрый старт (Windows)
1) Положи GGUF модель:
   - `models/qwen2.5-1.5b/qwen2.5-1.5b-instruct-q4_k_m.gguf`

2) Подними базу и залей данные:
```bat
docker compose up -d db
docker compose run --rm loader
```

3) Подними API + MCP + LLM + Orchestrator:
```bat
docker compose up -d api mcp llm orch
```

## Проверка
- API docs: `http://localhost:8000/docs`
- Orchestrator health: `http://localhost:9000/health`
- Logs: `http://localhost:9100/events`
- Orchestrator chat:
```bat
curl http://localhost:9000/chat -H "Content-Type: application/json" -d "{\"message\":\"Разбери негатив по кафе в Москве: причины, примеры, что улучшить\",\"mode\":\"insights\"}"
```

Smoke-тест (после `docker compose up -d api mcp llm orch`):
```bat
python scripts/smoke.py
```

## Tools (MCP)
MCP endpoint: `http://localhost:8787/mcp`

Tools:
- `top_rubrics(n)`
- `top_regions(n)`
- `text_search(qs,n)`
- `negative_insights(rubric,a0,n_terms,n_samples,max_docs)`


## Конфиг (.env)

- MCP endpoint: `MCP_URL=http://mcp:8787/mcp`
- Для отладки можно включить строгий режим (если MCP недоступен, запрос упадёт, без тихого fallback): `MCP_STRICT=1`

## MCP endpoint

`/mcp` использует SSE. Если дернуть из curl без `Accept: text/event-stream`, получите `406 Not Acceptable` — это нормально.


## Производительность

Для быстрых инсайтов убедитесь, что создан индекс `rev_org_rating_idx` на таблице `rev`.
