import os
from typing import Any, Dict
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from .schemas import ModerateRequest, ModerateResult
from .checks import (
    scan_secrets, scan_injection, scan_output_leaks,
    check_system_prompt_similarity, redact_text
)

app = FastAPI(title="moderator", version="1.0.0")

# Настройки через ENV (тонкая подстройка)
OUTPUT_BLOCK_ON_SYS_PROMPT = os.getenv("MOD_BLOCK_ON_SYS_PROMPT", "1") == "1"
OUTPUT_REDACT_SECRETS = os.getenv("MOD_REDACT_SECRETS", "1") == "1"
INPUT_REDACT_ENV = os.getenv("MOD_INPUT_REDACT_ENV", "1") == "1"


@app.post("/moderate")
async def moderate(request: Request):
    """
    Универсальная точка. Поддерживает как новый, так и старый формат:
      Новый: { "phase": "input"|"output", "text": "...", "system_prompt": "..."? }
      Старый (совместимость): { "text": "..." } -> phase="input"
    """
    payload: Dict[str, Any] = await request.json()
    # Совместимость
    if "phase" not in payload and "text" in payload:
        payload = {"phase": "input", "text": payload["text"]}

    data = ModerateRequest(**payload)

    if data.phase == "input":
        return JSONResponse(moderate_input(data).dict())
    else:
        return JSONResponse(moderate_output(data).dict())


def moderate_input(data: ModerateRequest) -> ModerateResult:
    text = data.text or ""
    reasons = []
    matches = []

    # 1) Пользователь случайно прислал секреты/.env?
    sec = scan_secrets(text)
    if sec:
        matches.extend(sec)
        reasons.append("input:secrets_detected")

    # 2) Джейлбрейки/инъекции?
    inj = scan_injection(text)
    if inj:
        matches.extend(inj)
        reasons.append("input:prompt_injection")

    # Решение
    if sec and INPUT_REDACT_ENV:
        # Секреты редактируем, остальное — пропускаем с пометкой
        red = redact_text(text, sec)
        return ModerateResult(action="redact", reasons=reasons, matches=matches, redacted_text=red)

    if inj:
        # Вход с явной инъекцией — блокируем
        return ModerateResult(action="block", reasons=reasons, matches=matches)

    return ModerateResult(action="allow", reasons=reasons, matches=matches)


def moderate_output(data: ModerateRequest) -> ModerateResult:
    text = data.text or ""
    reasons = []
    matches = []

    # 1) Утечки секретов в ответе
    sec = scan_secrets(text)
    if sec:
        matches.extend(sec)
        reasons.append("output:secrets_detected")

    # 2) Фразы утечек
    leak_phr = scan_output_leaks(text)
    if leak_phr:
        matches.extend(leak_phr)
        reasons.append("output:leak_phrase")

    # 3) Похож ли ответ на системный промпт?
    if data.system_prompt:
        leak_sys = check_system_prompt_similarity(text, data.system_prompt)
        if leak_sys:
            matches.extend(leak_sys)
            reasons.append("output:system_prompt_similarity")

    # Решение
    if any(m.category == "system_prompt_leak" for m in matches) and OUTPUT_BLOCK_ON_SYS_PROMPT:
        # если похоже на системный промпт — лучше заблокировать
        return ModerateResult(action="block", reasons=reasons, matches=matches)

    if sec or leak_phr:
        if OUTPUT_REDACT_SECRETS:
            red = redact_text(text, matches)
            return ModerateResult(action="redact", reasons=reasons, matches=matches, redacted_text=red)
        else:
            return ModerateResult(action="block", reasons=reasons, matches=matches)

    return ModerateResult(action="allow", reasons=reasons, matches=matches)


@app.get("/health")
async def health():
    return {"ok": True}