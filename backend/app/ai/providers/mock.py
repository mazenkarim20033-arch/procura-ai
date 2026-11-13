"""Deterministic MOCK provider for demo mode and tests. It is NOT an AI model: it applies a few keyword
heuristics to the same prompt payload a real model would see, so the pipeline, verifier, persistence
and UI can be exercised without credentials. Every explanation it writes starts with "[MOCK]", and
results carry is_mock=True end to end."""
import json
import re
import time

from app.ai.pipeline.schemas import ClauseFindings
from app.ai.providers.base import LLMError, LLMResult, T

MOCK_MODEL = "mock-keyword-rules-v1"
_VAGUE_MAX_WORDS = 7


def _block(user: str) -> tuple[list[dict], dict]:
    clauses = json.loads(re.search(r"POLICY CLAUSES:\n(.*?)\n\n<<<REQUEST DATA", user, re.DOTALL).group(1))
    request = json.loads(re.search(r"<<<REQUEST DATA[^\n]*>>>\n(.*?)\n<<<END REQUEST DATA>>>", user, re.DOTALL).group(1))
    return clauses, request


def _clause(clauses: list[dict], ref: str) -> dict | None:
    return next((c for c in clauses if c["clause_ref"] == ref), None)


def _quote(clause: dict) -> str:
    return clause["text"].split(".")[0][:200].strip() or clause["text"][:200]


class MockProvider:
    name = "mock"
    model = MOCK_MODEL
    is_mock = True

    def generate(self, *, system: str, user: str, schema: type[T], prompt_name: str, prompt_version: str):
        if prompt_name != "clause_reasoning" or schema is not ClauseFindings:
            raise LLMError(f"mock provider has no behaviour for prompt '{prompt_name}'")
        start = time.perf_counter()
        clauses, req = _block(user)
        text = " ".join([req.get("justification") or "", *[i.get("description") or "" for i in req.get("items", [])]]).lower()
        words = len((req.get("justification") or "").split())
        out: list[dict] = []

        def add(refs: list[str], title: str, explanation: str, category: str = "potential_violation") -> None:
            """Cite the first of `refs` that was actually shown (the model only knows what it was given)."""
            for ref in refs:
                c = _clause(clauses, ref)
                if c:
                    out.append({"title": title, "explanation": f"[MOCK] {explanation}", "clause_ref": ref,
                                "quote": _quote(c), "confidence": 0.5, "category": category})
                    return

        if re.search(r"non-?standard|custom|bespoke|special order|not in (the )?catalog", text):
            add(["PRC-006:2.2"], "Non-catalog item needs justification",
                "The request mentions a non-standard item, so the policy asks for a reasonable justification.")
        if 0 < words <= _VAGUE_MAX_WORDS:
            add(["PRC-006:2.2"], "Justification may be too brief",
                "The justification is very brief; a human should judge whether it is adequate.", "inconclusive")
        if re.search(r"emergency|urgent|immediately|asap", text):
            add(["PRC-006:3.2", "PRC-006:3.1", "PRC-006:3.3", "PRC-002:3.2"], "Possible emergency purchase",
                "The request describes urgency; the policy has special rules for emergency purchases.")
        if re.search(r"sole.?source|single.?source|only supplier|only vendor", text):
            add(["PRC-002:3.1"], "Single-source purchase",
                "The request describes a single source; a written sole-source justification is required.")
        if re.search(r"laptop|monitor|switch|server|docking|software|licen[cs]e", text):
            add(["PRC-004:1.1", "PRC-004:1.2", "PRC-004:1.3", "PRC-004:2.1"], "IT purchase needs IT review",
                "The items look like IT equipment or software, which the policy says needs IT or security review.")
        parsed = schema.model_validate({"findings": out})
        return LLMResult(parsed, self.name, self.model, None, None, int((time.perf_counter() - start) * 1000),
                         0, True, json.dumps({"findings": out}))
