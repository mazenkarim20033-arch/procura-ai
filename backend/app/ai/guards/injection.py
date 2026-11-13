"""Heuristic detector for instruction-like text in untrusted inputs (justifications, item descriptions,
supplier documents). It cannot catch every phrasing, so it is one layer: flagged text is shown to the
human reviewer, and the LLM prompt, schema and evidence verifier limit what injected text can do."""
import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, str]] = [
    ("ignore_instructions", r"ignore\s+(?:all\s+|any\s+|the\s+|your\s+)?(?:previous|prior|above|earlier)\s+(?:instructions?|rules?|prompts?|messages?)"),
    ("disregard_policy", r"disregard\s+(?:the\s+|all\s+|any\s+)?(?:policy|policies|rules?|instructions?|guidelines?)"),
    ("force_outcome", r"(?:mark|set|treat|record|label|report)\s+(?:this|the|it)(?:\s+(?:request|purchase|order|assessment))?\s+(?:as\s+)?(?:approved|compliant|valid|low[- ]risk|clean)"),
    ("approve_command", r"\bapprove\s+(?:this|the)\s+(?:request|purchase|order)\b"),
    ("role_override", r"you\s+are\s+(?:now\s+)?(?:an?|the)\s+(?:assistant|ai|system|developer|administrator|admin)\b"),
    ("fake_role_tag", r"</?\s*(?:system|assistant|instructions?)\s*>|\[\s*(?:system|inst)\s*\]|\bsystem\s+prompt\b"),
    ("suppress_findings", r"do\s+not\s+(?:flag|report|mention|raise|list)\b"),
    ("override_policy", r"override\s+(?:the\s+)?(?:policy|policies|approval|compliance|checks?)"),
]
_COMPILED = [(pid, re.compile(rx, re.IGNORECASE)) for pid, rx in _PATTERNS]


@dataclass
class InjectionHit:
    source: str
    pattern_id: str
    snippet: str


def scan(sources: list[tuple[str, str | None]]) -> list[InjectionHit]:
    hits: list[InjectionHit] = []
    for source, text in sources:
        if not text:
            continue
        for pid, rx in _COMPILED:
            m = rx.search(text)
            if m:
                lo, hi = max(0, m.start() - 30), min(len(text), m.end() + 30)
                hits.append(InjectionHit(source, pid, text[lo:hi].strip()))
    return hits
