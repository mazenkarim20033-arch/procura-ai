# Synthetic dataset

**Everything here is synthetic.** The company ("Northwind Industrial Co."), vendors, people, prices and policies are invented; every PDF carries a "SYNTHETIC DATA" footer. Nothing is connected to a real organisation.

Regenerate (seeded, deterministic; needs `reportlab`, installed by `pip install -e ".[dev]"`):

```bash
python data/synthetic/generate.py
```

Output in `out/` (68 PDFs, each with a ground-truth `.json`):

| Folder | Count | Notes |
|---|---|---|
| `policies/` | 6 | 45 numbered clauses. PRC-002 3.2 vs PRC-006 3.3 contradict each other on emergency purchases; PRC-006 2.2 is deliberately vague |
| `quotations/` | 32 | Two layouts (`QUOTATION` table style, `PRICE OFFER` one-line style), some vendor names written with different legal suffixes, 9 with injected flaws (arithmetic errors, missing validity date) |
| `purchase_requests/` | 12 | 2 missing the department, 1 with a wrong total |
| `invoices/` | 8 | 3 with injected arithmetic flaws |
| `contracts/` | 6 | simple "Label: value" layout |
| `other/` | 4 | memos/newsletters for classification negatives |

Documents are linked into 12 "deals" (`deal_id` in the truth files): one request, 2-3 competing quotations, and usually an invoice/contract reusing the same items and vendor.

## Known limits
- Layouts are simple and text-based (no scans, no multi-column pages, no Arabic). Extraction benchmarks on this set measure **in-distribution** performance only.
- 45 clauses and 68 documents is smaller than the planned evaluation set (see `docs/EVALUATION.md`); compliance-labelled request scenarios (compliant / violating / ambiguous) arrive with milestones 6-7.
