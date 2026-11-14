"""Vendor identity resolution from uploaded documents only (no external registry is consulted).

Order of evidence: tax ID, then normalised name or alias, then fuzzy name similarity. A tax ID that
disagrees with an otherwise matching name is recorded as a conflict (a human should look), and a fuzzy
match is always marked `needs_review`. Two vendors with different tax IDs are never merged by name similarity.
"""
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher

from app.vendors.normalize import normalize_vendor_name

FUZZY_THRESHOLD = 0.92  # see evals/runners/vendor_matching.py and docs/BENCHMARKS.md


@dataclass
class Candidate:
    id: str
    canonical_name: str
    tax_id: str | None = None
    aliases: list[str] = field(default_factory=list)


@dataclass
class Profile:
    name: str
    tax_id: str | None = None


@dataclass
class MatchDecision:
    action: str  # match | new
    vendor_id: str | None = None
    reason: str = ""  # tax_id | name | alias | fuzzy | no_match
    score: float = 0.0
    needs_review: bool = False
    conflicts: list[dict] = field(default_factory=list)


def normalize_tax_id(value: str | None) -> str | None:
    if not value:
        return None
    cleaned = re.sub(r"[^A-Za-z0-9]", "", value).upper()
    return cleaned or None


def _tax_conflict(profile_tax: str | None, cand_tax: str | None) -> bool:
    return bool(profile_tax and cand_tax and profile_tax != cand_tax)


def resolve_vendor(profile: Profile, candidates: list[Candidate], *, fuzzy_threshold: float = FUZZY_THRESHOLD) -> MatchDecision:
    tax = normalize_tax_id(profile.tax_id)
    name = normalize_vendor_name(profile.name)

    if tax:
        for c in candidates:
            if normalize_tax_id(c.tax_id) == tax:
                return MatchDecision("match", c.id, "tax_id", 1.0)

    if name:
        for c in candidates:
            known = {normalize_vendor_name(c.canonical_name), *(normalize_vendor_name(a) for a in c.aliases)}
            if name in known:
                conflicts = []
                if _tax_conflict(tax, normalize_tax_id(c.tax_id)):
                    conflicts.append({"field": "tax_id", "existing": c.tax_id, "new": profile.tax_id})
                return MatchDecision("match", c.id, "name" if name == normalize_vendor_name(c.canonical_name) else "alias",
                                     1.0, needs_review=bool(conflicts), conflicts=conflicts)

        best, best_ratio = None, 0.0
        for c in candidates:
            if _tax_conflict(tax, normalize_tax_id(c.tax_id)):
                continue  # different registered entities, however similar the names look
            ratio = max(SequenceMatcher(None, name, normalize_vendor_name(n)).ratio()
                        for n in (c.canonical_name, *c.aliases))
            if ratio > best_ratio:
                best, best_ratio = c, ratio
        if best is not None and best_ratio >= fuzzy_threshold:
            return MatchDecision("match", best.id, "fuzzy", round(best_ratio, 4), needs_review=True)

    return MatchDecision("new", None, "no_match", 0.0)
