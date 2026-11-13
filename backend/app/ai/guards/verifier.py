"""Evidence verifier: an LLM finding survives only if it cites a clause that was actually provided, quotes
that clause verbatim, and mentions no number absent from the request data or the cited clause."""
import re
from dataclasses import dataclass

from app.ai.pipeline.schemas import LLMFinding

_NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[\"'“”‘’]", "", text)).strip().casefold().rstrip(".")


def numbers(text: str) -> set[str]:
    out = set()
    for raw in _NUM.findall(text):
        n = raw.replace(",", "").rstrip(".")
        out.add(n.rstrip("0").rstrip(".") if "." in n else n)
    return out


@dataclass
class Rejected:
    finding: LLMFinding
    reason: str  # unknown_clause | quote_not_in_clause | unsupported_number


def verify(
    findings: list[LLMFinding], clauses: dict[str, str], request_text: str,
) -> tuple[list[LLMFinding], list[Rejected]]:
    ok: list[LLMFinding] = []
    bad: list[Rejected] = []
    request_numbers = numbers(request_text)
    for f in findings:
        clause_text = clauses.get(f.clause_ref)
        if clause_text is None:
            bad.append(Rejected(f, "unknown_clause"))
            continue
        if normalize(f.quote) not in normalize(clause_text):
            bad.append(Rejected(f, "quote_not_in_clause"))
            continue
        allowed = request_numbers | numbers(clause_text) | numbers(f.clause_ref)
        if not numbers(f.title + " " + f.explanation) <= allowed:
            bad.append(Rejected(f, "unsupported_number"))
            continue
        ok.append(f)
    return ok, bad
