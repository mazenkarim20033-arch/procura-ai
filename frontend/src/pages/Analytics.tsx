import { useState } from "react";
import { MockBadge } from "../components/badges";
import { BarList, CATEGORY_COLORS, COLORS, Donut, RISK_COLORS } from "../components/charts";
import { Badge, ErrorState, Field, Input, PageHeader, Panel, Skeleton, Stat, tableClasses as t } from "../components/ui";
import { cn } from "../lib/cn";
import { compactNumber, hours, label, ms, percent } from "../lib/format";
import { useOverview } from "../lib/queries";

export function Analytics() {
  const [since, setSince] = useState("");
  const [until, setUntil] = useState("");
  const [excludeMock, setExcludeMock] = useState(false);
  const ov = useOverview({ since: since || undefined, until: until || undefined, exclude_mock: excludeMock });

  return (
    <>
      <PageHeader title="Compliance analytics" subtitle="Computed live from the database. Each number says how many cases it rests on." />
      <Panel className="mb-5">
        <div className="flex flex-wrap items-end gap-4">
          <Field label="Submitted from">{(id) => <Input id={id} type="date" value={since} onChange={(e) => setSince(e.target.value)} className="w-[170px]" />}</Field>
          <Field label="Submitted until">{(id) => <Input id={id} type="date" value={until} onChange={(e) => setUntil(e.target.value)} className="w-[170px]" />}</Field>
          <label className="flex items-center gap-2 pb-2 text-[13.5px]"><input type="checkbox" checked={excludeMock} onChange={(e) => setExcludeMock(e.target.checked)} className="h-4 w-4 accent-[rgb(143_123_255)]" />Leave out mock AI assessments</label>
        </div>
      </Panel>

      {ov.isLoading ? <div className="space-y-5"><Skeleton className="h-40" /><Skeleton className="h-64" /></div> : ov.error || !ov.data ? <ErrorState error={ov.error} retry={() => ov.refetch()} /> : (() => {
        const d = ov.data;
        const status = Object.entries(d.assessments.latest_status_mix).map(([k, v]) => ({ label: label(k), value: v, color: k === "no_issues_found" ? COLORS.ok : k === "issues_found" ? COLORS.amber : k === "needs_information" ? COLORS.cobalt : COLORS.quiet }));
        const risk = ["low", "medium", "high", "critical"].map((k) => ({ name: label(k), value: d.assessments.latest_risk_distribution[k] ?? 0, color: RISK_COLORS[k] })).filter((x) => x.value);
        const bySource: Record<string, { rule: number; llm: number }> = {};
        d.findings.by_category_and_source.forEach((f) => { (bySource[f.category] ??= { rule: 0, llm: 0 })[f.source === "llm" ? "llm" : "rule"] += f.n; });
        const findings = Object.entries(bySource).map(([c, v]) => ({ label: label(c), value: v.rule + v.llm, color: CATEGORY_COLORS[c], note: v.llm ? `${v.llm} from a model` : undefined }));
        const agree = d.decisions.ai_agreement, dec = d.decisions;
        return (
          <div className="space-y-5">
            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="What the assessments found" description={`Latest assessment of ${d.assessments.requests_with_assessment} requests.`}><BarList rows={status} /></Panel>
              <Panel title="Risk rating"><Donut data={risk} centerLabel="assessed" /></Panel>
            </div>
            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="Findings by kind" description="Rule findings are deterministic; model findings are only ever potential or inconclusive."><BarList rows={findings} /></Panel>
              <Panel title="Most frequent problems" flush>
                {d.findings.top_rules.length === 0 ? <p className="p-5 text-[13.5px] text-muted">No findings yet.</p> : (
                  <table className={t.table}><thead><tr><th className={t.th}>Check</th><th className={cn(t.th, "text-right")}>Times</th></tr></thead>
                    <tbody>{d.findings.top_rules.slice(0, 8).map((r) => <tr key={r.rule_code + r.category} className={t.row}><td className={t.td}><div>{r.example_title}</div><div className="mt-0.5 flex items-center gap-2 text-[12px] text-faint">{r.rule_code}<Badge tone={r.category === "confirmed_violation" ? "danger" : r.category === "potential_violation" ? "amber" : r.category === "missing_information" ? "cobalt" : "quiet"}>{label(r.category)}</Badge></div></td><td className={cn(t.td, "num text-right font-medium")}>{r.n}</td></tr>)}</tbody></table>
                )}
              </Panel>
            </div>

            <Panel title="People and the AI" description={d.definitions.ai_agreement}>
              <div className="grid gap-8 lg:grid-cols-[1fr_1.2fr]">
                <div className="space-y-5">
                  <Stat label="Decisions that matched the AI signal" value={percent(agree.agreement_rate)} hint={`${agree.decisions_with_clear_signal} decisions with a clear signal, ${dec.total} in total`} />
                  <Stat label="Reviewers agreeing with individual findings" value={percent(dec.finding_reviews.agree_rate)} hint={`${dec.finding_reviews.total} verdicts recorded`} />
                </div>
                <BarList rows={Object.entries(agree.buckets).map(([k, v]) => ({ label: label(k), value: v, color: k === "agreed_with_ai" ? COLORS.ok : k === "no_clear_ai_signal" ? COLORS.neutral : COLORS.amber }))} />
              </div>
            </Panel>

            <div className="grid gap-5 lg:grid-cols-2">
              <Panel title="How long requests take" description={d.definitions.processing_time}>
                <div className="grid grid-cols-2 gap-6">
                  <div><div className="mb-2 text-[13px] font-medium">To first assessment</div><dl className="space-y-1 text-[13.5px]"><div className="flex justify-between"><dt className="text-muted">Median</dt><dd className="num">{hours(d.decisions.hours_to_first_assessment.median_hours)}</dd></div><div className="flex justify-between"><dt className="text-muted">90th percentile</dt><dd className="num">{hours(d.decisions.hours_to_first_assessment.p90_hours)}</dd></div><div className="flex justify-between"><dt className="text-muted">Requests</dt><dd className="num">{d.decisions.hours_to_first_assessment.n}</dd></div></dl></div>
                  <div><div className="mb-2 text-[13px] font-medium">To first decision</div><dl className="space-y-1 text-[13.5px]"><div className="flex justify-between"><dt className="text-muted">Median</dt><dd className="num">{hours(d.decisions.hours_to_first_decision.median_hours)}</dd></div><div className="flex justify-between"><dt className="text-muted">90th percentile</dt><dd className="num">{hours(d.decisions.hours_to_first_decision.p90_hours)}</dd></div><div className="flex justify-between"><dt className="text-muted">Requests</dt><dd className="num">{d.decisions.hours_to_first_decision.n}</dd></div></dl></div>
                </div>
              </Panel>
              <Panel title="Decisions" description="What people decided."><BarList rows={Object.entries(dec.by_action).map(([k, v]) => ({ label: label(k), value: v, color: k === "approve" ? COLORS.ok : k === "reject" ? COLORS.danger : COLORS.amber }))} /></Panel>
            </div>

            <Panel title="AI usage" description="By provider and model. Mock rows are deterministic keyword rules, so their speed says nothing about a real model." flush>
              {d.assessments.by_provider.length === 0 ? <p className="p-5 text-[13.5px] text-muted">No assessments yet.</p> : (
                <div className={t.wrap}><table className={t.table}>
                  <thead><tr><th className={t.th}>Provider</th><th className={cn(t.th, "text-right")}>Assessments</th><th className={cn(t.th, "text-right")}>Median</th><th className={cn(t.th, "text-right")}>Slowest 5%</th><th className={cn(t.th, "text-right")}>Tokens in</th><th className={cn(t.th, "text-right")}>Tokens out</th><th className={cn(t.th, "text-right")}>Estimated cost</th></tr></thead>
                  <tbody>{d.assessments.by_provider.map((p, i) => (
                    <tr key={i} className={t.row}><td className={t.td}><span className="font-medium">{p.provider}</span> <span className="text-muted">{p.model}</span> {p.is_mock && <MockBadge />}</td><td className={cn(t.td, "num text-right")}>{p.n}</td><td className={cn(t.td, "num text-right")}>{ms(p.p50_ms)}</td><td className={cn(t.td, "num text-right")}>{ms(p.p95_ms)}</td><td className={cn(t.td, "num text-right")}>{compactNumber(p.input_tokens)}</td><td className={cn(t.td, "num text-right")}>{compactNumber(p.output_tokens)}</td><td className={cn(t.td, "num text-right")}>{p.est_cost_usd === null ? <span className="text-faint" title="Set LLM_PRICE_IN_PER_M and LLM_PRICE_OUT_PER_M to estimate">Not configured</span> : `$${p.est_cost_usd.toFixed(4)}`}</td></tr>
                  ))}</tbody>
                </table></div>
              )}
            </Panel>

            <Panel title="How these numbers are defined" description="Read these before quoting a figure.">
              <dl className="space-y-3 text-[13.5px]">{Object.entries(d.definitions).map(([k, v]) => <div key={k}><dt className="font-medium">{label(k)}</dt><dd className="text-muted">{v}</dd></div>)}</dl>
              <p className="mt-4 text-[12.5px] text-faint">{d.basis}</p>
            </Panel>
          </div>
        );
      })()}
    </>
  );
}
