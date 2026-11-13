"""Basic supplier-name normalisation and comparison. Deliberately simple (no external data source):
the vendor-intelligence milestone adds an alias table and fuzzy clustering on top of this."""
import hashlib
import re
import unicodedata
from decimal import Decimal
from difflib import SequenceMatcher

_LEGAL_SUFFIXES = {
    "ltd", "limited", "llc", "inc", "incorporated", "co", "company", "corp", "corporation", "gmbh",
    "plc", "llp", "sa", "ag",
}
SIMILAR_RATIO = 0.88


def normalize_vendor_name(name: str | None) -> str:
    if not name:
        return ""
    text = unicodedata.normalize("NFKC", name).casefold().replace("&", " and ")
    text = re.sub(r"[.,'\"()]", "", text)
    tokens = re.sub(r"[^\w\s]", " ", text).split()
    while len(tokens) > 1 and tokens[-1] in _LEGAL_SUFFIXES:
        tokens.pop()
    return " ".join(tokens)


def compare_vendor_names(a: str | None, b: str | None) -> str:
    """'same' | 'similar' (likely typo/variant, needs a human look) | 'different' | 'unknown'."""
    na, nb = normalize_vendor_name(a), normalize_vendor_name(b)
    if not na or not nb:
        return "unknown"
    if na == nb:
        return "same"
    return "similar" if SequenceMatcher(None, na, nb).ratio() >= SIMILAR_RATIO else "different"


def normalize_item_description(text: str) -> str:
    return " ".join(re.findall(r"[a-z0-9]+", text.casefold()))


def request_fingerprint(supplier_name: str | None, items: list[tuple[str, Decimal | None]]) -> str:
    """Stable hash of supplier + the multiset of (description, quantity). Equal fingerprints mean the
    same goods from the same supplier regardless of wording order, casing, or legal-suffix spelling."""
    parts = sorted(f"{normalize_item_description(d)}:{(q.normalize() if q is not None else '?')}" for d, q in items)
    blob = normalize_vendor_name(supplier_name) + "|" + "|".join(parts)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
