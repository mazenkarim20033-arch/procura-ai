import { Link, useNavigate } from "react-router-dom";
import { ComplianceBadge, MockBadge, RiskBadge, StatusBadge } from "../components/badges";
import { BarList, Donut, RISK_COLORS, WeeklyArea } from "../components/charts";
import { Badge, EmptyState, ErrorState, PageHeader, Panel, Skeleton, Stat, tableClasses as t } from "../components/ui";
import { cn } from "../lib/cn";
import { hours, label, money, percent } from "../lib/format";
import { isReviewer } from "../lib/identity";
import { useIdentity, useOverview, useQueue, useRequests } from "../lib/queries";

function Queue() {
  const queue = useQueue();
  const nav = useNavigate();
  if (queue.isLoading) return <Skeleton className="h-56" />;
  if (queue.error) return <ErrorState error={queue.error} retry={() => queue.refetch()} />;
  const rows = (queue.data ?? []).slice(0, 7);
  return (
    <Panel title="Needs a decision" description="Highest AI risk first, then oldest. The ordering is a hint; you judge each request yourself." flush
      action={<Link to="/requests" className="text-[13px] text-[#a89bff] hover:text-[#c3b9ff]">All requests</Link>}>
      {rows.length === 0 ? <EmptyState title="Nothing is waiting" body="New requests appear here as soon as they are submitted." /> : (
        <div className={t.wrap}>
          <table className={t.table}>
            <thead><tr><th className={t.th}>Request</th><th className={t.th}>AI assessment</th><th className={cn(t.th, "text-right")}>Amount</th><th className={t.th}>Needs</th><th className={cn(t.th, "text-right")}>Waiting</th></tr></thead>
            <tbody>
              {rows.map((q) => (
                <tr key={q.id} className={cn(t.row, "cursor-pointer")} onClick={() => nav(`/requests/${q.id}`)}>
                  <td className={t.td}><Link to={`/requests/${q.id}`} onClick={(e) => e.stopPropagation()} className="whitespace-nowrap font-medium hover:text-[#b4a8ff]">{q.request_no}</Link><div className="text-[12.5px] text-muted">{q.supplier ?? "No supplier"}</div></td>
                  <td className={t.td}>{q.latest_assessment ? <div className="flex flex-wrap items-center gap-1.5"><RiskBadge risk={q.latest_assessment.risk} /><ComplianceBadge status={q.latest_assessment.status} />{q.latest_assessment.is_mock && <MockBadge />}</div> : <Badge tone="neutral">Not assessed</Badge>}</td>
                  <td className={cn(t.td, "num text-right")}>{money(q.total, q.currency)}</td>
                  <td className={t.td}>{q.required_approval ? label(q.required_approval.authority) : "CFO only"}</td>
                  <td className={cn(t.td, "num text-right text-muted")}>{q.age_days} {q.age_days === 1 ? "day" : "days"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Panel>
  );
}

function ReviewerView() {
  const ov = useOverview({});
  if (ov.isLoading) return <div className="space-y-5"><Skeleton className="h-56" /><Skeleton className="h-48" /></div>;
  if (ov.error || !ov.data) return <ErrorState error={ov.error} retry={() => ov.refetch()} />;
  const d = ov.data;
  const statusRows = Object.entries(d.requests.by_status).map(([k, v]) => ({ label: label(k), value: v }));
  const risk = ["low", "medium", "high", "critical"].map((k) => ({ name: label(k), value: d.assessments.latest_risk_distribution[k] ?? 0, color: RISK_COLORS[k] })).filter((x) => x.value > 0);
  const agree = d.decisions.ai_agreement;
  const mock = d.assessments.by_provider.filter((p) => p.is_mock).reduce((s, p) => s + p.n, 0);
  return (
    <div className="space-y-5">
      <Queue />
      <Panel>
        <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
          <Stat label="Purchase requests" value={d.requests.total} hint={`${d.requests.queue.awaiting_assessment} not yet assessed`} />
          <Stat label="Awaiting a decision" value={d.requests.queue.awaiting_decision} hint={`${d.requests.queue.awaiting_requester} waiting for the requester`} />
          <Stat label="Decided by people" value={d.decisions.total} hint={`${d.decisions.by_action.approve ?? 0} approved, ${d.decisions.by_action.reject ?? 0} rejected`} />
          <Stat label="Median time to decision" value={hours(d.decisions.hours_to_first_decision.median_hours)} hint={`from ${d.decisions.hours_to_first_decision.n} decided requests`} />
        </div>
      </Panel>
      <div className="grid gap-5 lg:grid-cols-2">
        <Panel title="Requests by status"><BarList rows={statusRows} /></Panel>
        <Panel title="AI risk rating" description="Latest assessment of each request."><Donut data={risk} centerLabel="assessed" /></Panel>
      </div>
      <div className="grid gap-5 lg:grid-cols-[1.4fr_1fr]">
        <Panel title="Requests submitted per week"><WeeklyArea data={d.requests.submitted_per_week.map((w) => ({ week: w.week, n: w.n }))} /></Panel>
        <Panel title="People and the AI" description="How often a decision matched the AI's signal.">
          <Stat label="Agreement" value={percent(agree.agreement_rate)} hint={agree.decisions_with_clear_signal ? `${agree.decisions_with_clear_signal} decisions with a clear AI signal` : "No decisions with a clear signal yet"} />
          {mock > 0 && <p className="mt-4 text-[12.5px] text-faint">{mock} of {d.assessments.total} assessments came from the mock provider, so this reflects the demo, not model quality.</p>}
        </Panel>
      </div>
    </div>
  );
}

function RequesterView() {
  const me = useIdentity();
  const reqs = useRequests();
  const mine = (reqs.data ?? []).filter((r) => r.requester_name?.toLowerCase() === me.user.toLowerCase());
  return (
    <Panel title="Your requests" description="Overview statistics are for reviewers. Switch persona in the top bar to see them." flush>
      {reqs.isLoading ? <Skeleton className="m-5 h-32" /> : mine.length === 0 ? <EmptyState title="You have not submitted anything yet" body="Create a purchase request on the Purchase requests page." action={<Link to="/requests" className="text-[#a89bff]">Go to requests</Link>} /> : (
        <ul>{mine.map((r) => <li key={r.id} className="flex items-center gap-3 border-b border-line px-5 py-3 last:border-0"><Link to={`/requests/${r.id}`} className="flex-1 font-medium hover:text-[#b4a8ff]">{r.request_no} <span className="font-normal text-muted">{r.supplier_name}</span></Link><StatusBadge status={r.status} /></li>)}</ul>
      )}
    </Panel>
  );
}

export function Overview() {
  const me = useIdentity();
  return (
    <>
      <PageHeader title="Overview" subtitle="What needs a decision now, and how the review process is going." />
      {isReviewer(me) ? <ReviewerView /> : <RequesterView />}
    </>
  );
}
