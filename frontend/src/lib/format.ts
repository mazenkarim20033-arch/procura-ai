const CURRENCY_DIGITS = new Intl.NumberFormat("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });

export function money(amount: string | number | null | undefined, currency?: string | null): string {
  if (amount === null || amount === undefined || amount === "") return "Not stated";
  const n = typeof amount === "number" ? amount : Number(amount);
  if (Number.isNaN(n)) return String(amount);
  return `${currency ? currency + " " : ""}${CURRENCY_DIGITS.format(n)}`;
}

export function compactNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return "n/a";
  return new Intl.NumberFormat("en-US", { notation: "compact", maximumFractionDigits: 1 }).format(n);
}

export function date(value: string | null | undefined): string {
  if (!value) return "n/a";
  const d = new Date(value);
  return Number.isNaN(d.getTime()) ? value : d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function dateTime(value: string | null | undefined): string {
  if (!value) return "n/a";
  const d = new Date(value);
  return Number.isNaN(d.getTime())
    ? value
    : d.toLocaleString("en-GB", { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" });
}

export function ago(value: string | null | undefined): string {
  if (!value) return "n/a";
  const seconds = (Date.now() - new Date(value).getTime()) / 1000;
  if (Number.isNaN(seconds)) return value;
  const steps: [number, string][] = [[60, "second"], [3600, "minute"], [86400, "hour"], [86400 * 30, "day"], [86400 * 365, "month"]];
  if (seconds < 45) return "just now";
  let divisor = 1;
  for (const [limit, unit] of steps) {
    if (seconds < limit) {
      const n = Math.max(1, Math.round(seconds / divisor));
      return `${n} ${unit}${n === 1 ? "" : "s"} ago`;
    }
    divisor = limit;
  }
  const years = Math.round(seconds / (86400 * 365));
  return `${years} year${years === 1 ? "" : "s"} ago`;
}

export function hours(h: number | null | undefined): string {
  if (h === null || h === undefined) return "n/a";
  if (h < 1) return `${Math.max(1, Math.round(h * 60))} min`;
  if (h < 48) return `${h.toFixed(1)} h`;
  return `${(h / 24).toFixed(1)} days`;
}

export function ms(value: number | null | undefined): string {
  if (value === null || value === undefined) return "n/a";
  return value < 1000 ? `${Math.round(value)} ms` : `${(value / 1000).toFixed(1)} s`;
}

export function percent(value: number | null | undefined, digits = 0): string {
  if (value === null || value === undefined) return "n/a";
  return `${(value * 100).toFixed(digits)}%`;
}

const LABELS: Record<string, string> = {
  confirmed_violation: "Confirmed violation",
  potential_violation: "Potential violation",
  missing_information: "Missing information",
  inconclusive: "Inconclusive",
  compliant: "Compliant",
  no_issues_found: "No issues found",
  issues_found: "Issues found",
  needs_information: "Needs information",
  info_requested: "Information requested",
  request_info: "Request information",
  agreed_with_ai: "Agreed with the AI",
  approved_despite_ai_issues: "Approved despite AI issues",
  rejected_despite_clean_ai: "Rejected despite a clean AI result",
  no_clear_ai_signal: "No clear AI signal",
};

/** Human wording for a machine value (statuses, categories, doc types). */
export function label(value: string | null | undefined): string {
  if (!value) return "n/a";
  if (LABELS[value]) return LABELS[value];
  const spaced = value.replace(/[_-]+/g, " ").trim();
  return spaced.charAt(0).toUpperCase() + spaced.slice(1);
}

export const plural = (n: number, one: string, many = one + "s") => `${n} ${n === 1 ? one : many}`;
