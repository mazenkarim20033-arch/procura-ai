"""Builds duplicate_cases.json: labelled pairs of purchase requests for the duplicate detector.

Seeded and synthetic. Paraphrases are written by hand (the PARAPHRASES table), so they test robustness to
rewording I thought of, not to the full variety of real-world descriptions. Labels hold by construction:

  exact_dup       identical goods and quantities, same supplier (suffix spelling may differ)   -> duplicate
  near_dup        same goods and quantities, descriptions reworded, same supplier             -> duplicate
  same_supplier_other_items   same supplier, disjoint goods                                    -> not duplicate
  partial_overlap one shared item out of three, same supplier                                  -> not duplicate
  stale_same      same supplier and goods but more than 90 days apart                          -> not duplicate
  other_supplier  reworded same goods from a different supplier (informational, not scored)    -> not scored

    python evals/datasets/make_duplicate_cases.py
"""
import json
import random
from pathlib import Path

SEED = 20260202
PARAPHRASES = {
    "Laptop 14in business": ["14-inch business laptop", "Business notebook 14 inch", "14in laptop for business use"],
    "Monitor 27in": ["27-inch monitor", "27 inch display screen", "Monitor 27 inch"],
    "Docking station USB-C": ["USB-C dock", "USB-C docking adapter station", "Laptop docking station (USB-C)"],
    "Network switch 24-port": ["24-port network switch", "24 port ethernet switch", "Switch, 24 ports, network"],
    "Design software licence": ["Licence for design software", "Design suite software license", "Design software subscription licence"],
    "Ergonomic office chair": ["Ergonomic chair for office", "Office chair, ergonomic", "Ergonomic desk chair"],
    "Standing desk": ["Height-adjustable standing desk", "Sit-stand desk", "Desk, standing"],
    "Whiteboard 120x90": ["120x90 whiteboard", "White board 120 by 90", "Whiteboard (120x90 cm)"],
    "LED desk lamp": ["Desk lamp LED", "LED lamp for desk", "Desk LED light"],
    "Printed brochures (500)": ["500 printed brochures", "Brochure printing, 500 copies", "Print run of 500 brochures"],
    "Consulting day rate": ["Consultant daily rate", "Consulting, per day", "Day rate for consulting"],
    "Cloud hosting (monthly)": ["Monthly cloud hosting", "Cloud hosting per month", "Hosting in the cloud, monthly"],
    "Cleaning service (monthly)": ["Monthly cleaning service", "Office cleaning per month", "Cleaning services, monthly"],
    "Security audit (fixed)": ["Fixed-price security audit", "Security audit, fixed fee", "Fixed security audit"],
}
GROUPS = {
    "it": ["Laptop 14in business", "Monitor 27in", "Docking station USB-C", "Network switch 24-port", "Design software licence"],
    "office": ["Ergonomic office chair", "Standing desk", "Whiteboard 120x90", "LED desk lamp", "Printed brochures (500)"],
    "services": ["Consulting day rate", "Cloud hosting (monthly)", "Cleaning service (monthly)", "Security audit (fixed)"],
}
SUPPLIERS = {
    "it": ["Orion Tech Supplies Ltd.", "Summit Networks Inc.", "Vertex Industrial Tools LLC"],
    "office": ["Delta Office Furniture LLC", "Cairo Print & Packaging Co.", "Lumen Lighting Solutions Ltd."],
    "services": ["BrightPath Consulting Group", "Nile Cloud Services", "Apex Facilities Management"],
}
SUFFIX_VARIANT = [(" Ltd.", " Limited"), (" Inc.", " Incorporated"), (" LLC", " L.L.C.")]


def variant(name: str) -> str:
    for a, b in SUFFIX_VARIANT:
        if name.endswith(a):
            return name[: -len(a)].upper() + b.upper()
    return name


def build() -> list[dict]:
    rng = random.Random(SEED)
    cases: list[dict] = []

    def req(supplier, descs, qtys, day):
        return {"supplier_name": supplier, "day": day,
                "items": [{"description": d, "quantity": q} for d, q in zip(descs, qtys, strict=True)]}

    def add(kind, label, a, b):
        cases.append({"id": f"c{len(cases) + 1:03d}", "type": kind, "label": label, "a": a, "b": b})

    for _ in range(12):  # per-kind repetitions
        for kind in ("exact_dup", "near_dup", "same_supplier_other_items", "partial_overlap", "stale_same",
                     "other_supplier"):
            grp = rng.choice(list(GROUPS))
            catalog, supplier = GROUPS[grp], rng.choice(SUPPLIERS[grp])
            n = rng.choice([1, 2, 3]) if kind != "partial_overlap" else 3
            if kind == "partial_overlap" and len(catalog) < 5:
                continue
            base = rng.sample(catalog, n)
            qtys = [rng.choice([1, 2, 5, 10]) for _ in base]
            day = rng.randint(0, 200)
            a = req(supplier, base, qtys, day)
            if kind == "exact_dup":
                add(kind, 1, a, req(variant(supplier), base, qtys, day + rng.randint(1, 40)))
            elif kind == "near_dup":
                add(kind, 1, a, req(supplier, [rng.choice(PARAPHRASES[d]) for d in base], qtys, day + rng.randint(1, 60)))
            elif kind == "same_supplier_other_items":
                others = [d for d in catalog if d not in base]
                if len(others) < n:
                    continue
                add(kind, 0, a, req(supplier, rng.sample(others, n), [rng.choice([1, 2, 5, 10]) for _ in range(n)],
                                    day + rng.randint(1, 30)))
            elif kind == "partial_overlap":
                others = [d for d in catalog if d not in base]
                b_items = [base[0], *rng.sample(others, 2)]
                add(kind, 0, a, req(supplier, [rng.choice(PARAPHRASES[d]) for d in b_items], [1, 1, 1],
                                    day + rng.randint(1, 40)))
            elif kind == "stale_same":
                add(kind, 0, a, req(supplier, base, qtys, day + rng.randint(120, 300)))
            else:  # other_supplier
                alt = rng.choice([s for s in SUPPLIERS[grp] if s != supplier])
                add(kind, None, a, req(alt, [rng.choice(PARAPHRASES[d]) for d in base], qtys, day + rng.randint(1, 20)))
    return cases


if __name__ == "__main__":
    cases = build()
    path = Path(__file__).parent / "duplicate_cases.json"
    path.write_text(json.dumps(cases, indent=1), encoding="utf-8")
    by = {}
    for c in cases:
        by[c["type"]] = by.get(c["type"], 0) + 1
    print(f"wrote {len(cases)} cases to {path}: {by}")
