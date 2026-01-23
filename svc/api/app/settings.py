import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    db_dsn: str

def get_settings() -> Settings:
    dsn = os.environ.get("DB")
    if not dsn:
        raise RuntimeError("DB env var is required")
    return Settings(db_dsn=dsn)
