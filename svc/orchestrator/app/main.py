from __future__ import annotations

import time
from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel

from .settings import get_settings
from .tool_client import ToolClient
from .llm_client import LLMClient
from .planner import infer_rubric, infer_region, pick_filters_with_llm, norm
from .formatter import compact_context, context_to_text


class ChatIn(BaseModel):
    message: str
    mode: str | None = "auto"  # auto | search | insights | leaders


class ChatOut(BaseModel):
    answer: str
    tool_used: str
    tool_args: dict
    context: dict
    mcp_used: bool


def _actions_for(label: str) -> list[str]:
    m = {
        "Ожидание и скорость": [
            "Снизить ожидание: пересмотреть загрузку кухни/персонала в пиковые часы, добавить человека на выдачу/зал.",
            "Дать честные сроки и контроль: таймер/статус заказа, уведомления, компенсация при >45 минут.",
        ],
        "Заказ и ошибки": [
            "Проверка заказа перед выдачей: чек-лист + подтверждение позиции клиенту.",
            "Убрать оплату без подтверждения готовности: либо предавторизация, либо понятная отмена/возврат.",
        ],
        "Еда/качество": [
            "Контроль качества блюд: температура/состав/подача, дегустация менеджером 1–2 раза в смену.",
            "Санитария: отдельный контроль волос/перчаток/поверхностей (по жалобам на «волос»).",
        ],
        "Обслуживание/персонал": [
            "Скрипты общения + контроль менеджера в зале, разбор конфликтов с персоналом.",
            "Обучение официантов: реакция на просьбы клиента, статус заказа каждые 10–15 минут.",
        ],
        "Цены/счёт": [
            "Прозрачность цены: предупреждать про доплаты до заказа, не «сюрпризить» чек.",
            "Если качество/сроки не соблюдены: скидка/компенсация по правилам.",
        ],
    }
    return m.get(
        label,
        [
            "Проверить процесс по этой причине и закрепить ответственное лицо.",
            "Ввести контроль и метрику, чтобы не повторялось.",
        ],
    )


def _score_aspects(top_terms: list[dict], top_bigrams: list[dict]) -> list[dict]:
    # вытаскиваем строки
    terms_words = [x.get("w") for x in top_terms if isinstance(x, dict) and x.get("w")]
    bigram_phr = [x.get("g") for x in top_bigrams if isinstance(x, dict) and x.get("g")]

    # фильтруем мусор
    stop_terms = {"очень", "просто", "только", "когда", "после", "больше", "место", "время", "итоге", "ничего"}
    stop_bg = {"потому что", "в данном", "все было", "в первый", "данном заведении", "при этом", "как будто"}

    terms_words = [t for t in terms_words if t not in stop_terms]
    bigram_phr = [g for g in bigram_phr if g not in stop_bg]

    def score(keys: list[str]) -> tuple[int, list[str]]:
        s = 0
        ev: list[str] = []
        for k in keys:
            for t in terms_words:
                if k in t:
                    s += 1
                    ev.append(t)
            for g in bigram_phr:
                if k in g:
                    s += 2
                    ev.append(g)
        # уникализируем, обрезаем
        uniq = []
        seen = set()
        for x in ev:
            if x not in seen:
                seen.add(x)
                uniq.append(x)
        return s, uniq[:6]

    aspects = [
        ("Ожидание и скорость", ["минут", "ждал", "ожидан", "час"]),
        ("Обслуживание/персонал", ["персонал", "официант", "сервис", "администратор", "отношен", "хам"]),
        ("Еда/качество", ["блюд", "пицц", "паста", "волос", "невкус", "вкус", "холод", "пресн", "порци"]),
        ("Заказ и ошибки", ["заказ", "принес", "оплат", "позици", "перепут"]),
        ("Цены/счёт", ["дорог", "рубл", "цена", "счет", "стоим"]),
    ]

    out = []
    for label, keys in aspects:
        sc, ev = score(keys)
        if sc:
            out.append({"label": label, "score": sc, "evidence": ev})
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:3]


def _drilldown_text(expl_ctx: dict) -> str:
    org = expl_ctx.get("org") or {}
    stats = expl_ctx.get("stats") or {}
    reasons = expl_ctx.get("reasons") or []
    samples = expl_ctx.get("samples") or []

    lines = []
    lines.append(f"{org.get('name_ru')} — {org.get('address')}")
    if stats:
        lines.append(f"Негативных отзывов (1–2★): {stats.get('reviews')} | avg: {stats.get('avg_rating')}")
    lines.append("")
    lines.append("Причины:")
    if not reasons:
        lines.append("- Недостаточно данных для выделения причин (пустые агрегаты).")
    else:
        for r in reasons[:3]:
            ev = ", ".join((r.get("evidence") or [])[:5])
            lines.append(f"- {r.get('label')} (evidence: {ev})")

    lines.append("")
    lines.append("Цитаты:")
    for i, s in enumerate(samples[:2], 1):
        t = (s.get("text") or "").replace("\n", " ").strip()
        lines.append(f"{i}) {t}")

    lines.append("")
    lines.append("Что улучшить:")
    for r in reasons[:3]:
        acts = _actions_for(r.get("label") or "")
        lines.append(f"- {acts[0]} (связь: {r.get('label')})")

    return "\n".join(lines)


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.settings = s
    app.state.tools = ToolClient(s.mcp_url, s.data_api)
    app.state.llm = LLMClient(s.llm_chat_url, s.llm_model)

    app.state.mcp_used_last = False
    app.state.mcp_ok_last = False
    app.state.mcp_last_ts = None

    async def call_tool(name: str, args: dict):
        tools: ToolClient = app.state.tools
        used_mcp, res = await tools.call(name, args)

        app.state.mcp_used_last = bool(used_mcp) or bool(getattr(app.state, "mcp_used_last", False))
        app.state.mcp_ok_last = bool(tools.mcp_ok)
        app.state.mcp_last_ts = time.time()

        return used_mcp, res

    app.state.call_tool = call_tool

    # warm caches
    used1, rub = await app.state.call_tool("top_rubrics", {"n": 300})
    used2, regs = await app.state.call_tool("top_regions", {"n": 800})

    app.state.rubrics = [r["rubric"] for r in rub] if isinstance(rub, list) else []
    app.state.regions = [r["a0"] for r in regs if isinstance(r, dict) and r.get("a0")] if isinstance(regs, list) else []
    app.state.mcp_used_last = app.state.mcp_used_last or used1 or used2

    yield


app = FastAPI(lifespan=lifespan, title="reviewops-orchestrator", version="0.2.3")


@app.get("/health")
async def health():
    return {
        "ok": True,
        "rubrics_n": len(getattr(app.state, "rubrics", [])),
        "regions_n": len(getattr(app.state, "regions", [])),
        "mcp_ok_last": bool(getattr(app.state, "mcp_ok_last", False)),
        "mcp_used_last": bool(getattr(app.state, "mcp_used_last", False)),
        "mcp_last_ts": getattr(app.state, "mcp_last_ts", None),
        "mcp_ok_raw": bool(getattr(app.state.tools, "mcp_ok", False)),
    }


@app.get("/debug/caches")
async def debug_caches():
    return {
        "rubrics": getattr(app.state, "rubrics", [])[:30],
        "regions": getattr(app.state, "regions", [])[:30],
        "mcp_ok_last": bool(getattr(app.state, "mcp_ok_last", False)),
        "mcp_used_last": bool(getattr(app.state, "mcp_used_last", False)),
        "mcp_last_ts": getattr(app.state, "mcp_last_ts", None),
        "mcp_ok_raw": bool(getattr(app.state.tools, "mcp_ok", False)),
    }


@app.post("/chat", response_model=ChatOut)
async def chat(inp: ChatIn):
    s = app.state.settings
    llm: LLMClient = app.state.llm
    call_tool = app.state.call_tool

    msg = inp.message.strip()
    m = norm(msg)

    # SEARCH
    if inp.mode == "search" or "найди" in m or "поиск" in m:
        tool_used = "text_search"
        tool_args = {"qs": msg, "n": 20}

        used_mcp, tool_res = await call_tool(tool_used, tool_args)

        ctx = {"result": tool_res}
        sys = "Ты помощник. По контексту выдай краткий ответ и дай 3 наиболее релевантных найденных фрагмента."
        user = f"Запрос: {msg}\nКонтекст: {str(tool_res)[:1200]}"

        answer = await llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            max_tokens=220,
            temperature=0.2,
        )
        return ChatOut(answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    # LEADERS
    is_worst = ("худш" in m) or ("антилидер" in m) or ("плох" in m)
    is_best = ("луч" in m) and not is_worst
    wants_leaders = (inp.mode == "leaders") or is_worst or is_best or ("топ" in m and ("луч" in m or "худ" in m or "рейтинг" in m))

    if wants_leaders:
        rubrics = getattr(app.state, "rubrics", [])
        regions = getattr(app.state, "regions", [])

        rubric = infer_rubric(msg, rubrics)
        a0 = infer_region(msg, regions)

        if rubric is None or a0 is None:
            rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
            rubric = rubric or rb2
            a0 = a0 or a02

        if (inp.mode == "leaders" and not is_worst and not is_best and "негатив" in m) or is_worst:
            tool_used = "leaders_worst"
        else:
            tool_used = "leaders_best"

        tool_args = {
            "rubric": rubric or "Кафе",
            "min_reviews": s.leaders_min_reviews,
            "n": s.leaders_n,
        }
        if a0:
            tool_args["a0"] = a0

        used_mcp, items = await call_tool(tool_used, tool_args)

        rows = []
        if isinstance(items, list):
            for x in items[: s.leaders_n]:
                if isinstance(x, dict):
                    row = {
                        "org_key": x.get("org_key"),
                        "name_ru": x.get("name_ru"),
                        "address": x.get("address"),
                        "reviews": int(x.get("reviews") or 0),
                        "avg_rating": round(float(x.get("avg_rating") or 0.0), 3),
                    }
                    if tool_used == "leaders_worst":
                        row["bad_share"] = round(float(x.get("bad_share") or 0.0), 3)
                    rows.append(row)

        ctx = {"filters": {"rubric": tool_args["rubric"], "a0": tool_args.get("a0")}, "items": rows}

        title = "Худшие" if tool_used == "leaders_worst" else "Лучшие"
        place = f" в {a0}" if a0 else ""
        head = f"{title} {tool_args['rubric']}{place} (min_reviews={tool_args['min_reviews']})"

        lines = [head]
        for i, r in enumerate(rows, 1):
            extra = f" — bad_share={r['bad_share']}" if tool_used == "leaders_worst" else ""
            lines.append(f"{i}) {r['name_ru']} — {r['address']} — avg={r['avg_rating']} — reviews={r['reviews']}{extra}")

        answer = "\n".join(lines)

        # drilldown: explain why #1 is bad (DETERMINISTIC)
        drill = ("почему" in m) or ("объясни" in m) or ("разбери" in m)
        if drill and rows and rows[0].get("org_key"):
            org_key = rows[0]["org_key"]

            used2, org_ins = await call_tool(
                "org_negative_insights",
                {"org_key": org_key, "n_terms": 20, "n_samples": 3, "max_docs": 800},
            )
            org_ins = org_ins if isinstance(org_ins, dict) else {"result": org_ins}

            top_terms = (org_ins.get("top_terms") or [])[:20]
            top_bigrams = (org_ins.get("top_bigrams") or [])[:20]
            samples = (org_ins.get("samples") or [])[:3]
            reasons = _score_aspects(top_terms, top_bigrams)

            expl_ctx = {
                "org": {"name_ru": rows[0].get("name_ru"), "address": rows[0].get("address")},
                "stats": org_ins.get("stats"),
                "top_terms": top_terms[:10],
                "top_bigrams": top_bigrams[:10],
                "samples": samples[:2],
                "reasons": reasons,
            }

            expl = _drilldown_text(expl_ctx)
            answer = answer + "\n\n---\nПочему №1 внизу:\n" + expl
            used_mcp = used_mcp or used2
            ctx["drilldown"] = expl_ctx

        return ChatOut(answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    # INSIGHTS
    if inp.mode == "insights" or ("негатив" in m or "жалоб" in m or "почему" in m or "причин" in m):
        rubrics = getattr(app.state, "rubrics", [])
        regions = getattr(app.state, "regions", [])

        rubric = infer_rubric(msg, rubrics)
        a0 = infer_region(msg, regions)

        if rubric is None or a0 is None:
            rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
            rubric = rubric or rb2
            a0 = a0 or a02

        tool_used = "negative_insights"
        tool_args = {
            "rubric": rubric or "Кафе",
            "n_terms": s.ins_n_terms,
            "n_samples": s.ins_n_samples,
            "max_docs": s.ins_max_docs,
        }
        if a0:
            tool_args["a0"] = a0

        used_mcp, tool_res = await call_tool(tool_used, tool_args)
        ins = tool_res if isinstance(tool_res, dict) else {"result": tool_res}

        ctx = compact_context(ins, max_samples=3, sample_len=220)
        ctx_text = context_to_text(ctx)

        sys = (
            "Ты аналитик отзывов. Используй только контекст.\n"
            "Запрещено придумывать факты.\n"
            "Причины: перечисли ВСЕ строки label из блока 'Причины (агрегаты)'. Если их меньше 5 — не выдумывай.\n"
            "Не объясняй причины своими словами.\n"
            "Цитаты: 3 штуки ТОЛЬКО из блока 'Цитаты'.\n"
            "Действия: 5 действий, каждое привяжи к одной причине (по смыслу), без выдуманных деталей.\n"
            "Формат строго:\n"
            "1) Итог: ...\n"
            "2) Причины:\n- ...\n"
            "3) Цитаты:\n- ...\n"
            "4) Что улучшить:\n- ..."
        )

        user = f"Запрос: {msg}\n\n{ctx_text}"
        answer = await llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            max_tokens=320,
            temperature=0.2,
        )

        return ChatOut(answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    # fallback
    used_mcp, tool_res = await call_tool("top_rubrics", {"n": 30})
    return ChatOut(
        answer="Уточни запрос. Пока что могу показать топ рубрик.",
        tool_used="top_rubrics",
        tool_args={"n": 30},
        context={"result": tool_res},
        mcp_used=used_mcp,
    )
