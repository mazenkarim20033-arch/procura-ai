import { useMutation } from "@tanstack/react-query";
import { ChevronLeft } from "lucide-react";
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { StatusBadge } from "../components/badges";
import { Badge, ErrorState, KeyValue, Panel, Skeleton, Tabs, useToast } from "../components/ui";
import { AssessmentPanel } from "../features/request/AssessmentPanel";
import { DecisionPanel } from "../features/request/DecisionPanel";
import { DocumentsPanel } from "../features/request/DocumentsPanel";
import { HistoryPanel } from "../features/request/HistoryPanel";
import { IntakePanel } from "../features/request/IntakePanel";
import { QuotesPanel } from "../features/request/QuotesPanel";
import { api, ApiError, type Assessment } from "../lib/api";
import { date, label, money } from "../lib/format";
import { isReviewer } from "../lib/identity";
import { requiredApproval } from "../lib/policy";
import { useAssessment, useAssessments, useComparison, useHistory, useIdentity, useIntake, useInvalidateRequest, useRequest } from "../lib/queries";

type Tab = "assessment" | "intake" | "quotes" | "documents" | "history";

export function RequestDetail() {
  const { id = "" } = useParams();
  const me = useIdentity();
  const toast = useToast();
  const refresh = useInvalidateRequest();
  const [tab, setTab] = useState<Tab>("assessment");
  const [picked, setPicked] = useState<string | undefined>();

  const request = useRequest(id);
  const versions = useAssessments(id);
  const latestId = versions.data?.[0]?.id;
  const selectedId = picked ?? latestId;
  const assessment = useAssessment(selectedId);
  const intake = useIntake(id);
  const comparison = useComparison(id);
  const history = useHistory(id);
  useEffect(() => setPicked(undefined), [id]);

  const run = useMutation({
    mutationFn: () => api.post<Assessment>(`/requests/${id}/assess`),
    onSuccess: (a) => { setPicked(a.id); toast({ tone: "ok", title: `Assessment version ${a.version} ready`, body: a.is_mock ? "Produced by the mock provider." : undefined }); refresh(id); },
    onError: (e) => toast({ tone: "danger", title: "Assessment failed", body: e instanceof ApiError ? e.detail : undefined }),
  });

  if (request.isLoading) return <div className="space-y-4"><Skeleton className="h-10 w-72" /><Skeleton className="h-24" /><Skeleton className="h-96" /></div>;
  if (request.error || !request.data) return <ErrorState error={request.error} retry={() => request.refetch()} />;
  const r = request.data;
  const need = requiredApproval(r.total_amount, r.currency);
  const lastDecision = history.data?.decisions.at(-1);
  const openInfo = history.data?.information_requests.find((i) => !i.resolved_at);
  const final = r.status === "approved" || r.status === "rejected";

  return (
    <div>
      <Link to="/requests" className="mb-3 inline-flex items-center gap-1 text-[13px] text-muted hover:text-text"><ChevronLeft className="h-4 w-4" aria-hidden />Purchase requests</Link>
      <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-[32px] font-medium leading-tight">{r.request_no}</h1>
            <StatusBadge status={r.status} />
            {r.is_synthetic && <Badge tone="neutral" className="border-dashed" title="Part of the synthetic demo dataset">Synthetic</Badge>}
          </div>
          <p className="mt-1 text-[14px] text-muted">{r.supplier_name ?? "No supplier named"} for <span className="num text-text">{money(r.total_amount, r.currency)}</span>, requested by {r.requester_name ?? "an unnamed requester"}{r.department ? ` in ${r.department}` : ""} on {date(r.submitted_at)}</p>
        </div>
      </div>

      <div className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_380px]">
        <div className="min-w-0 space-y-5">
          <Panel title="The request">
            <div className="grid gap-6 lg:grid-cols-[1.2fr_1fr]">
              <div>
                <h3 className="mb-2 font-sans text-[13px] font-medium tracking-normal text-muted">Why it is needed</h3>
                <p className="max-w-prose text-[14px] leading-relaxed">{r.justification || <em className="text-amber">No justification was given.</em>}</p>
                <KeyValue className="mt-5" items={[
                  { k: "Approval level", v: need ? `${label(need.authority)} or higher (${need.clause})` : "Chief financial officer only: amount missing or not in USD" },
                  { k: "Category", v: r.category ? label(r.category) : "Not recorded" },
                ]} />
              </div>
              <div className="overflow-x-auto rounded-control border border-line">
                <table className="w-full text-left text-[13px]">
                  <thead><tr className="border-b border-line text-muted"><th className="px-3 py-2 font-medium">Item</th><th className="px-3 py-2 text-right font-medium">Qty</th><th className="px-3 py-2 text-right font-medium">Line total</th></tr></thead>
                  <tbody>{r.items.length === 0 ? <tr><td colSpan={3} className="px-3 py-3 text-amber">No items listed.</td></tr> : r.items.map((it, i) => (
                    <tr key={i} className="border-b border-line/60 last:border-0"><td className="px-3 py-2">{it.description}</td><td className="num px-3 py-2 text-right">{Number(it.quantity)}</td><td className="num px-3 py-2 text-right">{money(it.line_total)}</td></tr>
                  ))}</tbody>
                </table>
              </div>
            </div>
          </Panel>

          <Tabs value={tab} onChange={setTab} tabs={[
            { id: "assessment", label: "AI assessment", count: assessment.data?.findings.length },
            { id: "intake", label: "Intake checks", count: intake.data?.summary.issues },
            { id: "quotes", label: "Quotations", count: comparison.data?.quotes.length },
            { id: "documents", label: "Documents", count: r.documents.length },
            { id: "history", label: "History", count: history.data?.timeline.length },
          ]} />

          {tab === "assessment" && (
            <AssessmentPanel assessment={assessment.data} versions={versions.data ?? []} selected={selectedId} onSelect={setPicked}
              loading={versions.isLoading || (!!selectedId && assessment.isLoading)} canRun={isReviewer(me) && !final} running={run.isPending} onRun={() => run.mutate()} />
          )}
          {tab === "intake" && <IntakePanel intake={intake.data} loading={intake.isLoading} error={intake.error} />}
          {tab === "quotes" && <QuotesPanel data={comparison.data} loading={comparison.isLoading} error={comparison.error} />}
          {tab === "documents" && <DocumentsPanel requestId={id} attached={r.documents} locked={final} />}
          {tab === "history" && <HistoryPanel data={history.data} loading={history.isLoading} error={history.error} />}
        </div>

        <div className="xl:sticky xl:top-20">
          <DecisionPanel request={r} assessment={assessment.data} latestId={latestId} lastDecision={lastDecision} openInfo={openInfo} />
        </div>
      </div>
    </div>
  );
}
