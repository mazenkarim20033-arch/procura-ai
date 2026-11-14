import { afterEach, describe, expect, it, vi } from "vitest";
import { api, ApiError } from "./api";
import { setIdentity } from "./identity";

afterEach(() => vi.unstubAllGlobals());

const reply = (status: number, body: unknown) => new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });

describe("api client", () => {
  it("sends the demo identity as headers on every call", async () => {
    setIdentity({ role: "reviewer", user: "Dina Samir", authority: "finance director", label: "Finance director" });
    const fetchMock = vi.fn().mockResolvedValue(reply(200, { ok: true }));
    vi.stubGlobal("fetch", fetchMock);
    await api.get("/requests", { status: "assessed", limit: undefined });
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("/requests?status=assessed");
    expect(String(url)).not.toContain("limit");
    expect(init.headers).toMatchObject({ "x-demo-role": "reviewer", "x-demo-user": "Dina Samir", "x-demo-authority": "finance director" });
  });

  it("keeps the server's own explanation when a rule refuses something", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(reply(409, { title: "conflict", detail: "The request is already approved; decisions are final" })));
    const err = await api.post("/requests/1/decisions", {}).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 409, title: "conflict", detail: "The request is already approved; decisions are final" });
  });

  it("explains an unreachable API instead of failing silently", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));
    const err = (await api.get("/health/live").catch((e) => e)) as ApiError;
    expect(err).toMatchObject({ status: 0 });
    expect(err.detail).toMatch(/Is the backend running/);
  });
});
