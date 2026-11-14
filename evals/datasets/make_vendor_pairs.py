"""Builds vendor_pairs.json: labelled pairs of vendor names (plus optional tax IDs) for the matcher.

Seeded and synthetic. Positives are the same fictional vendor written differently; negatives are different
vendors, including hand-written near-miss names. Labels hold by construction. Written before tuning.

    python evals/datasets/make_vendor_pairs.py
"""
import json
import random
import re
from pathlib import Path

SEED = 20260303
ROOT = Path(__file__).resolve().parents[2]
VENDORS = json.loads((ROOT / "data" / "synthetic" / "out" / "vendor_truth.json").read_text(encoding="utf-8"))["vendors"]

SUFFIX_SWAP = [(" Ltd.", " Limited"), (" Inc.", " Incorporated"), (" LLC", " L.L.C."), (" Co.", " Company")]
# near-miss names that are genuinely different companies (each gets its own tax ID in the with-tax-ID setting)
NEAR_MISS = [
    ("Nile Cloud Services", "Nile Cloud Solutions"), ("Summit Networks Inc.", "Summit Network Systems Inc."),
    ("Orion Tech Supplies Ltd.", "Orion Tech Supply Ltd."), ("Delta Office Furniture LLC", "Delta Office Fixtures LLC"),
    ("Apex Facilities Management", "Apex Facility Management"), ("BrightPath Consulting Group", "BrightPoint Consulting Group"),
    ("Lumen Lighting Solutions Ltd.", "Lumen Lighting Systems Ltd."), ("Vertex Industrial Tools LLC", "Vertex Industrial Tooling LLC"),
    ("Cairo Print & Packaging Co.", "Cairo Print & Paper Co."), ("Nile Cloud Services", "Nile Cloud Services Egypt"),
    ("Summit Networks Inc.", "Summit Networking Inc."), ("Apex Facilities Management", "Apex Fire Management"),
]


def variants(name: str, rng: random.Random) -> dict[str, str]:
    out = {"upper": name.upper(), "lower": name.lower()}
    for a, b in SUFFIX_SWAP:
        if name.endswith(a):
            out["suffix_swap"] = name[: -len(a)] + b
    stripped = re.sub(r"\s+(Ltd\.|Inc\.|LLC|Co\.|Limited)$", "", name)
    if stripped != name:
        out["no_suffix"] = stripped
    out["punct"] = name.replace("&", "and").replace(".", "").replace(",", "")
    i = rng.randrange(2, len(name) - 3)
    out["typo_delete"] = name[:i] + name[i + 1:]
    j = rng.randrange(2, len(name) - 4)
    out["typo_swap"] = name[:j] + name[j + 1] + name[j] + name[j + 2:]
    return out


def build() -> list[dict]:
    rng = random.Random(SEED)
    pairs: list[dict] = []

    def add(kind, label, a, b, tax_a=None, tax_b=None):
        pairs.append({"id": f"p{len(pairs) + 1:03d}", "kind": kind, "label": label,
                      "a": {"name": a, "tax_id": tax_a}, "b": {"name": b, "tax_id": tax_b}})

    names = list(VENDORS)
    for n in names:
        tax = VENDORS[n]["tax_id"]
        for kind, v in variants(n, rng).items():
            add(f"same:{kind}", 1, n, v, tax, tax)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            add("different:distinct", 0, a, b, VENDORS[a]["tax_id"], VENDORS[b]["tax_id"])
    for n, (a, b) in enumerate(NEAR_MISS):
        add("different:near_miss", 0, a, b, f"TX-{900 + n}-000-111", f"TX-{900 + n}-000-222")
    return pairs


if __name__ == "__main__":
    data = build()
    path = Path(__file__).parent / "vendor_pairs.json"
    path.write_text(json.dumps(data, indent=1), encoding="utf-8")
    kinds = {}
    for p in data:
        kinds[p["kind"]] = kinds.get(p["kind"], 0) + 1
    print(f"wrote {len(data)} pairs to {path}: {kinds}")
