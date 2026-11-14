/** Mirrors PRC-001 clauses 2.1-2.4 for display only. The server enforces the real rule and is the source of truth. */
import { AUTHORITIES } from "./identity";

const BANDS: { upTo: number; authority: (typeof AUTHORITIES)[number]; clause: string }[] = [
  { upTo: 1000, authority: "department manager", clause: "PRC-001:2.1" },
  { upTo: 10000, authority: "procurement officer", clause: "PRC-001:2.2" },
  { upTo: 50000, authority: "finance director", clause: "PRC-001:2.3" },
];

export function requiredApproval(amount: string | number | null | undefined, currency: string | null | undefined) {
  if (amount === null || amount === undefined || currency !== "USD") return null;
  const n = Number(amount);
  if (Number.isNaN(n)) return null;
  return BANDS.find((b) => n <= b.upTo) ?? { upTo: Infinity, authority: AUTHORITIES[3], clause: "PRC-001:2.4" };
}

export const authorityRank = (a: string | null | undefined) => (a ? (AUTHORITIES as readonly string[]).indexOf(a) : -1);

/** Can this authority approve the amount? Unknown amounts or non-USD currencies need the top authority. */
export function canApprove(authority: string | null, amount: string | null | undefined, currency: string | null | undefined): boolean {
  const need = requiredApproval(amount, currency);
  if (!need) return authority === AUTHORITIES[3];
  return authorityRank(authority) >= authorityRank(need.authority);
}
