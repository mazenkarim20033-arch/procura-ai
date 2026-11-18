import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "./errors";
import { clearSnapshotCache, snapshotFile, snapshotGet, snapshotWriteError } from "./snapshot";

const files: Record<string, unknown> = {
  requests: [{ id: "a", status: "assessed" }, { id: "b", status: "approved" }],
  review__queue: [{ id: "a", status: "assessed" }, { id: "c", status: "info_requested" }],
  audit: { entries: [3, 2, 1].map((id) => ({ id, actor_type: id === 2 ? "ai" : "user", action: "x", entity_type: "request" })), next_before_id: null },
  audit__verify: { ok: true, entries_checked: 3, first_bad_id: null, head_hash: "abc", verified_at: "2026-11-18T00:00:00Z" },
  analytics__overview: { basis: "full" },
  analytics__overview__exclude_mock: { basis: "no mock" },
  requests__a__intake: { issues: [] },
  health: { status: "ok", read_only: true, snapshot: true },
};

beforeEach(() => {
  clearSnapshotCache();
  vi.stubGlobal("fetch", vi.fn(async (url: string) => {
    const name = String(url).split("/demo-data/")[1].replace(/\.json$/, "");
    return name in files ? new Response(JSON.stringify(files[name])) : new Response("", { status: 404 });
  }));
});
afterEach(() => vi.unstubAllGlobals());

describe("snapshot mode", () => {
  it("maps API paths to recorded files", () => {
    expect(snapshotFile("/requests/abc/intake")).toBe("requests__abc__intake");
    expect(snapshotFile("/settings/approved-suppliers")).toBe("settings__approved-suppliers");
  });

  it("applies the status filters the API would apply", async () => {
    expect(await snapshotGet("/requests", { status: "approved" })).toEqual([{ id: "b", status: "approved" }]);
    expect(await snapshotGet("/review/queue", { status: "submitted,assessed" })).toEqual([{ id: "a", status: "assessed" }]);
    expect(await snapshotGet("/review/queue", { status: "info_requested" })).toEqual([{ id: "c", status: "info_requested" }]);
  });

  it("filters and pages the audit log newest first", async () => {
    const one = await snapshotGet<{ entries: { id: number }[]; next_before_id: number | null }>("/audit", { limit: 2 });
    expect(one.entries.map((e) => e.id)).toEqual([3, 2]);
    expect(one.next_before_id).toBe(2);
    const two = await snapshotGet<{ entries: { id: number }[]; next_before_id: number | null }>("/audit", { limit: 2, before_id: "2" });
    expect(two.entries.map((e) => e.id)).toEqual([1]);
    expect(two.next_before_id).toBeNull();
    const ai = await snapshotGet<{ entries: { id: number }[] }>("/audit", { actor_type: "ai" });
    expect(ai.entries.map((e) => e.id)).toEqual([2]);
  });

  it("serves the recorded health report", async () => {
    expect(await snapshotGet("/health/ready")).toMatchObject({ status: "ok", snapshot: true });
  });

  it("marks a replayed verification as a snapshot", async () => {
    expect(await snapshotGet("/audit/verify")).toMatchObject({ ok: true, entries_checked: 3, snapshot: true });
  });

  it("refuses what needs live computation instead of faking it", async () => {
    await expect(snapshotGet("/analytics/overview", { since: "2026-01-01" })).rejects.toMatchObject({ status: 403, title: "snapshot_unavailable" });
    expect(await snapshotGet("/analytics/overview", { exclude_mock: true })).toEqual({ basis: "no mock" });
    await expect(snapshotGet("/requests/zzz")).rejects.toMatchObject({ status: 404 });
  });

  it("explains every write as read-only, and policy search separately", () => {
    const w = snapshotWriteError("/requests/1/decisions");
    expect(w).toBeInstanceOf(ApiError);
    expect(w).toMatchObject({ status: 403, title: "read_only_demo" });
    expect(w.detail).toMatch(/recorded snapshot/);
    expect(snapshotWriteError("/policies/search").detail).toMatch(/policy search/);
  });
});
