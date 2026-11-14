import { Badge, type Tone } from "./ui";
import { label } from "../lib/format";

const requestTone: Record<string, Tone> = { submitted: "neutral", assessed: "cobalt", info_requested: "amber", approved: "ok", rejected: "danger" };
export const StatusBadge = ({ status }: { status: string }) => <Badge tone={requestTone[status] ?? "neutral"}>{label(status)}</Badge>;

const riskTone: Record<string, Tone> = { low: "ok", medium: "amber", high: "danger", critical: "danger" };
export const RiskBadge = ({ risk }: { risk: string }) => (
  <Badge tone={riskTone[risk] ?? "neutral"} className={risk === "critical" ? "font-semibold" : ""}>{label(risk)} risk</Badge>
);

const complianceTone: Record<string, Tone> = { no_issues_found: "ok", issues_found: "amber", needs_information: "cobalt", inconclusive: "quiet" };
export const ComplianceBadge = ({ status }: { status: string }) => <Badge tone={complianceTone[status] ?? "neutral"}>{label(status)}</Badge>;

export const categoryTone: Record<string, Tone> = {
  confirmed_violation: "danger", potential_violation: "amber", missing_information: "cobalt", inconclusive: "quiet", compliant: "ok",
};
export const CategoryBadge = ({ category }: { category: string }) => <Badge tone={categoryTone[category] ?? "neutral"}>{label(category)}</Badge>;

export const MockBadge = ({ title }: { title?: string }) => (
  <Badge tone="neutral" className="border-dashed" title={title ?? "Produced by the mock provider: deterministic keyword rules, not an AI model"}>Mock AI</Badge>
);

export const ActorBadge = ({ type }: { type: string }) => (
  <Badge tone={type === "ai" ? "quiet" : type === "system" ? "neutral" : "cobalt"}>{type === "ai" ? "AI" : type === "user" ? "Person" : "System"}</Badge>
);
