import { Badge, EmptyState, ErrorState, Panel, Skeleton, Stat, type Tone } from "../../components/ui";
import type { Intake } from "../../lib/api";
import { label, plural } from "../../lib/format";

const sev: Record<string, Tone> = { error: "danger", warning: "amber", info: "neutral" };
const KINDS: { kind: string; title: string; help: string }[] = [
  { kind: "missing", title: "Missing information", help: "Fields the request or its documents should contain." },
  { kind: "inconsistent", title: "Inconsistencies", help: "Numbers, dates or names that do not agree with each other." },
  { kind: "limitation", title: "Checks that could not run", help: "Stated openly instead of guessing." },
];

export function IntakePanel({ intake, loading, error }: { intake: Intake | undefined; loading: boolean; error: unknown }) {
  if (loading) return <Skeleton className="h-64" />;
  if (error || !intake) return <ErrorState error={error} />;
  const s = intake.summary;
  return (
    <div className="space-y-5">
      <Panel>
        <div className="grid grid-cols-2 gap-6 sm:grid-cols-4">
          <Stat label="Issues found" value={s.issues} tone={s.errors ? "danger" : undefined} hint={s.errors ? plural(s.errors, "error") : "no errors"} />
          <Stat label="Quotations attached" value={s.quotations_attached} />
          <Stat label="Possible duplicates" value={s.possible_duplicates} tone={s.possible_duplicates ? "amber" : undefined} />
          <Stat label="Split-purchase signals" value={s.split_findings} tone={s.split_findings ? "amber" : undefined} />
        </div>
        <p className="mt-4 text-[12.5px] text-faint">These are deterministic checks computed when you open this page ({intake.generated_by}). They feed the AI assessment but involve no model.</p>
      </Panel>

      {KINDS.map(({ kind, title, help }) => {
        const rows = intake.issues.filter((i) => i.kind === kind);
        if (!rows.length) return null;
        return (
          <Panel key={kind} title={title} description={help} flush>
            <ul>{rows.map((i, n) => (
              <li key={n} className="flex items-start gap-3 border-b border-line px-5 py-3 text-[13.5px] last:border-0">
                <Badge tone={sev[i.severity] ?? "neutral"}>{label(i.severity)}</Badge>
                <div className="min-w-0"><div>{i.message}</div><div className="mt-0.5 text-[12px] text-faint">{i.code}</div></div>
              </li>
            ))}</ul>
          </Panel>
        );
      })}

      {(intake.duplicates.length > 0 || intake.splits.length > 0) && (
        <Panel title="Duplicates and split purchases" description="Matching is by supplier, item meaning and timing. A repeat of the same order months later is shown for information only.">
          <ul className="space-y-3 text-[13.5px]">
            {intake.duplicates.map((d, i) => (
              <li key={i} className="flex flex-wrap items-center gap-2">
                <Badge tone={d.kind === "exact" || d.kind === "similar" ? "amber" : "neutral"}>{label(d.kind)}</Badge>
                <span className="font-medium">{d.other_request_no}</span><span className="text-muted">{d.reasons[0]}</span>
              </li>
            ))}
            {intake.splits.map((sp, i) => <li key={`s${i}`} className="flex items-start gap-2"><Badge tone={sev[sp.severity] ?? "neutral"}>{sp.code === "INT-SPLIT" ? "Possible split" : "Near a threshold"}</Badge><span className="text-muted">{sp.message}</span></li>)}
          </ul>
        </Panel>
      )}
      {intake.issues.length === 0 && intake.duplicates.length === 0 && intake.splits.length === 0 && <Panel><EmptyState title="No intake issues" body="The request is complete and consistent, and nothing looks like a duplicate or split purchase." /></Panel>}
    </div>
  );
}
