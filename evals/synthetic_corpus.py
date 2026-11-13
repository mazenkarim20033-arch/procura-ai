"""The synthetic policy clauses as in-memory Clause objects (used by tests and benchmarks)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "data" / "synthetic"))
sys.path.insert(0, str(ROOT / "backend"))

from policies import POLICIES

from app.ai.pipeline.context import Clause


def load_clauses(skip: set[str] | None = None) -> list[Clause]:
    out = []
    for p in POLICIES:
        for s_no, (_, texts) in enumerate(p["sections"], 1):
            for c_no, text in enumerate(texts, 1):
                ref = f"{p['code']}:{s_no}.{c_no}"
                if skip and ref in skip:
                    continue
                out.append(Clause(ref, p["code"], f"{s_no}.{c_no}", text, chunk_id=f"mem-{ref}"))
    return out
