from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel

from .settings import get_settings
from .tool_client import ToolClient
from .llm_client import LLMClient
from .log_client import LogClient
from .security_client import SecurityClient
from .moderator_client import ModeratorClient
from .planner import infer_rubric, infer_region, pick_filters_with_llm, pick_compare_with_llm, norm
from .formatter import compact_context


class ChatIn(BaseModel):
    message: str
    mode: str | None = "auto"


class ChatOut(BaseModel):
    trace_id: str
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


def _compare_reasons(left: list[dict], right: list[dict]):
    lmap = {x.get("label"): x for x in left if isinstance(x, dict) and x.get("label")}
    rmap = {x.get("label"): x for x in right if isinstance(x, dict) and x.get("label")}
    common = []
    only_l = []
    only_r = []
    for k in lmap.keys():
        if k in rmap:
            common.append(k)
        else:
            only_l.append(k)
    for k in rmap.keys():
        if k not in lmap:
            only_r.append(k)
    return common, only_l, only_r


def _uniq_keep_order(xs: list[str]) -> list[str]:
    seen = set()
    out = []
    for x in xs:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def _should_llm_guess_filters(m: str) -> bool:
    keys = [
        "в ",
        "город",
        "область",
        "край",
        "республика",
        "округ",
        "район",
        "москва",
        "питер",
        "спб",
        "санкт",
        "кафе",
        "ресторан",
        "салон",
        "магазин",
        "гостиниц",
        "отель",
        "бар",
        "паб",
        "автосервис",
        "стоматолог",
        "клиника",
    ]
    return any(k in m for k in keys)


def _render_insights(ctx: dict) -> str:
    f = (ctx.get("filters") or {})
    rubric = f.get("rubric") or "—"
    a0 = f.get("a0")

    ins = (ctx.get("insights") or {})
    stats = (ins.get("stats") or {})
    total = (stats.get("total") or {})
    neg = (stats.get("negative") or {})

    reasons = ins.get("reasons") or []
    samples = ins.get("samples") or []

    place = f" в {a0}" if a0 else ""
    lines = []
    lines.append(f"1) Итог: Негатив по рубрике «{rubric}»{place}.")

    lines.append("")
    lines.append("2) Причины:")
    if not reasons:
        lines.append("- Недостаточно данных по фильтру (reasons пуст).")
    else:
        for r in reasons[:5]:
            label = (r.get("label") or "").strip()
            score = r.get("score")
            ev = ", ".join((r.get("evidence") or [])[:5])
            if label and score is not None and ev:
                lines.append(f"- {label} (score={score}; evidence: {ev})")
            elif label and score is not None:
                lines.append(f"- {label} (score={score})")
            elif label:
                lines.append(f"- {label}")

    quotes = []
    for s in samples:
        t = (s.get("text") or "").replace("\n", " ").strip()
        if t:
            quotes.append(t)

    for d in (ctx.get("drilldown") or []):
        for s in ((d.get("samples") or [])[:2]):
            t = (s.get("text") or "").replace("\n", " ").strip()
            if t:
                quotes.append(t)

    quotes = _uniq_keep_order(quotes)

    lines.append("")
    lines.append("3) Цитаты:")
    if not quotes:
        lines.append("- Недостаточно цитат.")
    else:
        for q in quotes[:3]:
            lines.append(f"- {q}")
        if len(quotes) < 3:
            lines.append("- Недостаточно цитат.")

    lines.append("")
    lines.append("4) Что улучшить:")
    if reasons:
        for r in reasons[:5]:
            label = (r.get("label") or "").strip()
            acts = _actions_for(label)
            lines.append(f"- {acts[0]} (связь: {label})")
    else:
        lines.append("- Сначала собери больше данных по фильтру (мало негативных отзывов).")

    lines.append("")
    lines.append("Сводка по данным:")
    lines.append(f"- Всего отзывов: {total.get('total_reviews')}")
    lines.append(f"- Негативных (1–2★): {neg.get('reviews')}")
    lines.append(f"- Средний рейтинг (все): {total.get('avg_rating_all')}")
    lines.append(f"- Средний рейтинг (негатив): {neg.get('avg_rating')}")
    lines.append(f"- Плохих отзывов (в total): {total.get('bad_reviews')}")

    return "\n".join(lines)

def _search_ctx(tool_res: object, max_items: int = 3, max_len: int = 260) -> str:
    if not isinstance(tool_res, list):
        return str(tool_res)[:1200]

    out = []
    for it in tool_res[:max_items]:
        if not isinstance(it, dict):
            continue
        sn = (it.get("snip") or "").replace("\\n", " ").replace("\n", " ").strip()
        # убираем html <b>…</b>, чтобы модель не “пугалась”
        sn = sn.replace("<b>", "").replace("</b>", "")
        if len(sn) > max_len:
            sn = sn[:max_len].rstrip() + "…"
        out.append(f"- {sn}")
    return "\n".join(out) if out else "—"

@asynccontextmanager
async def lifespan(app: FastAPI):
    s = get_settings()
    app.state.settings = s
    app.state.tools = ToolClient(s.mcp_url, s.data_api)
    app.state.llm = LLMClient(s.llm_chat_url, s.llm_model)
    app.state.logger = LogClient(s.log_url, enabled=s.log_enabled)
    app.state.security = SecurityClient(s.security_url)
    app.state.moderator = ModeratorClient(s.moderator_url, enabled=s.moderator_enabled)

    app.state.mcp_used_last = False
    app.state.mcp_ok_last = False
    app.state.mcp_last_ts = None

    async def call_tool(trace_id: str, name: str, args: dict):
        tools: ToolClient = app.state.tools
        t0 = time.time()
        used_mcp, res = await tools.call(name, args)
        dt = time.time() - t0

        app.state.mcp_used_last = bool(used_mcp) or bool(getattr(app.state, "mcp_used_last", False))
        app.state.mcp_ok_last = bool(tools.mcp_ok)
        app.state.mcp_last_ts = time.time()

        await app.state.logger.emit(
            trace_id,
            "orch",
            "tool_call",
            {"tool": name, "args": args, "mcp_used": used_mcp, "latency_s": dt},
        )
        return used_mcp, res

    app.state.call_tool = call_tool

    try:
        used1, rub = await app.state.call_tool("boot", "top_rubrics", {"n": 300})
        used2, regs = await app.state.call_tool("boot", "top_regions", {"n": 800})
        app.state.rubrics = [r["rubric"] for r in rub] if isinstance(rub, list) else []
        app.state.regions = [r["a0"] for r in regs if isinstance(r, dict) and r.get("a0")] if isinstance(regs, list) else []
        app.state.mcp_used_last = app.state.mcp_used_last or used1 or used2
    except Exception:
        app.state.rubrics = []
        app.state.regions = []

    yield


app = FastAPI(lifespan=lifespan, title="reviewops-orchestrator", version="0.5.0")


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


@app.post("/chat", response_model=ChatOut)
async def chat(inp: ChatIn, authorization: str | None = Header(default=None)):
    s = app.state.settings
    llm: LLMClient = app.state.llm
    call_tool = app.state.call_tool
    logger: LogClient = app.state.logger

    trace_id = uuid.uuid4().hex
    await logger.emit(trace_id, "orch", "request", {"mode": inp.mode, "message": inp.message})

    # auth
    if s.auth_enabled:
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1].strip()
        ok = await app.state.security.verify(token)
        if not ok:
            raise HTTPException(status_code=401, detail="invalid token")

    msg = (inp.message or "").strip()
    m = norm(msg)

    mode = (inp.mode or "auto").strip().lower()
    is_auto = mode == "auto"

    mod: ModeratorClient = app.state.moderator

    async def finalize_answer(answer: str, system_prompt: str | None) -> str:
        if not getattr(mod, "enabled", False):
            return answer

        mo = await mod.moderate("output", answer, system_prompt=system_prompt)
        act2 = (mo.get("action") or "allow")
        if act2 == "block":
            await logger.emit(trace_id, "orch", "moderation", {"phase": "output", "action": "block", "reasons": mo.get("reasons", [])})
            return "Ответ заблокирован модерацией."
        if act2 == "redact" and isinstance(mo.get("redacted_text"), str):
            await logger.emit(trace_id, "orch", "moderation", {"phase": "output", "action": "redact", "reasons": mo.get("reasons", [])})
            return mo["redacted_text"]

        await logger.emit(trace_id, "orch", "moderation", {"phase": "output", "action": "allow", "reasons": mo.get("reasons", [])})
        return answer

    # INPUT moderation before ANY routing/tool calls
    if getattr(mod, "enabled", False):
        mi = await mod.moderate("input", msg)
        act = (mi.get("action") or "allow")
        if act == "block":
            await logger.emit(trace_id, "orch", "moderation", {"phase": "input", "action": "block", "reasons": mi.get("reasons", [])})
            raise HTTPException(status_code=400, detail="blocked by moderator")
        if act == "redact" and isinstance(mi.get("redacted_text"), str):
            msg = mi["redacted_text"]
            m = norm(msg)
            await logger.emit(trace_id, "orch", "moderation", {"phase": "input", "action": "redact", "reasons": mi.get("reasons", [])})
        else:
            await logger.emit(trace_id, "orch", "moderation", {"phase": "input", "action": "allow", "reasons": mi.get("reasons", [])})

    def _cmp_docs_limit() -> int:
        # compare – самый дорогой путь (2x insights). режем max_docs.
        return min(int(getattr(s, "ins_max_docs", 3000)), 800)

    def _need_two_distinct_regions(a1: str | None, a2: str | None) -> bool:
        return (not a1) or (not a2) or (a1 == a2)

    # -----------------
    # STRICT MODES (mode != auto)
    # -----------------
    if not is_auto:
        if mode == "search":
            tool_used = "text_search"
            tool_args = {"qs": msg, "n": 20}
            used_mcp, tool_res = await call_tool(trace_id, tool_used, tool_args)

            ctx = {"result": tool_res}
            ctx_txt = _search_ctx(tool_res)

            sys = (
                "Ты помощник по поиску по отзывам.\n"
                "Отвечай только на русском.\n"
                "Используй только контекст ниже.\n"
                "Если в контексте есть прямые совпадения, укажи это.\n"
                "Формат:\n"
                "Ответ: <1-2 предложения>\n"
                "Релевантные фрагменты:\n"
                "1) ...\n2) ...\n3) ..."
            )
            user = f"Запрос: {msg}\n\nКонтекст (фрагменты):\n{ctx_txt}"

            t0 = time.time()
            answer = await llm.chat(
                [{"role": "system", "content": sys}, {"role": "user", "content": user}],
                max_tokens=350,
                temperature=0.1,
            )
            await logger.emit(trace_id, "orch", "llm_call", {"latency_s": time.time() - t0, "tokens_hint": len(user), "kind": "search"})

            answer = await finalize_answer(answer, sys)
            return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

        if mode == "compare":
            rubrics = getattr(app.state, "rubrics", [])
            regions = getattr(app.state, "regions", [])

            rb = infer_rubric(msg, rubrics)

            # deterministic region extraction
            mentioned = []
            ml = norm(msg)
            for r in regions:
                nr = norm(r)
                if nr and nr in ml:
                    mentioned.append(r)
            mentioned = list(dict.fromkeys(mentioned))

            a1 = mentioned[0] if len(mentioned) > 0 else None
            a2 = mentioned[1] if len(mentioned) > 1 else None

            # LLM resolver if missing/weak
            if _need_two_distinct_regions(a1, a2):
                rb2, x1, x2 = await pick_compare_with_llm(llm, msg, rubrics, regions)
                rb = rb or rb2
                a1 = a1 or x1
                a2 = a2 or x2

            # MUST block compare if still not 2 distinct regions
            if _need_two_distinct_regions(a1, a2):
                answer = "Для режима compare нужно указать ДВА РАЗНЫХ региона, например: «сравни кафе Москва vs Санкт-Петербург» (можно «Москва vs Питер»)."
                answer = await finalize_answer(answer, None)
                return ChatOut(trace_id=trace_id, answer=answer, tool_used="none", tool_args={}, context={"hint": "need_two_distinct_regions"}, mcp_used=False)

            tool_used = "compare_regions"
            tool_args = {"rubric": rb or (rubrics[0] if rubrics else "Кафе"), "a0_1": a1, "a0_2": a2}

            max_docs = _cmp_docs_limit()

            used1, ins1 = await call_tool(trace_id, "negative_insights", {"rubric": tool_args["rubric"], "a0": a1, "n_terms": s.ins_n_terms, "n_samples": 3, "max_docs": max_docs})
            used2, ins2 = await call_tool(trace_id, "negative_insights", {"rubric": tool_args["rubric"], "a0": a2, "n_terms": s.ins_n_terms, "n_samples": 3, "max_docs": max_docs})
            used_mcp = used1 or used2

            ins1 = ins1 if isinstance(ins1, dict) else {"result": ins1}
            ins2 = ins2 if isinstance(ins2, dict) else {"result": ins2}

            r1 = ins1.get("reasons") or []
            r2 = ins2.get("reasons") or []
            common, only_l, only_r = _compare_reasons(r1, r2)

            lines = []
            lines.append(f"Сравнение: {tool_args['rubric']} | {a1} vs {a2}")
            lines.append("")
            lines.append("Общее (пересечение причин):")
            for x in common:
                lines.append(f"- {x}")
            lines.append("")
            lines.append(f"Только {a1}:")
            for x in only_l:
                lines.append(f"- {x}")
            lines.append("")
            lines.append(f"Только {a2}:")
            for x in only_r:
                lines.append(f"- {x}")

            ctx = {"rubric": tool_args["rubric"], "left": {"a0": a1, "reasons": r1}, "right": {"a0": a2, "reasons": r2}}

            sys = (
            "Напиши ТОЛЬКО 2-3 предложения.\n"
            "Запрещено добавлять новые причины.\n"
            "Запрещено повторять списки.\n"
            "Укажи 1 ключевое отличие, опираясь только на секции 'Только ...' и 'Общее'.\n"
            "Отвечай на русском."
            )
            t0 = time.time()
            extra = await llm.chat(
                [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines[:30])[:1200]}],
                max_tokens=120,
                temperature=0.2,
            )
            await logger.emit(trace_id, "orch", "llm_call", {"latency_s": time.time() - t0, "kind": "compare_summary"})

            answer = "\n".join(lines) + "\n\nКоротко:\n" + extra
            answer = await finalize_answer(answer, sys)
            return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

        if mode == "leaders":
            rubrics = getattr(app.state, "rubrics", [])
            regions = getattr(app.state, "regions", [])

            rubric = infer_rubric(msg, rubrics)
            a0 = infer_region(msg, regions)

            if (rubric is None or a0 is None) and _should_llm_guess_filters(m):
                rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
                rubric = rubric or rb2
                a0 = a0 or a02

            is_worst = ("худш" in m) or ("антилидер" in m) or ("самые плох" in m) or ("низкий рейтинг" in m)
            is_best = ("луч" in m) and not is_worst

            if is_worst:
                tool_used = "leaders_worst"
            elif is_best:
                tool_used = "leaders_best"
            else:
                tool_used = "leaders_worst" if ("почему" in m or "разбери" in m) else "leaders_best"

            tool_args = {"rubric": rubric or (rubrics[0] if rubrics else "Кафе"), "min_reviews": s.leaders_min_reviews, "n": s.leaders_n}
            if a0:
                tool_args["a0"] = a0

            used_mcp, items = await call_tool(trace_id, tool_used, tool_args)

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
            place = f" | Регион: {a0}" if a0 else ""
            head = f"{title} {tool_args['rubric']}{place} (min_reviews={tool_args['min_reviews']})"
            lines = [head]
            for i, r in enumerate(rows, 1):
                extra = f" — bad_share={r.get('bad_share')}" if tool_used == "leaders_worst" else ""
                lines.append(f"{i}) {r.get('name_ru')} — {r.get('address')} — avg={r.get('avg_rating')} — reviews={r.get('reviews')}{extra}")

            answer = "\n".join(lines)

            # drilldown for "почему/разбери" ONLY in leaders_worst
            if tool_used == "leaders_worst" and rows and (("почему" in m) or ("разбери" in m) or ("объясн" in m)):
                topk = 3 if ("топ 3" in m or "top 3" in m or "первые 3" in m) else 1
                ctx["drilldown"] = []
                used_any = False
                for idx, row in enumerate(rows[:topk], 1):
                    ok, org_ins = await call_tool(
                        trace_id,
                        "org_negative_insights",
                        {"org_key": row["org_key"], "n_terms": 20, "n_samples": 3, "max_docs": 600},
                    )
                    used_any = used_any or ok
                    org_ins = org_ins if isinstance(org_ins, dict) else {"result": org_ins}
                    expl_ctx = {
                        "org": {"name_ru": row.get("name_ru"), "address": row.get("address")},
                        "stats": org_ins.get("stats"),
                        "reasons": org_ins.get("reasons") or [],
                        "samples": (org_ins.get("samples") or [])[:2],
                    }
                    ctx["drilldown"].append(expl_ctx)
                    answer += f"\n\n---\nПочему #{idx} внизу:\n{_drilldown_text(expl_ctx)}"
                used_mcp = used_mcp or used_any

            answer = await finalize_answer(answer, None)
            return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

        if mode == "insights":
            rubrics = getattr(app.state, "rubrics", [])
            regions = getattr(app.state, "regions", [])

            rubric = infer_rubric(msg, rubrics)
            a0 = infer_region(msg, regions)

            if (rubric is None or a0 is None) and _should_llm_guess_filters(m):
                rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
                rubric = rubric or rb2
                a0 = a0 or a02

            if rubric is None:
                rubric = rubrics[0] if rubrics else "Кафе"

            tool_used = "negative_insights"
            tool_args = {"rubric": rubric, "n_terms": s.ins_n_terms, "n_samples": s.ins_n_samples, "max_docs": s.ins_max_docs}
            if a0:
                tool_args["a0"] = a0
            else:
                tool_args["max_docs"] = min(tool_args["max_docs"], 800)

            used_mcp, tool_res = await call_tool(trace_id, tool_used, tool_args)
            ins = tool_res if isinstance(tool_res, dict) else {"result": tool_res}

            ctx = {"filters": {"rubric": tool_args["rubric"], "a0": tool_args.get("a0")}, "insights": compact_context(ins, max_samples=3, sample_len=220)}
            answer = _render_insights(ctx)
            answer = await finalize_answer(answer, None)
            return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

        answer = f"Неизвестный режим: {mode}. Доступно: auto|search|insights|leaders|compare."
        answer = await finalize_answer(answer, None)
        return ChatOut(trace_id=trace_id, answer=answer, tool_used="none", tool_args={}, context={}, mcp_used=False)

    # -----------------
    # AUTO MODE (HEURISTICS)
    # -----------------
    wants_search = ("найди" in m) or ("поиск" in m)
    wants_compare = ("сравн" in m) or (" vs " in f" {m} ")
    is_worst = ("худш" in m) or ("антилидер" in m) or ("самые плох" in m) or ("низкий рейтинг" in m)
    is_best = ("луч" in m) and not is_worst
    wants_leaders = is_worst or is_best or ("лидер" in m) or ("топ" in m and ("луч" in m or "худ" in m or "рейтинг" in m))
    wants_insights = ("негатив" in m) or ("жалоб" in m) or ("причин" in m) or ("почему" in m) or ("что улучш" in m) or ("разбери" in m)

    # priority: search -> compare -> leaders -> insights
    if wants_search:
        tool_used = "text_search"
        tool_args = {"qs": msg, "n": 20}
        used_mcp, tool_res = await call_tool(trace_id, tool_used, tool_args)

        ctx = {"result": tool_res}
        sys = "Ты помощник. По контексту выдай краткий ответ и дай 3 наиболее релевантных найденных фрагмента. Отвечай на русском."
        user = f"Запрос: {msg}\nКонтекст: {str(tool_res)[:1200]}"

        t0 = time.time()
        answer = await llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": user}],
            max_tokens=220,
            temperature=0.2,
        )
        await logger.emit(trace_id, "orch", "llm_call", {"latency_s": time.time() - t0, "tokens_hint": len(user), "kind": "search"})

        answer = await finalize_answer(answer, sys)
        return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    if wants_compare:
        rubrics = getattr(app.state, "rubrics", [])
        regions = getattr(app.state, "regions", [])

        rb = infer_rubric(msg, rubrics)

        mentioned = []
        ml = norm(msg)
        for r in regions:
            nr = norm(r)
            if nr and nr in ml:
                mentioned.append(r)
        mentioned = list(dict.fromkeys(mentioned))
        a1 = mentioned[0] if len(mentioned) > 0 else None
        a2 = mentioned[1] if len(mentioned) > 1 else None

        if _need_two_distinct_regions(a1, a2) and _should_llm_guess_filters(ml):
            rb2, x1, x2 = await pick_compare_with_llm(llm, msg, rubrics, regions)
            rb = rb or rb2
            a1 = a1 or x1
            a2 = a2 or x2

        if _need_two_distinct_regions(a1, a2):
            answer = "Для сравнения укажи два РАЗНЫХ региона, например: «сравни кафе Москва vs Санкт-Петербург»."
            answer = await finalize_answer(answer, None)
            return ChatOut(trace_id=trace_id, answer=answer, tool_used="none", tool_args={}, context={"hint": "need_two_distinct_regions"}, mcp_used=False)

        tool_used = "compare_regions"
        tool_args = {"rubric": rb or (rubrics[0] if rubrics else "Кафе"), "a0_1": a1, "a0_2": a2}

        max_docs = _cmp_docs_limit()

        used1, ins1 = await call_tool(trace_id, "negative_insights", {"rubric": tool_args["rubric"], "a0": a1, "n_terms": s.ins_n_terms, "n_samples": 3, "max_docs": max_docs})
        used2, ins2 = await call_tool(trace_id, "negative_insights", {"rubric": tool_args["rubric"], "a0": a2, "n_terms": s.ins_n_terms, "n_samples": 3, "max_docs": max_docs})
        used_mcp = used1 or used2

        ins1 = ins1 if isinstance(ins1, dict) else {"result": ins1}
        ins2 = ins2 if isinstance(ins2, dict) else {"result": ins2}

        r1 = ins1.get("reasons") or []
        r2 = ins2.get("reasons") or []
        common, only_l, only_r = _compare_reasons(r1, r2)

        lines = []
        lines.append(f"Сравнение: {tool_args['rubric']} | {a1} vs {a2}")
        lines.append("")
        lines.append("Общее (пересечение причин):")
        for x in common:
            lines.append(f"- {x}")
        lines.append("")
        lines.append(f"Только {a1}:")
        for x in only_l:
            lines.append(f"- {x}")
        lines.append("")
        lines.append(f"Только {a2}:")
        for x in only_r:
            lines.append(f"- {x}")

        ctx = {"rubric": tool_args["rubric"], "left": {"a0": a1, "reasons": r1}, "right": {"a0": a2, "reasons": r2}}

        sys = "Коротко (2-3 предложения) объясни различия. Не выдумывай факты, опирайся только на список причин. Отвечай на русском."
        t0 = time.time()
        extra = await llm.chat(
            [{"role": "system", "content": sys}, {"role": "user", "content": "\n".join(lines)[:1400]}],
            max_tokens=120,
            temperature=0.2,
        )
        await logger.emit(trace_id, "orch", "llm_call", {"latency_s": time.time() - t0, "kind": "compare_summary"})

        answer = "\n".join(lines) + "\n\nКоротко:\n" + extra
        answer = await finalize_answer(answer, sys)
        return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    if wants_leaders:
        rubrics = getattr(app.state, "rubrics", [])
        regions = getattr(app.state, "regions", [])

        rubric = infer_rubric(msg, rubrics)
        a0 = infer_region(msg, regions)

        if (rubric is None or a0 is None) and _should_llm_guess_filters(m):
            rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
            rubric = rubric or rb2
            a0 = a0 or a02

        tool_used = "leaders_worst" if is_worst or ("почему" in m) or ("разбери" in m) else "leaders_best"
        tool_args = {"rubric": rubric or (rubrics[0] if rubrics else "Кафе"), "min_reviews": s.leaders_min_reviews, "n": s.leaders_n}
        if a0:
            tool_args["a0"] = a0

        used_mcp, items = await call_tool(trace_id, tool_used, tool_args)

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
        place = f" | Регион: {a0}" if a0 else ""
        head = f"{title} {tool_args['rubric']}{place} (min_reviews={tool_args['min_reviews']})"
        lines = [head]
        for i, r in enumerate(rows, 1):
            extra = f" — bad_share={r.get('bad_share')}" if tool_used == "leaders_worst" else ""
            lines.append(f"{i}) {r.get('name_ru')} — {r.get('address')} — avg={r.get('avg_rating')} — reviews={r.get('reviews')}{extra}")

        answer = "\n".join(lines)

        if tool_used == "leaders_worst" and rows and (("почему" in m) or ("разбери" in m) or ("объясн" in m)):
            topk = 3 if ("топ 3" in m or "top 3" in m or "первые 3" in m) else 1
            ctx["drilldown"] = []
            used_any = False
            for idx, row in enumerate(rows[:topk], 1):
                ok, org_ins = await call_tool(trace_id, "org_negative_insights", {"org_key": row["org_key"], "n_terms": 20, "n_samples": 3, "max_docs": 600})
                used_any = used_any or ok
                org_ins = org_ins if isinstance(org_ins, dict) else {"result": org_ins}
                expl_ctx = {
                    "org": {"name_ru": row.get("name_ru"), "address": row.get("address")},
                    "stats": org_ins.get("stats"),
                    "reasons": org_ins.get("reasons") or [],
                    "samples": (org_ins.get("samples") or [])[:2],
                }
                ctx["drilldown"].append(expl_ctx)
                answer += f"\n\n---\nПочему #{idx} внизу:\n{_drilldown_text(expl_ctx)}"
            used_mcp = used_mcp or used_any

        answer = await finalize_answer(answer, None)
        return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    if wants_insights:
        rubrics = getattr(app.state, "rubrics", [])
        regions = getattr(app.state, "regions", [])

        rubric = infer_rubric(msg, rubrics)
        a0 = infer_region(msg, regions)

        if (rubric is None or a0 is None) and _should_llm_guess_filters(m):
            rb2, a02 = await pick_filters_with_llm(llm, msg, rubrics, regions)
            rubric = rubric or rb2
            a0 = a0 or a02

        if rubric is None:
            rubric = rubrics[0] if rubrics else "Кафе"

        tool_used = "negative_insights"
        tool_args = {"rubric": rubric, "n_terms": s.ins_n_terms, "n_samples": s.ins_n_samples, "max_docs": s.ins_max_docs}
        if a0:
            tool_args["a0"] = a0
        else:
            tool_args["max_docs"] = min(tool_args["max_docs"], 800)

        used_mcp, tool_res = await call_tool(trace_id, tool_used, tool_args)
        ins = tool_res if isinstance(tool_res, dict) else {"result": tool_res}

        ctx = {"filters": {"rubric": tool_args["rubric"], "a0": tool_args.get("a0")}, "insights": compact_context(ins, max_samples=3, sample_len=220)}
        answer = _render_insights(ctx)
        answer = await finalize_answer(answer, None)
        return ChatOut(trace_id=trace_id, answer=answer, tool_used=tool_used, tool_args=tool_args, context=ctx, mcp_used=used_mcp)

    used_mcp, tool_res = await call_tool(trace_id, "top_rubrics", {"n": 30})
    ans = await finalize_answer("Уточни запрос. Пока что могу показать топ рубрик.", None)
    return ChatOut(trace_id=trace_id, answer=ans, tool_used="top_rubrics", tool_args={"n": 30}, context={"result": tool_res}, mcp_used=used_mcp)