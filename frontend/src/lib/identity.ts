/** Demo-grade identity: sent as headers so the server can enforce roles. NOT real authentication. */
export type Role = "requester" | "reviewer" | "admin";
export interface Identity {
  role: Role;
  user: string;
  authority: string | null;
  label: string;
}

export const AUTHORITIES = ["department manager", "procurement officer", "finance director", "chief financial officer"] as const;

export const PERSONAS: Identity[] = [
  { role: "requester", user: "Layla Hassan", authority: null, label: "Requester" },
  { role: "reviewer", user: "Rami Haddad", authority: "procurement officer", label: "Procurement officer" },
  { role: "reviewer", user: "Dina Samir", authority: "finance director", label: "Finance director" },
  { role: "admin", user: "Omar Nassar", authority: "chief financial officer", label: "Administrator" },
];

const KEY = "procura.identity.v1";
let current: Identity = PERSONAS[2];
const listeners = new Set<() => void>();

try {
  const raw = localStorage.getItem(KEY);
  if (raw) current = { ...PERSONAS[2], ...JSON.parse(raw) };
} catch {
  /* storage unavailable: keep the default persona */
}

export const getIdentity = () => current;

export function setIdentity(next: Identity) {
  current = next;
  try {
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* ignore */
  }
  listeners.forEach((l) => l());
}

export const subscribeIdentity = (fn: () => void) => {
  listeners.add(fn);
  return () => listeners.delete(fn);
};

export const isReviewer = (i: Identity) => i.role === "reviewer" || i.role === "admin";
