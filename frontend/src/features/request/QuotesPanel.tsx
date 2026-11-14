import { Badge, EmptyState, ErrorState, Panel, Skeleton, tableClasses as t, type Tone } from "../../components/ui";
import type { Comparison } from "../../lib/api";
import { cn } from "../../lib/cn";
import { label, money } from "../../lib/format";

const sev: Record<string, Tone> = { warning: "amber", info: "neutral" };

export function QuotesPanel({ data, loading, error }: { data: Comparison | undefined; loading: boolean; error: unknown }) {
  if (loading) return <Skeleton className="h-64" />;
  if (error || !data) return <ErrorState error={error} />;
  if (data.quotes.length === 0) return <Panel><EmptyState title="No quotations attached" body="Attach supplier quotations on the Documents tab to compare prices, terms and validity." /></Panel>;
  const labels = data.quotes.map((q) => q.label);
  const lowest = data.ranking[0]?.label;
  return (
    <div className="space-y-5">
      <Panel title="Quotations side by side" description={data.basis} flush>
        <div className={t.wrap}>
          <table className={t.table}>
            <thead><tr><th className={t.th}>Supplier</th><th className={cn(t.th, "text-right")}>Total</th><th className={t.th}>Payment terms</th><th className={cn(t.th, "text-right")}>Delivery</th><th className={cn(t.th, "text-right")}>Valid from request date</th></tr></thead>
            <tbody>
              {data.quotes.map((q) => (
                <tr key={q.label} className={t.row}>
                  <td className={t.td}><div className="font-medium">{q.vendor}</div><div className="max-w-[260px] truncate text-[12px] text-faint" title={q.label}>{q.label}</div></td>
                  <td className={cn(t.td, "num text-right")}>{money(q.total, q.currency)}{q.label === lowest && <div className="mt-0.5"><Badge tone="ok">Lowest</Badge></div>}</td>
                  <td className={t.td}>{q.payment_terms ?? "Not stated"}{q.advance_pct && Number(q.advance_pct) > 30 && <div className="mt-0.5"><Badge tone="amber">{q.advance_pct}% in advance</Badge></div>}</td>
                  <td className={cn(t.td, "num text-right")}>{q.delivery_days ? `${q.delivery_days} days` : "Not stated"}</td>
                  <td className={cn(t.td, "num text-right")}>{q.validity_days_from_request === null ? "Not stated" : <span className={q.validity_days_from_request < 30 ? "text-amber" : ""}>{q.validity_days_from_request} days</span>}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {data.notes.length > 0 && <ul className="space-y-1 border-t border-line px-5 py-3 text-[13px] text-muted">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>}
      </Panel>

      {data.item_rows.length > 0 && (
        <Panel title="Unit prices by item" description="Items are matched across quotations by meaning, not exact wording. The ratio compares each price with the median." flush>
          <div className={t.wrap}>
            <table className={t.table}>
              <thead><tr><th className={t.th}>Item</th>{data.quotes.map((q) => <th key={q.label} className={cn(t.th, "text-right")}>{q.vendor}</th>)}</tr></thead>
              <tbody>
                {data.item_rows.map((row, i) => (
                  <tr key={i} className={t.row}>
                    <td className={t.td}>{row.description}</td>
                    {labels.map((l) => {
                      const c = row.cells[l];
                      const off = c?.ratio_to_median !== undefined && Math.abs(c.ratio_to_median - 1) > 0.25;
                      return <td key={l} className={cn(t.td, "num text-right")}>{c?.unit_price ? <>{money(c.unit_price)}{c.ratio_to_median !== undefined && <div className={cn("text-[12px]", off ? "text-amber" : "text-faint")}>{c.ratio_to_median.toFixed(2)} of median</div>}</> : <span className="text-faint">Not quoted</span>}</td>;
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      )}

      {data.flags.length > 0 && (
        <Panel title="Things worth a look" description="Price and document flags from the comparison. Thresholds are heuristics, not policy values." flush>
          <ul>{data.flags.map((f, i) => <li key={i} className="flex items-start gap-3 border-b border-line px-5 py-3 text-[13.5px] last:border-0"><Badge tone={sev[f.severity] ?? "neutral"}>{label(f.severity)}</Badge><span>{f.message}</span></li>)}</ul>
        </Panel>
      )}
    </div>
  );
}
