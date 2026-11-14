import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BarList } from "../components/charts";
import { Badge, Button, Dialog, Drawer, EmptyState, ErrorState, Field, PageHeader, Panel, Select, Skeleton, Stat, tableClasses as t, useToast } from "../components/ui";
import { api, ApiError } from "../lib/api";
import { cn } from "../lib/cn";
import { date, money } from "../lib/format";
import { useIdentity, useOverview, useVendor, useVendors } from "../lib/queries";
import { isReviewer } from "../lib/identity";

const sev = { warning: "amber", info: "neutral" } as const;

function MergeDialog({ id, name, onClose }: { id: string; name: string; onClose: () => void }) {
  const vendors = useVendors();
  const toast = useToast();
  const qc = useQueryClient();
  const [into, setInto] = useState("");
  const merge = useMutation({
    mutationFn: () => api.post(`/vendors/${id}/merge`, { into_vendor_id: into }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["vendors"] }); qc.invalidateQueries({ queryKey: ["vendor"] }); toast({ tone: "ok", title: "Vendors merged" }); onClose(); },
    onError: (e) => toast({ tone: "danger", title: "Could not merge", body: e instanceof ApiError ? e.detail : undefined }),
  });
  return (
    <Dialog open onClose={onClose} title={`Merge ${name}`} description="Use this when two records are the same company. Its quotations, requests and names move to the vendor you choose, and this record is removed. It cannot be undone."
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="danger" disabled={!into} loading={merge.isPending} onClick={() => merge.mutate()}>Merge vendors</Button></>}>
      <Field label="Keep this vendor">{(f) => <Select id={f} value={into} onChange={(e) => setInto(e.target.value)}><option value="">Choose a vendor</option>{(vendors.data ?? []).filter((v) => v.id !== id).map((v) => <option key={v.id} value={v.id}>{v.name}</option>)}</Select>}</Field>
    </Dialog>
  );
}

function VendorDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const v = useVendor(id);
  const me = useIdentity();
  const [merging, setMerging] = useState(false);
  const d = v.data;
  return (
    <Drawer open={!!id} onClose={onClose} title={d?.name ?? "Vendor"} subtitle={d && "Built only from the documents that were uploaded"}>
      {v.isLoading && <Skeleton className="h-64" />}
      {v.error && <ErrorState error={v.error} />}
      {d && (
        <div className="space-y-6">
          <dl className="grid grid-cols-[110px_1fr] gap-x-4 gap-y-2 text-[13.5px]">
            <dt className="text-muted">Tax ID</dt><dd>{d.tax_id ?? <span className="text-amber">Not on any document</span>}</dd>
            <dt className="text-muted">Country</dt><dd>{d.country ?? <span className="text-faint">Not stated</span>}</dd>
            <dt className="text-muted">Email</dt><dd>{d.contact.email ?? <span className="text-faint">Not stated</span>}</dd>
            <dt className="text-muted">Phone</dt><dd>{d.contact.phone ?? <span className="text-faint">Not stated</span>}</dd>
            <dt className="text-muted">Address</dt><dd>{d.contact.address ?? <span className="text-faint">Not stated</span>}</dd>
            {d.aliases.length > 0 && <><dt className="text-muted">Also written as</dt><dd>{d.aliases.join(", ")}</dd></>}
          </dl>
          {d.gaps.length > 0 && (
            <section>
              <h3 className="mb-2 font-sans text-[14px] font-semibold tracking-normal">Gaps and conflicts</h3>
              <ul className="space-y-1.5">{d.gaps.map((g, i) => <li key={i} className="flex gap-2 rounded-control border border-line bg-ink/50 px-3 py-2 text-[13px]"><Badge tone={sev[g.severity as keyof typeof sev] ?? "neutral"}>{g.code === "VND-CONFLICT" ? "Conflict" : g.code === "VND-ALIAS-REVIEW" ? "Check" : "Missing"}</Badge><span>{g.message}</span></li>)}</ul>
            </section>
          )}
          <section>
            <h3 className="mb-2 font-sans text-[14px] font-semibold tracking-normal">Quotations</h3>
            {d.quotations.length === 0 ? <p className="text-[13.5px] text-muted">No quotations from this vendor yet.</p> : (
              <ul className="divide-y divide-line rounded-control border border-line">{d.quotations.map((q) => (
                <li key={q.id} className="flex flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2.5 text-[13px]">
                  <span className="font-medium">{q.quote_no ?? "No number"}</span><span className="num text-muted">{date(q.issue_date)}</span>
                  <span className="num ml-auto">{money(q.total, q.currency)}</span>
                  {q.request_id && <Link to={`/requests/${q.request_id}`} className="text-[#a89bff] hover:text-[#c3b9ff]">Open request</Link>}
                </li>
              ))}</ul>
            )}
          </section>
          <p className="text-[12.5px] text-faint">{d.basis}</p>
          {me.role === "admin" && <Button variant="outline" onClick={() => setMerging(true)}>Merge into another vendor</Button>}
          {merging && <MergeDialog id={d.id} name={d.name} onClose={() => { setMerging(false); onClose(); }} />}
        </div>
      )}
    </Drawer>
  );
}

export function Vendors() {
  const me = useIdentity();
  const [params, setParams] = useSearchParams();
  const vendors = useVendors();
  const ov = useOverview({});
  const cmp = ov.data?.vendors.quotation_comparison;
  return (
    <>
      <PageHeader title="Vendors" subtitle="Suppliers as they appear in the uploaded documents, with what is missing and what disagrees. No external verification is performed." />
      {isReviewer(me) && ov.data && (
        <Panel className="mb-5">
          <div className="grid grid-cols-2 gap-6 md:grid-cols-4">
            <Stat label="Vendors" value={ov.data.vendors.vendors} hint={`${ov.data.vendors.quotations} quotations`} />
            <Stat label="Without a tax ID" value={ov.data.vendors.without_tax_id} tone={ov.data.vendors.without_tax_id ? "amber" : undefined} />
            <Stat label="With conflicting details" value={ov.data.vendors.with_conflicts} tone={ov.data.vendors.with_conflicts ? "danger" : undefined} />
            <Stat label="Typical price spread" value={cmp?.median_spread_pct != null ? `${cmp.median_spread_pct}%` : "n/a"} hint={cmp ? `across ${cmp.requests_compared} compared requests` : undefined} />
          </div>
        </Panel>
      )}
      <div className="grid gap-5 xl:grid-cols-[1fr_340px]">
        <Panel flush>
          {vendors.isLoading ? <div className="space-y-2 p-5"><Skeleton className="h-9" /><Skeleton className="h-9" /></div> : vendors.error ? <div className="p-5"><ErrorState error={vendors.error} /></div> : (vendors.data ?? []).length === 0 ? <EmptyState title="No vendors yet" body="Vendors appear when quotations, invoices or contracts are uploaded." /> : (
            <div className={t.wrap}>
              <table className={t.table}>
                <thead><tr><th className={t.th}>Vendor</th><th className={t.th}>Country</th><th className={t.th}>Tax ID</th><th className={cn(t.th, "text-right")}>Quotations</th><th className={cn(t.th, "text-right")}>Gaps</th></tr></thead>
                <tbody>{vendors.data!.map((v) => (
                  <tr key={v.id} className={cn(t.row, "cursor-pointer")} onClick={() => setParams({ open: v.id })}>
                    <td className={cn(t.td, "font-medium")}>{v.name}</td><td className={t.td}>{v.country ?? <span className="text-faint">Not stated</span>}</td>
                    <td className={t.td}>{v.tax_id ?? <Badge tone="amber">Missing</Badge>}</td><td className={cn(t.td, "num text-right")}>{v.quotations}</td>
                    <td className={cn(t.td, "num text-right")}>{v.gaps ? <Badge tone="amber">{v.gaps}</Badge> : <span className="text-faint">0</span>}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
        </Panel>
        {cmp && cmp.lowest_bidder_wins.length > 0 && (
          <Panel title="Who quotes lowest" description="Share of compared requests where the vendor had the lowest total.">
            <BarList rows={cmp.lowest_bidder_wins.map((w) => ({ label: w.vendor, value: w.wins, note: `of ${w.bids}` }))} />
            <p className="mt-4 text-[12.5px] text-faint">The requested supplier was the lowest quote in {cmp.chosen_vs_lowest.chosen_was_lowest} of {cmp.chosen_vs_lowest.requests_with_chosen_quote} requests{cmp.chosen_vs_lowest.avg_premium_pct_when_not_lowest != null ? `; otherwise about ${cmp.chosen_vs_lowest.avg_premium_pct_when_not_lowest}% above the lowest.` : "."}</p>
          </Panel>
        )}
      </div>
      <VendorDrawer id={params.get("open")} onClose={() => setParams({})} />
    </>
  );
}
