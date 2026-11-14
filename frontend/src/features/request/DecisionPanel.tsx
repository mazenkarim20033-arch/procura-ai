import { useMutation } from "@tanstack/react-query";
import { AlertTriangle, Check, MessageSquareMore, ShieldCheck, X } from "lucide-react";
import { useMemo, useState } from "react";
import { Badge, Button, Field, Select, Textarea, useToast } from "../../components/ui";
import { api, ApiError, type Assessment, type Decision, type RequestDetail } from "../../lib/api";
import { cn } from "../../lib/cn";
import { dateTime, label, money } from "../../lib/format";
import { isReviewer } from "../../lib/identity";
import { canApprove, requiredApproval } from "../../lib/policy";
import { useIdentity, useInvalidateRequest } from "../../lib/queries";

type Action = "approve" | "reject" | "request_info";
const ACTIONS: { id: Action; text: string; icon: typeof Check }[] = [
  { id: "approve", text: "Approve", icon: Check },
  { id: "reject", text: "Reject", icon: X },
  { id: "request_info", text: "Ask for information", icon: MessageSquareMore },
];
const SUBMIT: Record<Action, string> = { approve: "Approve request", reject: "Reject request", request_info: "Send information request" };
const MIN_REASON = 10;

function FinalRecord({ d }: { d: Decision }) {
  const approved = d.action === "approve";
  return (
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <Badge tone={approved ? "ok" : "danger"}>{approved ? "Approved" : "Rejected"}</Badge>
        <span className="text-[13px] text-muted">by {d.reviewer?.name ?? "a reviewer"} on {dateTime(d.created_at)}</span>
      </div>
      <p className="text-[13.5px] leading-relaxed">{d.reasoning}</p>
      {d.went_against_ai_signal && <div className="rounded-control border border-amber/30 bg-amber/10 px-3 py-2 text-[13px] text-amber">This decision went against what the AI assessment found. That is allowed and recorded.</div>}
      {d.finding_reviews.length > 0 && (
        <ul className="space-y-2 border-t border-line pt-3 text-[13px]">
          {d.finding_reviews.map((r) => (
            <li key={r.finding_id}><span className="font-medium">{r.title}</span> <span className="text-muted">marked {r.verdict}</span>{r.note && <div className="text-muted">“{r.note}”</div>}</li>
          ))}
        </ul>
      )}
      <p className="text-[12.5px] text-faint">Decisions are final and cannot be edited.</p>
    </div>
  );
}

export function DecisionPanel({ request, assessment, latestId, lastDecision, openInfo }: {
  request: RequestDetail; assessment: Assessment | undefined; latestId: string | undefined; lastDecision: Decision | undefined;
  openInfo: { message: string; created_at: string } | undefined;
}) {
  const me = useIdentity();
  const toast = useToast();
  const refresh = useInvalidateRequest();
  const [action, setAction] = useState<Action>("approve");
  const [reasoning, setReasoning] = useState("");
  const [reviews, setReviews] = useState<Record<string, { verdict: string; note: string }>>({});
  const [reply, setReply] = useState("");
  const setReview = (findingId: string, patch: Partial<{ verdict: string; note: string }>) =>
    setReviews((r) => ({ ...r, [findingId]: { ...(r[findingId] ?? { verdict: "", note: "" }), ...patch } }));
  const [error, setError] = useState<string | null>(null);

  const confirmed = useMemo(() => assessment?.findings.filter((f) => f.category === "confirmed_violation") ?? [], [assessment]);
  const need = requiredApproval(request.total_amount, request.currency);
  const sameAsRequester = !!request.requester_name && request.requester_name.trim().toLowerCase() === me.user.trim().toLowerCase();
  const final = request.status === "approved" || request.status === "rejected";
  const stale = !!assessment && assessment.id !== latestId;
  const authorityOk = canApprove(me.authority, request.total_amount, request.currency);

  const overrideProblems = action === "approve"
    ? confirmed.filter((f) => reviews[f.id]?.verdict !== "disagree" || (reviews[f.id]?.note ?? "").trim().length < MIN_REASON)
    : [];
  const blockers: string[] = [];
  if (action !== "request_info" && !assessment) blockers.push("Run the AI assessment first so you decide with the evidence in front of you.");
  if (action !== "request_info" && stale) blockers.push("Switch to the latest assessment version to record a decision.");
  if (action === "approve" && !authorityOk) blockers.push(need ? `A ${money(request.total_amount, request.currency)} request needs the ${need.authority} or higher (${need.clause}). You are acting as ${me.authority ?? "someone without approval authority"}.` : "The amount is missing or not in USD, so only the chief financial officer can approve.");
  if (overrideProblems.length > 0) blockers.push("To approve over a confirmed violation, mark each one “disagree” and explain why.");
  if (reasoning.trim().length < MIN_REASON) blockers.push(`Write your reasoning (at least ${MIN_REASON} characters).`);

  // Do not nag about the empty reasoning box before the person has started writing.
  const shownBlockers = blockers.filter((b) => !(b.startsWith("Write your reasoning") && reasoning.length === 0));

  const submit = useMutation({
    mutationFn: () => api.post(`/requests/${request.id}/decisions`, {
      action, reasoning, assessment_id: action === "request_info" ? undefined : assessment?.id,
      finding_reviews: Object.entries(reviews).filter(([id]) => confirmed.some((f) => f.id === id)).map(([finding_id, r]) => ({ finding_id, verdict: r.verdict, note: r.note || undefined })),
    }),
    onSuccess: () => { toast({ tone: "ok", title: action === "approve" ? "Request approved" : action === "reject" ? "Request rejected" : "Information requested" }); setReasoning(""); setReviews({}); setError(null); refresh(request.id); },
    onError: (e) => { const msg = e instanceof ApiError ? e.detail : "The decision could not be saved."; setError(msg); toast({ tone: "danger", title: "Decision not recorded", body: msg }); },
  });
  const respond = useMutation({
    mutationFn: () => api.post(`/requests/${request.id}/info-response`, { message: reply }),
    onSuccess: () => { toast({ tone: "ok", title: "Reply sent", body: "The request is back in the review queue." }); setReply(""); refresh(request.id); },
    onError: (e) => toast({ tone: "danger", title: "Reply not sent", body: e instanceof ApiError ? e.detail : undefined }),
  });

  let body;
  if (final && lastDecision) body = <FinalRecord d={lastDecision} />;
  else if (request.status === "info_requested" && openInfo) {
    body = (
      <div className="space-y-4">
        <div className="rounded-control border border-amber/30 bg-amber/5 p-3.5 text-[13.5px]">
          <div className="font-medium text-amber">Waiting for the requester</div>
          <p className="mt-1 text-muted">{openInfo.message}</p>
        </div>
        <Field label="Reply to the reviewer" hint="Attach any new documents on the Documents tab, then send this.">
          {(id) => <Textarea id={id} value={reply} onChange={(e) => setReply(e.target.value)} placeholder="What you are sending and where to find it" />}
        </Field>
        <Button variant="primary" className="w-full" loading={respond.isPending} disabled={reply.trim().length < 3} onClick={() => respond.mutate()}>Send reply</Button>
      </div>
    );
  } else if (!isReviewer(me)) {
    body = <p className="text-[13.5px] text-muted">Only reviewers record decisions. You are acting as <span className="text-text">{me.user}</span>. Switch persona in the top bar to review this request.</p>;
  } else if (sameAsRequester) {
    body = <div className="rounded-control border border-amber/30 bg-amber/10 p-3.5 text-[13.5px] text-amber">You submitted this request, so you cannot decide on it (PRC-001:3.1, segregation of duties). Switch to another reviewer.</div>;
  } else {
    body = (
      <form className="space-y-4" onSubmit={(e) => { e.preventDefault(); setError(null); submit.mutate(); }}>
        <div role="radiogroup" aria-label="Decision" className="grid grid-cols-3 gap-1.5 rounded-control bg-ink p-1">
          {ACTIONS.map(({ id, text, icon: Icon }) => (
            <button type="button" key={id} role="radio" aria-checked={action === id} onClick={() => setAction(id)}
              className={cn("flex flex-col items-center gap-1 rounded-[5px] px-1 py-2 text-[12.5px] font-medium transition-colors",
                action === id ? "bg-raised text-text shadow-sm" : "text-muted hover:text-text")}>
              <Icon className="h-4 w-4" aria-hidden />{text}
            </button>
          ))}
        </div>

        {action === "approve" && confirmed.length > 0 && (
          <fieldset className="space-y-3 rounded-control border border-danger/25 bg-danger/5 p-3.5">
            <legend className="px-1 text-[13px] font-medium text-danger">Confirmed violations to override</legend>
            <p className="text-[12.5px] text-muted">Approving over a violation is allowed, but you must say why you disagree with each one.</p>
            {confirmed.map((f) => (
              <div key={f.id} className="space-y-1.5">
                <div className="text-[13px] font-medium">{f.title}</div>
                <div className="grid grid-cols-[110px_1fr] gap-2">
                  <Select aria-label={`Verdict on ${f.title}`} value={reviews[f.id]?.verdict ?? ""} onChange={(e) => setReview(f.id, { verdict: e.target.value })} className="h-8 text-[13px]">
                    <option value="" disabled>Verdict</option><option value="disagree">Disagree</option><option value="agree">Agree</option><option value="unsure">Unsure</option>
                  </Select>
                  <input aria-label={`Why you disagree with ${f.title}`} placeholder="Why this does not stand" value={reviews[f.id]?.note ?? ""} onChange={(e) => setReview(f.id, { note: e.target.value })}
                    className="h-8 rounded-control border border-line-strong bg-ink px-2.5 text-[13px] placeholder:text-faint focus:border-iris focus:outline-none focus:ring-2 focus:ring-iris/30" />
                </div>
              </div>
            ))}
          </fieldset>
        )}

        <Field label="Your reasoning" hint={`Recorded with your name and shown in the history. ${reasoning.trim().length}/${MIN_REASON} characters minimum.`}>
          {(id) => <Textarea id={id} value={reasoning} onChange={(e) => setReasoning(e.target.value)} placeholder={action === "request_info" ? "What you need from the requester" : "What you checked and why you decided this"} />}
        </Field>

        {shownBlockers.length > 0 && (
          <ul className="space-y-1.5 text-[12.5px] text-amber">{shownBlockers.map((b) => <li key={b} className="flex gap-2"><AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />{b}</li>)}</ul>
        )}
        {error && <div role="alert" className="rounded-control border border-danger/30 bg-danger/10 p-3 text-[13px] text-danger">{error}</div>}

        <Button type="submit" variant={action === "reject" ? "danger" : "primary"} className="w-full" loading={submit.isPending} disabled={blockers.length > 0}>{SUBMIT[action]}</Button>
      </form>
    );
  }

  return (
    <aside aria-label="Your decision" className="rounded-panel border border-iris/35 bg-panel shadow-[0_0_0_1px_rgb(var(--iris)/0.06),0_18px_40px_-24px_rgb(var(--iris)/0.45)]">
      <header className="border-b border-line px-5 py-4">
        <h2 className="flex items-center gap-2 font-sans text-[15px] font-semibold tracking-normal"><ShieldCheck className="h-4 w-4 text-[#a89bff]" aria-hidden />Your decision</h2>
        <p className="mt-1 text-[12.5px] leading-snug text-muted">The AI assessment on the left is advice. Only a person can approve or reject, and the decision is stored separately from it.</p>
      </header>
      <div className="space-y-4 p-5">
        <div className="flex items-center justify-between text-[13px]">
          <span className="text-muted">Approval level for this amount</span>
          <span className="text-right font-medium">{need ? `${label(need.authority)} (${need.clause})` : "Chief financial officer only"}</span>
        </div>
        {body}
      </div>
    </aside>
  );
}
