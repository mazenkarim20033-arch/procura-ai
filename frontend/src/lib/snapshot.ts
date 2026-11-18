/**
 * Snapshot mode (VITE_STATIC_DEMO=1): the public demo has no backend. Every GET is answered from JSON files recorded
 * from the real API by backend/scripts/export_snapshot.py, and every write is refused with an explanation.
 * Filters the API would apply (status, audit filters, paging) are applied here to the recorded lists. Anything that
 * needs live computation (date-range analytics, policy search, new assessments) says so instead of faking a result.
 */
import { ApiError } from "./errors";

export const STATIC_DEMO = import.meta.env.VITE_STATIC_DEMO === "1";

type Params = Record<string, string | number | boolean | undefined | null>;

const cache = new Map<string, Promise<unknown>>();

export function snapshotFile(path: string): string {
  return path.replace(/^\//, "").split("/").join("__");
}

async function load<T>(file: string): Promise<T> {
  const url = `${import.meta.env.BASE_URL}demo-data/${file}.json`;
  if (!cache.has(url)) {
    cache.set(url, fetch(url).then((res) => {
      if (!res.ok) throw new ApiError(404, "not_in_snapshot", "That page is not part of the recorded demo snapshot.");
      return res.json();
    }).catch((e) => {
      cache.delete(url);
      throw e instanceof ApiError ? e : new ApiError(0, "unreachable", "Could not load the demo snapshot. Check your connection and reload.");
    }));
  }
  return cache.get(url) as Promise<T>;
}

export function clearSnapshotCache(): void {
  cache.clear();
}

interface AuditPage { entries: { id: number; actor_type: string; action: string; entity_type: string }[]; next_before_id: number | null }

export async function snapshotGet<T>(path: string, params: Params = {}): Promise<T> {
  const p = (k: string) => (params[k] === undefined || params[k] === null || params[k] === "" ? undefined : String(params[k]));

  if (path === "/health/ready") return load<T>("health");
  if (path === "/requests") {
    const all = await load<{ status: string }[]>("requests");
    const status = p("status");
    return (status ? all.filter((r) => status.split(",").includes(r.status)) : all) as T;
  }
  if (path === "/review/queue") {
    const all = await load<{ status: string }[]>("review__queue");
    const wanted = (p("status") ?? "submitted,assessed").split(",");
    return all.filter((r) => wanted.includes(r.status)) as T;
  }
  if (path === "/analytics/overview") {
    if (p("since") || p("until")) {
      throw new ApiError(403, "snapshot_unavailable", "Date filters are computed live. This demo is a recorded snapshot, so only the full period is shown.");
    }
    return load<T>(params.exclude_mock ? "analytics__overview__exclude_mock" : "analytics__overview");
  }
  if (path === "/audit") {
    const all = await load<AuditPage>("audit");
    const eq: [keyof AuditPage["entries"][number], string | undefined][] = [["entity_type", p("entity_type")], ["action", p("action")], ["actor_type", p("actor_type")]];
    const before = Number(p("before_id") ?? Infinity);
    const limit = Number(p("limit") ?? 50);
    const rows = all.entries.filter((e) => e.id < before && eq.every(([k, v]) => !v || e[k] === v));
    const page = rows.slice(0, limit);
    return { entries: page, next_before_id: rows.length > limit ? page[page.length - 1].id : null } as T;
  }
  if (path === "/audit/verify") {
    const v = await load<Record<string, unknown>>("audit__verify");
    return { ...v, snapshot: true } as T;
  }
  return load<T>(snapshotFile(path));
}

export function snapshotWriteError(path: string): ApiError {
  const live = path.startsWith("/policies/search")
    ? "Live policy search needs the running backend, which this recorded demo does not have."
    : "This is a recorded snapshot of the demo, so nothing can be created, uploaded, assessed or decided here.";
  return new ApiError(403, "read_only_demo", `${live} Run Procura locally to use every feature (see the project README).`);
}
