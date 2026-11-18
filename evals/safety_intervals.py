"""Confidence intervals for the safety counts recorded in evals/reports (no database, no model).

    python evals/safety_intervals.py [report.json ...]

Reads compliance reports and prints, per mode/configuration, the Wilson 95% interval for
  - false approval rate   (gold confirmed violation, status no_issues_found)
  - false clean rate      (any gold issue, status no_issues_found)
With counts this small the intervals are wide: "0 of 12" only rules out a rate above about 24%.
Writes evals/reports/safety_intervals_<date>_<sha>.json so the figures quoted in docs/BENCHMARKS.md are traceable.
"""
import json
import math
import subprocess
import sys
from datetime import date
from pathlib import Path

REPORTS = Path(__file__).resolve().parent / "reports"


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def counts(text: str) -> tuple[int, int]:
    k, n = text.split("/")
    return int(k), int(n)


def rows(path: Path) -> list[dict]:
    d = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for name, m in d.get("modes", {}).items():
        label = name
        llm = m.get("llm") or {}
        if llm.get("model"):
            label = f"{name}:{llm['model']}:prompt-v{llm.get('prompt_version')}"
        row = {"report": path.name, "config": label}
        k, n = counts(m["false_approval_rate"]["count"])
        row["false_approval"] = {"k": k, "n": n, "wilson95": [round(x, 3) for x in wilson(k, n)]}
        k, n = counts(m["false_clean_rate_any_issue"])
        row["false_clean_any_issue"] = {"k": k, "n": n, "wilson95": [round(x, 3) for x in wilson(k, n)]}
        out.append(row)
    return out


def main() -> None:
    paths = [Path(a) for a in sys.argv[1:]] or sorted(REPORTS.glob("compliance_*.json"))
    result = []
    for p in paths:
        try:
            result.extend(rows(p))
        except (KeyError, ValueError, json.JSONDecodeError) as exc:  # older report shapes
            print(f"skipped {p.name}: {exc}")
    for r in result:
        fa, fc = r["false_approval"], r["false_clean_any_issue"]
        print(f"{r['report']:60s} {r['config']:42s} false-approval {fa['k']}/{fa['n']} CI {fa['wilson95']}  "
              f"false-clean {fc['k']}/{fc['n']} CI {fc['wilson95']}")
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=REPORTS, check=False).stdout.strip()
    out = REPORTS / f"safety_intervals_{date.today().isoformat()}_{sha}.json"
    out.write_text(json.dumps({"git_sha": sha, "method": "Wilson score interval, 95%", "rows": result}, indent=2), encoding="utf-8")
    print("wrote", out)


if __name__ == "__main__":
    main()
