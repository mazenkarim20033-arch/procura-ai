import { ActorBadge, ComplianceBadge, MockBadge, RiskBadge } from "../../components/badges";
import { Badge, EmptyState, ErrorState, Panel, Skeleton } from "../../components/ui";
import type { History, HistoryEvent } from "../../lib/api";
import { dateTime, label } from "../../lib/format";

function describe(e: HistoryEvent): string {
  const d = e.detail as Record<string, string | number | null | boolean | undefined>;
  switch (e.action) {
    case "request.created": return "Request created";
    case "request.document_attached": return `Document attached (${label(String(d.doc_type ?? "document"))})`;
    case "assessment.created": return `AI assessment version ${d.version}: ${label(String(d.status))}, ${label(String(d.risk))} risk${d.is_mock ? " (mock)" : ""}`;
    case "decision.recorded": return `Decision recorded: ${label(String(d.action))}`;
    case "request.info_provided": return "Information provided by the requester";
    default: return label(e.action.replace(".", " "));
  }
}

export function HistoryPanel({ data, loading, error }: { data: History | undefined; loading: boolean; error: unknown }) {
  if (loading) return <Skeleton className="h-64" />;
  if (error || !data) return <ErrorState error={error} />;
  return (
    <div className="space-y-5">
      <Panel title="Timeline" description={data.note} flush>
        {data.timeline.length === 0 ? <EmptyState title="No activity yet" /> : (
          <ol className="relative">
            {data.timeline.map((e, i) => (
              <li key={i} className="flex gap-4 border-b border-line px-5 py-3 last:border-0">
                <div className="w-[132px] shrink-0 pt-0.5 text-[12.5px] text-faint">{dateTime(e.ts)}</div>
                <div className="min-w-0 flex-1 text-[13.5px]">
                  <div className="flex flex-wrap items-center gap-2"><ActorBadge type={e.actor_type} /><span>{describe(e)}</span></div>
                  {e.actor && <div className="mt-0.5 text-[12.5px] text-faint">by {e.actor}</div>}
                </div>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="AI assessments" description="Recommendations only." flush>
          {data.ai_assessments.length === 0 ? <EmptyState title="None yet" /> : (
            <ul>{data.ai_assessments.map((a) => (
              <li key={a.id} className="flex flex-wrap items-center gap-2 border-b border-line px-5 py-3 text-[13.5px] last:border-0">
                <span className="font-medium">Version {a.version}</span><ComplianceBadge status={a.status} /><RiskBadge risk={a.risk} />{a.is_mock && <MockBadge />}
                <span className="ml-auto text-[12.5px] text-faint">{dateTime(a.created_at)}</span>
              </li>
            ))}</ul>
          )}
        </Panel>
        <Panel title="Human decisions" description="The only decisions that count." flush>
          {data.decisions.length === 0 ? <EmptyState title="No decision yet" /> : (
            <ul>{data.decisions.map((d) => (
              <li key={d.id} className="space-y-1.5 border-b border-line px-5 py-3 text-[13.5px] last:border-0">
                <div className="flex flex-wrap items-center gap-2">
                  <Badge tone={d.action === "approve" ? "ok" : d.action === "reject" ? "danger" : "amber"}>{label(d.action)}</Badge>
                  <span>{d.reviewer?.name}</span><span className="ml-auto text-[12.5px] text-faint">{dateTime(d.created_at)}</span>
                </div>
                <p className="text-muted">{d.reasoning}</p>
                {d.ai_recommendation_at_decision && <p className="text-[12.5px] text-faint">AI said {label(d.ai_recommendation_at_decision.status).toLowerCase()} (version {d.ai_recommendation_at_decision.version}){d.went_against_ai_signal && "; this decision went against it"}</p>}
              </li>
            ))}</ul>
          )}
        </Panel>
      </div>

      {data.information_requests.length > 0 && (
        <Panel title="Information requests" flush>
          <ul>{data.information_requests.map((r) => (
            <li key={r.id} className="space-y-1 border-b border-line px-5 py-3 text-[13.5px] last:border-0">
              <div className="flex items-center gap-2"><Badge tone={r.resolved_at ? "ok" : "amber"}>{r.resolved_at ? "Answered" : "Open"}</Badge><span className="text-[12.5px] text-faint">Asked {dateTime(r.created_at)}{r.resolved_at && `, answered ${dateTime(r.resolved_at)}`}</span></div>
              <p className="text-muted">{r.message}</p>
            </li>
          ))}</ul>
        </Panel>
      )}
    </div>
  );
}
