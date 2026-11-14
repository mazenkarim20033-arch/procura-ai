"""Architecture guard (docs/ARCHITECTURE.md): api -> services -> (rules | ai | retrieval | documents | vendors) -> db.
Lower layers never import upward."""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
IMPORT = re.compile(r"^\s*(?:from|import)\s+app\.(\w+)", re.MULTILINE)
LOWER = ("rules", "ai", "retrieval", "documents", "vendors", "schemas")
FORBIDDEN = {  # package -> packages it must not import
    **{pkg: {"api", "services"} for pkg in LOWER},
    "db": {"api", "services", "rules", "ai", "retrieval", "documents", "vendors"},
    "services": {"api"},
}


def test_no_layer_imports_upward():
    problems = []
    for pkg, banned in FORBIDDEN.items():
        for path in (APP / pkg).rglob("*.py"):
            for target in set(IMPORT.findall(path.read_text(encoding="utf-8"))):
                if target in banned:
                    problems.append(f"{path.relative_to(APP).as_posix()} imports app.{target}")
    assert problems == []
