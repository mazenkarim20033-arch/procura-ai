"""Record the running API's read-only responses as static JSON for the public snapshot demo.

    cd backend && .venv/Scripts/python scripts/export_snapshot.py [--api http://localhost:8000] [--out ../frontend/public/demo-data]

Start the backend first (the data comes from whatever database it is connected to). Only GET endpoints are
called, so nothing is changed. File names mirror the API paths (`/requests/{id}/intake` becomes
`requests__{id}__intake.json`), which is the rule frontend/src/lib/snapshot.ts uses to read them back.
The health response is rewritten on purpose: the snapshot has no live model, no live database and cannot write.
"""
import argparse
import json
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path

import httpx

HEADERS = {"x-demo-role": "admin", "x-demo-user": "Snapshot exporter", "x-demo-authority": "chief financial officer"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--api", default="http://localhost:8000")
    ap.add_argument("--out", default=str(Path(__file__).resolve().parents[2] / "frontend" / "public" / "demo-data"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    client = httpx.Client(base_url=args.api, headers=HEADERS, timeout=180)
    written: dict[str, int] = {}

    def get(path: str, **params):
        r = client.get(path, params=params or None)
        r.raise_for_status()
        return r.json()

    def save(name: str, data) -> None:
        (out / f"{name}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        written[name] = (out / f"{name}.json").stat().st_size

    def fname(path: str) -> str:
        return path.lstrip("/").replace("/", "__")

    def record(path: str, **params) -> object:
        data = get(path, **params)
        save(fname(path), data)
        return data

    health = get("/health/ready")
    health.update({"read_only": True, "snapshot": True, "snapshot_at": datetime.now(UTC).isoformat()})
    health["checks"]["llm"] = {"provider": "mock", "mock": True}
    health["checks"]["database"] = {"ok": True}
    save("health", health)

    requests = get("/requests", limit=500)
    save("requests", requests)
    ids = [r["id"] for r in requests]

    def one_request(rid: str) -> list[str]:
        assessments = []
        for suffix in ("", "/intake", "/quote-comparison", "/history"):
            record(f"/requests/{rid}{suffix}")
        assessments = record(f"/requests/{rid}/assessments")
        for a in assessments:
            record(f"/assessments/{a['id']}")
        return [a["id"] for a in assessments]

    with ThreadPoolExecutor(4) as pool:
        for n, aids in enumerate(pool.map(one_request, ids), 1):
            print(f"request {n}/{len(ids)} ({len(aids)} assessments)", flush=True)

    save("review__queue", get("/review/queue", status="submitted,assessed,info_requested"))
    save("analytics__overview", get("/analytics/overview"))
    save("analytics__overview__exclude_mock", get("/analytics/overview", exclude_mock="true"))

    docs = get("/documents", limit=500)
    save("documents", docs)
    with ThreadPoolExecutor(4) as pool:
        list(pool.map(lambda d: record(f"/documents/{d['id']}"), docs))
    print(f"documents {len(docs)}", flush=True)

    vendors = record("/vendors")
    for v in vendors:
        record(f"/vendors/{v['id']}")
    policies = record("/policies")
    for p in policies:
        record(f"/policies/{p['id']}")
    record("/settings/approved-suppliers")

    entries, before = [], None
    while True:
        page = get("/audit", limit=200, **({"before_id": before} if before else {}))
        entries.extend(page["entries"])
        before = page["next_before_id"]
        if not before:
            break
    save("audit", {"entries": entries, "next_before_id": None})
    save("audit__verify", get("/audit/verify"))

    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=False,
                         cwd=Path(__file__).resolve().parent).stdout.strip()
    meta = {"generated_at": datetime.now(UTC).isoformat(), "git_sha": sha, "requests": len(ids), "documents": len(docs),
            "vendors": len(vendors), "policies": len(policies), "audit_entries": len(entries),
            "note": "Recorded GET responses from the Procura API over synthetic data. Contains no secrets."}
    save("meta", meta)
    total = sum(written.values())
    print(f"wrote {len(written)} files, {total / 1e6:.2f} MB to {out}")
    print(json.dumps(meta))


if __name__ == "__main__":
    try:
        main()
    except httpx.HTTPError as exc:
        sys.exit(f"export failed: {exc}")
