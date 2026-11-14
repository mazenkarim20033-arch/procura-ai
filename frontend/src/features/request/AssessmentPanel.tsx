import { BookMarked, ChevronDown, FileText, Sparkles, TextCursorInput } from "lucide-react";
import { useMemo, useState } from "react";
import { ComplianceBadge, CategoryBadge, MockBadge, RiskBadge, categoryTone } from "../../components/badges";
import { Badge, Button, EmptyState, Panel, Select, Skeleton } from "../../components/ui";
import type { Assessment, AssessmentListItem, Evidence, Finding } from "../../lib/api";
import { cn } from "../../lib/cn";
import { ago, compactNumber, dateTime, label, ms, percent } from "../../lib/format";

export const CATEGORY_ORDER = ["confirmed_violation", "potential_violation", "missing_information", "inconclusive", "compliant"] as const;

const barTone: Record<string, string> = {
  danger: "bg-danger", amber: "bg-amber", cobalt: "bg-cobalt", quiet: "bg-quiet", ok: "bg-ok", neutral: "bg-line-strong",
};
const sectionTitle: Record<string, string> = {
  confirmed_violation: "Confirmed violations", potential_violation: "Potential violations to investigate",
  missing_information: "Missing information", inconclusive: "Could not be checked", compliant: "Checked and compliant",
};
const sectionHelp: Record<string, string> = {
  confirmed_violation: "A fact in the submitted file contradicts a policy clause. Only deterministic rules can produce these.",
  potential_violation: "Something suspicious that needs a person to look. The AI cannot confirm it.",
  missing_information: "The file lacks what a clause needs, so compliance cannot be judged. This is not a violation.",
  inconclusive: "The clause applies but the data was not enough to say either way.",
  compliant: "Clauses that clearly apply and are satisfied.",
};

function EvidenceItem({ e }: { e: Evidence }) {
  const ref = (e.ref.clause_ref as string | undefined) ?? undefined;
  if (e.kind === "policy_chunk") {
    return (
      <figure className="rounded-control border border-line bg-ink/60 p-3.5">
        <div className="mb-2 flex flex-wrap items-center gap-2 text-[12.5px] text-muted">
          <BookMarked className="h-3.5 w-3.5" aria-hidden />Policy clause {ref && <Badge tone="quiet">{ref}</Badge>}
        </div>
        <blockquote className="border-l-2 border-iris/70 pl-3.5 font-display text-[15.5px] italic leading-[1.45] text-text">“{e.quote}”</blockquote>
        {e.chunk_id && <figcaption className="mt-2 text-[12px] text-faint">Quoted from the stored clause <span className="font-mono">{e.chunk_id.slice(0, 8)}</span></figcaption>}
      </figure>
    );
  }
  if (e.kind === "request_field") {
    const field = String(e.ref.field ?? "field");
    const value = e.ref.value;
    return (
      <div className="flex items-start gap-3 rounded-control border border-line bg-ink/60 px-3.5 py-2.5 text-[13.5px]">
        <TextCursorInput className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
        <div className="min-w-0">
          <span className="text-muted">Request field </span><span className="font-medium">{label(field)}</span>
          <span className="text-muted">: </span>
          <span className="break-words">{value === null || value === undefined || value === "" ? <em className="text-faint">empty</em> : typeof value === "string" ? value : JSON.stringify(value)}</span>
          {e.quote && <div className="mt-1 text-[12.5px] text-faint">Matched text: “{e.quote}”</div>}
        </div>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3 rounded-control border border-line bg-ink/60 px-3.5 py-2.5 text-[13.5px]">
      <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted" aria-hidden />
      <div className="min-w-0">
        <span className="text-muted">{e.kind === "quotation" ? "Quotation" : "Document"} </span>
        <span className="break-all font-medium">{String(e.ref.filename ?? e.ref.source ?? "")}</span>
        {e.quote && <div className="mt-1 break-words text-[12.5px] text-faint">“{e.quote}”</div>}
      </div>
    </div>
  );
}

function FindingRow({ f }: { f: Finding }) {
  const [open, setOpen] = useState(false);
  const tone = categoryTone[f.category] ?? "neutral";
  return (
    <li className="flex gap-4 border-b border-line px-5 py-4 last:border-0">
      <span className={cn("w-[3px] shrink-0 self-stretch rounded-full", barTone[tone])} aria-hidden />
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
          <h3 className="font-sans text-[14.5px] font-medium tracking-normal">{f.title}</h3>
          {f.source === "rule"
            ? <Badge tone="neutral" title="Produced by a deterministic rule, not a model">Rule {f.rule_code}</Badge>
            : <Badge tone="quiet" title="Written by a language model; every quote is verified against the stored clause">Model finding</Badge>}
        </div>
        <p className="mt-1.5 max-w-prose text-[13.5px] leading-relaxed text-muted">{f.explanation}</p>
        {f.source === "llm" && f.confidence !== null && <p className="mt-1 text-[12.5px] text-faint">Model confidence {f.confidence.toFixed(2)}, an uncalibrated self-estimate.</p>}
        {f.evidence.length > 0 && (
          <>
            <button onClick={() => setOpen(!open)} aria-expanded={open} className="mt-2.5 inline-flex items-center gap-1.5 rounded-control text-[13px] font-medium text-[#a89bff] hover:text-[#c3b9ff]">
              <ChevronDown className={cn("h-3.5 w-3.5 transition-transform", open && "rotate-180")} aria-hidden />
              {open ? "Hide evidence" : `Show evidence (${f.evidence.length})`}
            </button>
            {open && <div className="reveal mt-2.5 space-y-2">{f.evidence.map((e, i) => <EvidenceItem key={i} e={e} />)}</div>}
          </>
        )}
      </div>
    </li>
  );
}

export function AssessmentPanel({ assessment, versions, selected, onSelect, loading, canRun, running, onRun }: {
  assessment: Assessment | undefined; versions: AssessmentListItem[]; selected: string | undefined; onSelect: (id: string) => void;
  loading: boolean; canRun: boolean; running: boolean; onRun: () => void;
}) {
  const [filter, setFilter] = useState<string | null>(null);
  const grouped = useMemo(() => {
    const m: Record<string, Finding[]> = {};
    assessment?.findings.forEach((f) => (m[f.category] ??= []).push(f));
    return m;
  }, [assessment]);

  if (loading) return <div className="space-y-3"><Skeleton className="h-28" /><Skeleton className="h-64" /></div>;
  if (!assessment) {
    return (
      <Panel>
        <EmptyState
          title="No AI assessment yet"
          body={canRun ? "Run the assessment to check this request against the procurement policies. It produces findings with evidence for you to review; it never approves or rejects." : "A reviewer needs to run the assessment before a decision can be made."}
          action={canRun ? <Button variant="primary" loading={running} onClick={onRun} icon={<Sparkles className="h-4 w-4" />}>Run AI assessment</Button> : undefined}
        />
      </Panel>
    );
  }

  const counts = CATEGORY_ORDER.map((c) => ({ c, n: grouped[c]?.length ?? 0 }));
  const latest = versions[0]?.id === assessment.id;
  return (
    <div className="space-y-5">
      <Panel flush>
        <div className="space-y-4 p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex flex-wrap items-center gap-2">
              <ComplianceBadge status={assessment.compliance_status} /><RiskBadge risk={assessment.overall_risk} />
              {assessment.is_mock ? <MockBadge /> : <Badge tone="quiet">{assessment.provider} {assessment.model}</Badge>}
            </div>
            <div className="flex items-center gap-2">
              {versions.length > 1 && (
                <Select aria-label="Assessment version" value={selected} onChange={(e) => onSelect(e.target.value)} className="h-8 w-auto text-[13px]">
                  {versions.map((v) => <option key={v.id} value={v.id}>Version {v.version}{v.id === versions[0].id ? " (latest)" : ""}</option>)}
                </Select>
              )}
              {canRun && <Button size="sm" variant="outline" loading={running} onClick={onRun} icon={<Sparkles className="h-3.5 w-3.5" />}>Run again</Button>}
            </div>
          </div>
          <p className="max-w-3xl font-display text-[19px] leading-snug text-text">{assessment.summary}</p>
          {!latest && <div className="rounded-control border border-amber/30 bg-amber/10 px-3 py-2 text-[13px] text-amber">You are viewing an older version. Decisions are always recorded against the latest assessment.</div>}
          <div className="flex flex-wrap gap-2" role="group" aria-label="Filter findings">
            {counts.map(({ c, n }) => (
              <button key={c} disabled={n === 0} onClick={() => setFilter(filter === c ? null : c)} aria-pressed={filter === c}
                className={cn("flex items-center gap-2 rounded-control border px-3 py-1.5 text-[13px] transition-colors disabled:opacity-40",
                  filter === c ? "border-iris/60 bg-iris/10 text-text" : "border-line bg-ink/40 text-muted hover:border-line-strong hover:text-text")}>
                <span className={cn("h-2 w-2 rounded-full", barTone[categoryTone[c]])} aria-hidden />
                {label(c)} <span className="num font-medium text-text">{n}</span>
              </button>
            ))}
          </div>
        </div>
      </Panel>

      {CATEGORY_ORDER.filter((c) => (grouped[c]?.length ?? 0) > 0 && (!filter || filter === c)).map((c) => (
        <Panel key={c} title={<span className="flex items-center gap-2"><CategoryBadge category={c} />{sectionTitle[c]} <span className="num font-normal text-muted">{grouped[c].length}</span></span>} description={sectionHelp[c]} flush>
          <ul>{grouped[c].map((f) => <FindingRow key={f.id} f={f} />)}</ul>
        </Panel>
      ))}

      {(assessment.next_steps.length > 0 || assessment.financial_risks.length > 0) && (
        <div className="grid gap-5 lg:grid-cols-2">
          <Panel title="Suggested next steps" description="Generated from the findings. They are suggestions, not instructions.">
            <ol className="space-y-3">
              {assessment.next_steps.map((s, i) => (
                <li key={i} className="text-[13.5px]">
                  <div className="text-text">{s.action}</div>
                  <div className="mt-0.5 text-[12.5px] text-faint">{s.clause_ref ? <>Based on {s.clause_ref}</> : <>From {s.reason}</>}</div>
                </li>
              ))}
            </ol>
          </Panel>
          <Panel title="Financial exposure" description="Figures taken directly from the request and its quotations.">
            {assessment.financial_risks.length === 0 ? <p className="text-[13.5px] text-muted">Nothing notable.</p> : (
              <ul className="space-y-3">{assessment.financial_risks.map((r, i) => <li key={i} className="text-[13.5px]"><span className="font-medium">{label(r.type)}</span><div className="text-muted">{r.detail}</div></li>)}</ul>
            )}
          </Panel>
        </div>
      )}

      <Panel title="How this assessment was produced">
        <dl className="grid gap-x-8 gap-y-2.5 text-[13.5px] sm:grid-cols-2">
          <div><dt className="text-muted">Created</dt><dd>{dateTime(assessment.created_at)} ({ago(assessment.created_at)})</dd></div>
          <div><dt className="text-muted">Provider and model</dt><dd>{assessment.provider ?? "Rules only"} {assessment.model ?? ""}{assessment.is_mock && " (mock heuristics, not an AI model)"}</dd></div>
          <div><dt className="text-muted">Prompt</dt><dd>{Object.entries(assessment.prompt_versions).filter(([k]) => k !== "sha256").map(([, v]) => v).join(", ") || "No model prompt was used"}</dd></div>
          <div><dt className="text-muted">Time and tokens</dt><dd>{ms(assessment.latency_ms)}; {compactNumber(assessment.tokens.input)} in, {compactNumber(assessment.tokens.output)} out{assessment.est_cost_usd !== null && `; about $${assessment.est_cost_usd.toFixed(4)}`}</dd></div>
          <div className="sm:col-span-2"><dt className="text-muted">Confidence</dt><dd>{percent(assessment.confidence)}. {assessment.confidence_note}.</dd></div>
        </dl>
      </Panel>
    </div>
  );
}
