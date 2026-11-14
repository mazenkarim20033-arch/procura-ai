"""Structural guard for the product's central promise: the AI never approves or rejects anything.

Only the human-decision service may assign a final request status; the AI-facing code (providers, pipeline,
rules, assessment service) must not even reference those statuses or the string values.
"""
import re
from pathlib import Path

APP = Path(__file__).resolve().parents[2] / "app"
FINAL = re.compile(r"RequestStatus\.(approved|rejected)|status\s*=\s*['\"](approved|rejected)['\"]")
ALLOWED = {"services/decisions.py"}


def test_only_the_decision_service_assigns_final_statuses():
    offenders = []
    for path in APP.rglob("*.py"):
        rel = path.relative_to(APP).as_posix()
        if FINAL.search(path.read_text(encoding="utf-8")) and rel not in ALLOWED:
            offenders.append(rel)
    assert offenders == [], f"{offenders} reference a final request status; only services/decisions.py may"


def test_ai_packages_cannot_import_the_decision_service():
    for pkg in ("ai", "rules"):
        for path in (APP / pkg).rglob("*.py"):
            text = path.read_text(encoding="utf-8")
            assert "services.decisions" not in text and "services import decisions" not in text, path
    assessment = (APP / "services" / "assessment.py").read_text(encoding="utf-8")
    # The assessment service may only move a request to "assessed" (and only from "submitted").
    assert "RequestStatus.assessed" in assessment and not FINAL.search(assessment)
    assert "req.status = " in assessment and len(re.findall(r"\.status\s*=\s*E\.RequestStatus\.(\w+)", assessment)) == 1
