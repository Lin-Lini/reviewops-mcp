import math
import re
from typing import List, Tuple

_BASE64LIKE = re.compile(r"[A-Za-z0-9_\-\/\+=]{20,}")


def shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    probs = [float(s.count(c)) / len(s) for c in set(s)]
    return -sum(p * math.log(p, 2) for p in probs)


def detect_high_entropy_candidates(text: str, min_len: int = 20, threshold: float = 4.0) -> List[Tuple[int, int, str]]:
    """
    Ищем куски, похожие на токены: длинные base64-like + высокая энтропия.
    Возвращаем список (start, end, snippet).
    """
    results: List[Tuple[int, int, str]] = []
    for m in _BASE64LIKE.finditer(text):
        s, e = m.span()
        if e - s < min_len:
            continue
        chunk = text[s:e]
        if shannon_entropy(chunk) >= threshold:
            results.append((s, e, chunk[:80]))
    return results