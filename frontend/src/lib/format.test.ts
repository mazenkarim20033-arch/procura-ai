import { describe, expect, it } from "vitest";
import { ago, hours, label, money, ms, percent, plural } from "./format";

describe("format", () => {
  it("formats money with the currency and two decimals, and says so when nothing is stated", () => {
    expect(money("12000", "USD")).toBe("USD 12,000.00");
    expect(money(2885.756, "EGP")).toBe("EGP 2,885.76");
    expect(money(null, "USD")).toBe("Not stated");
    expect(money("abc")).toBe("abc");
  });

  it("turns machine values into plain words", () => {
    expect(label("confirmed_violation")).toBe("Confirmed violation");
    expect(label("approved_despite_ai_issues")).toBe("Approved despite AI issues");
    expect(label("some_new_status")).toBe("Some new status");
    expect(label(null)).toBe("n/a");
  });

  it("formats durations and percentages without false precision", () => {
    expect(hours(0.02)).toBe("1 min");
    expect(hours(3.456)).toBe("3.5 h");
    expect(hours(96)).toBe("4.0 days");
    expect(hours(null)).toBe("n/a");
    expect(ms(420)).toBe("420 ms");
    expect(ms(4402)).toBe("4.4 s");
    expect(percent(0.8333)).toBe("83%");
    expect(percent(null)).toBe("n/a");
  });

  it("describes elapsed time in words", () => {
    const iso = (secondsAgo: number) => new Date(Date.now() - secondsAgo * 1000).toISOString();
    expect(ago(iso(10))).toBe("just now");
    expect(ago(iso(5 * 60))).toBe("5 minutes ago");
    expect(ago(iso(3600))).toBe("1 hour ago");
    expect(ago(iso(3 * 86400))).toBe("3 days ago");
    expect(plural(1, "request")).toBe("1 request");
    expect(plural(2, "request")).toBe("2 requests");
  });
});
