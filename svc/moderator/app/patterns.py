import re

# ====== СЕКРЕТЫ / КЛЮЧИ / ТОКЕНЫ ======
SECRETS_PATTERNS = {
    # Приватные ключи
    "PRIVATE_KEY_BLOCK": re.compile(
        r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]+?-----END [A-Z ]*PRIVATE KEY-----",
        re.IGNORECASE
    ),
    # JWT (типичный base64url, часто начинается на eyJ{...}.{...}.{...})
    "JWT_TOKEN": re.compile(
        r"\beyJ[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\.[a-zA-Z0-9_\-]{10,}\b"
    ),
    # Telegram Bot Token
    "TELEGRAM_BOT_TOKEN": re.compile(
        r"\b\d{8,12}:[A-Za-z0-9_-]{35}\b"
    ),
    # AWS
    "AWS_ACCESS_KEY_ID": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "AWS_SECRET_ACCESS_KEY": re.compile(r"\b[A-Za-z0-9/+=]{40}\b"),
    # Google API
    "GOOGLE_API_KEY": re.compile(r"\bAIza[0-9A-Za-z\-_]{35}\b"),
    # Slack
    "SLACK_TOKEN": re.compile(r"\bxox[baprs]-\d+-\d+-[A-Za-z0-9]{24,}\b"),
    # Discord Webhook
    "DISCORD_WEBHOOK": re.compile(r"https://(ptb\.)?discord(app)?\.com/api/webhooks/\d+/[A-Za-z0-9\-_]+"),
    # Generic Bearer
    "AUTH_BEARER": re.compile(r"Authorization:\s*Bearer\s+[A-Za-z0-9\-\._~\+/=]{20,}", re.IGNORECASE),
    # .env ключи
    "ENV_LINE": re.compile(
        r"(?im)^(?P<key>(?:\w+)?(?:TOKEN|SECRET|PASSWORD|PASS|KEY|API_KEY|ACCESS_KEY|PRIVATE_KEY)[\w\-]*)\s*=\s*(?P<value>.+)$"
    ),
    # Yandex Cloud (очень общий вид, не строгий — специально)
    "YANDEX_KEYS": re.compile(r"\bYC[A-Z]{2}[A-Za-z0-9_\-]{12,}\b"),
}

# ====== ВХОД: ПАТТЕРНЫ ДЖЕЙЛБРЕЙКОВ / ИНЪЕКЦИЙ ======
INJECTION_PHRASES = [
    # EN
    r"ignore (all|any|previous) (instructions|rules)",
    r"disregard (your|the) system prompt",
    r"reveal (your|the) system prompt",
    r"print (your|the) system prompt",
    r"act as (DAN|developer mode)",
    r"bypass (safety|policy|guardrails)",
    r"you must do (anything|everything) i say",
    r"simulate a (linux|windows) terminal",
    r"pretend to be (root|an expert|a hacker)",
    r"do not follow (the|any) rules",
    r"ignore safety (checks|policies)",
    # RU
    r"(выдай|покажи|раскрой|выведи)\s+(свой|ваш|мой)?\s*(системн\w*)\s+(промпт|промт)\b",
    r"игнорируй (все|любые|предыдущие) (инструкции|правила)",
    r"наплюй на (правила|инструкции)",
    r"покажи (свой|твой|системный) промпт",
    r"раскрой системный промпт",
    r"включи (режим|мод) разработчика",
    r"обойти (правила|модерацию|защиту)",
    r"симулируй терминал",
    r"сделай вид, что ты (root|хакер|админ)",
    r"(выдай|покажи|раскрой|приведи) (свой|твой|системный) промпт",
    r"(выдай|покажи|раскрой|приведи) (свой|твой|системный) промт",
    r"(дай|покажи) (инструкции|правила) (системы|ассистента|модели)",

]

INJECTION_REGEXES = [re.compile(p, re.IGNORECASE) for p in INJECTION_PHRASES]

# ====== ВЫХОД: ПРИЗНАКИ УТЕЧЕК ======
OUTPUT_LEAK_PHRASES = [
    r"system prompt", r"системный промпт", r"системный промт",
    r"Here is my system prompt", r"Вот мой системный промпт", r"Вот мой системный промт",
    r"BEGIN PRIVATE KEY", r"END PRIVATE KEY",
]

OUTPUT_LEAK_REGEXES = [re.compile(p, re.IGNORECASE) for p in OUTPUT_LEAK_PHRASES]