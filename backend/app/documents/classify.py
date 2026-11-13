"""Rule-based document classification (no LLM). Returns scores so callers can see why."""
import re
from dataclasses import dataclass

# (regex, weight). Title-line patterns dominate; keyword patterns break ties.
_RULES: dict[str, list[tuple[str, float]]] = {
    "quotation": [
        (r"(?im)^\s*(?:[\w-]+\s+){0,2}(?:quotation|price offer|price quote)\s*$", 10),
        (r"(?i)\bvalid (?:until|through)\b|\bexpires\b", 2),
        (r"(?i)\bquotation no\b|\boffer ref\b|\bquote no\b", 3),
        (r"(?i)\bunit price\b", 1),
    ],
    "invoice": [
        (r"(?im)^\s*(?:[\w-]+\s+){0,2}invoice\s*$", 10),
        (r"(?i)\bdue date\b", 2),
        (r"(?i)\btotal due\b|\bamount due\b", 2),
        (r"(?i)\binvoice no\b|\bpo reference\b", 3),
    ],
    "purchase_request": [
        (r"(?im)^\s*(?:[\w-]+\s+){0,2}purchase (?:request|requisition)\s*$", 10),
        (r"(?i)\brequester\b", 2),
        (r"(?i)\bjustification\b", 2),
        (r"(?i)\brequest no\b", 3),
    ],
    "contract": [
        (r"(?im)^\s*(?:[\w-]+\s+){0,3}(?:agreement|contract)\s*$", 10),
        (r"(?i)\bcontract no\b", 3),
        (r"(?i)\btermination\b|\beffective date\b", 1),
    ],
    "policy": [
        (r"(?im)^\s*(?:[\w&-]+\s+){0,3}policy\s*$", 10),
        (r"(?i)\bpolicy code\b", 6),
        (r"(?i)\bshall\b|\bmust\b", 0.5),
        (r"(?m)^\s*\d+\.\d+\s+\S", 1),
    ],
}

MIN_SCORE = 5.0
MIN_SHARE = 0.5


@dataclass
class Classification:
    doc_type: str
    confidence: float
    scores: dict[str, float]


def classify(text: str) -> Classification:
    head = text[:3000]
    scores = {t: 0.0 for t in _RULES}
    for doc_type, rules in _RULES.items():
        for pattern, weight in rules:
            hits = len(re.findall(pattern, head))
            if hits:
                scores[doc_type] += weight * min(hits, 3)
    total = sum(scores.values())
    best = max(scores, key=scores.get)
    if total == 0 or scores[best] < MIN_SCORE:
        return Classification("other", 0.0 if total == 0 else round(scores[best] / total, 3), scores)
    share = scores[best] / total
    if share < MIN_SHARE:
        return Classification("other", round(share, 3), scores)
    return Classification(best, round(share, 3), scores)
