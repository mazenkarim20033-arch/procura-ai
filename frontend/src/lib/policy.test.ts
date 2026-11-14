import { describe, expect, it } from "vitest";
import { canApprove, requiredApproval } from "./policy";

describe("approval level (mirrors PRC-001 2.1-2.4; the server stays the source of truth)", () => {
  it("follows the amount bands, inclusive at the upper edge", () => {
    const need = (a: string) => requiredApproval(a, "USD")?.authority;
    expect([need("500"), need("1000"), need("1000.01"), need("10000"), need("10000.01"), need("50000"), need("50000.01")]).toEqual([
      "department manager", "department manager", "procurement officer", "procurement officer", "finance director", "finance director", "chief financial officer",
    ]);
    expect(requiredApproval("12000", "USD")?.clause).toBe("PRC-001:2.3");
  });

  it("cannot determine a level for missing or non-USD amounts", () => {
    expect(requiredApproval(null, "USD")).toBeNull();
    expect(requiredApproval("12000", "EUR")).toBeNull();
    expect(requiredApproval("abc", "USD")).toBeNull();
  });

  it("lets only sufficient authority approve, and only the top authority approve undeterminable amounts", () => {
    expect(canApprove("procurement officer", "9000", "USD")).toBe(true);
    expect(canApprove("procurement officer", "12000", "USD")).toBe(false);
    expect(canApprove("finance director", "12000", "USD")).toBe(true);
    expect(canApprove(null, "800", "USD")).toBe(false);
    expect(canApprove("finance director", "12000", "EUR")).toBe(false);
    expect(canApprove("chief financial officer", "12000", "EUR")).toBe(true);
    expect(canApprove("chief financial officer", null, "USD")).toBe(true);
  });
});
