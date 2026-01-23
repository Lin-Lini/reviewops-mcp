import os
from dataclasses import dataclass

@dataclass(frozen=True)
class Settings:
    mcp_url: str
    data_api: str
    llm_chat_url: str
    llm_model: str
    ins_n_terms: int
    ins_n_samples: int
    ins_max_docs: int
    leaders_n: int
    leaders_min_reviews: int

def get_settings() -> Settings:
    return Settings(
        mcp_url=os.getenv("MCP_URL", "http://mcp:8787/mcp"),
        data_api=os.getenv("DATA_API", "http://api:8000"),
        llm_chat_url=os.getenv("LLM_CHAT_URL", "http://llm:8080/v1/chat/completions"),
        llm_model=os.getenv("LLM_MODEL", "qwen2.5-1.5b"),
        ins_n_terms=int(os.getenv("INS_N_TERMS", "20")),
        ins_n_samples=int(os.getenv("INS_N_SAMPLES", "5")),
        ins_max_docs=int(os.getenv("INS_MAX_DOCS", "3000")),
        leaders_n=int(os.getenv("LEADERS_N", "10")),
        leaders_min_reviews=int(os.getenv("LEADERS_MIN_REVIEWS", "20")),
    )
