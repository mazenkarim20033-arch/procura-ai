import { useMutation } from "@tanstack/react-query";
import { Plus, Search, Trash2 } from "lucide-react";
import { useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ComplianceBadge, RiskBadge, StatusBadge } from "../components/badges";
import { Button, Dialog, EmptyState, ErrorState, Field, Input, PageHeader, Panel, Select, Skeleton, Textarea, tableClasses as t, useToast } from "../components/ui";
import { api, ApiError, type RequestSummary } from "../lib/api";
import { cn } from "../lib/cn";
import { date, money } from "../lib/format";
import { isReviewer } from "../lib/identity";
import { useIdentity, useQueue, useRequests } from "../lib/queries";
import { useQueryClient } from "@tanstack/react-query";

const STATUSES = ["", "submitted", "assessed", "info_requested", "approved", "rejected"];
const STATUS_TEXT: Record<string, string> = { "": "All statuses", submitted: "Submitted", assessed: "Assessed", info_requested: "Information requested", approved: "Approved", rejected: "Rejected" };
const CURRENCIES = ["USD", "EUR", "EGP", "GBP"];

interface ItemDraft { description: string; quantity: string; unit_cost: string }

function NewRequest({ open, onClose }: { open: boolean; onClose: () => void }) {
  const me = useIdentity();
  const nav = useNavigate();
  const toast = useToast();
  const qc = useQueryClient();
  const [f, setF] = useState({ requester_name: me.user, department: "", supplier_name: "", currency: "USD", justification: "" });
  const [items, setItems] = useState<ItemDraft[]>([{ description: "", quantity: "1", unit_cost: "" }]);
  const total = items.reduce((s, i) => s + (Number(i.quantity) || 0) * (Number(i.unit_cost) || 0), 0);
  const valid = f.supplier_name.trim() && items.every((i) => i.description.trim() && Number(i.quantity) > 0 && i.unit_cost !== "" && Number(i.unit_cost) >= 0);

  const create = useMutation({
    mutationFn: () => api.post<RequestSummary>("/requests", {
      ...f, total_amount: total.toFixed(2), justification: f.justification || undefined, department: f.department || undefined,
      items: items.map((i) => ({ description: i.description, quantity: i.quantity, unit_cost: i.unit_cost })),
    }),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["requests"] }); qc.invalidateQueries({ queryKey: ["queue"] }); toast({ tone: "ok", title: `${r.request_no} created` }); onClose(); nav(`/requests/${r.id}`); },
    onError: (e) => toast({ tone: "danger", title: "Request not created", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const setItem = (n: number, patch: Partial<ItemDraft>) => setItems(items.map((it, i) => (i === n ? { ...it, ...patch } : it)));

  return (
    <Dialog open={open} onClose={onClose} wide title="New purchase request" description="Incomplete requests are accepted. The intake checks list what is missing."
      footer={<><Button variant="quiet" onClick={onClose}>Cancel</Button><Button variant="primary" disabled={!valid} loading={create.isPending} onClick={() => create.mutate()}>Create request</Button></>}>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Your name">{(id) => <Input id={id} value={f.requester_name} onChange={(e) => setF({ ...f, requester_name: e.target.value })} />}</Field>
        <Field label="Department">{(id) => <Input id={id} value={f.department} onChange={(e) => setF({ ...f, department: e.target.value })} placeholder="Finance" />}</Field>
        <Field label="Supplier">{(id) => <Input id={id} value={f.supplier_name} onChange={(e) => setF({ ...f, supplier_name: e.target.value })} placeholder="Full legal name" />}</Field>
        <Field label="Currency">{(id) => <Select id={id} value={f.currency} onChange={(e) => setF({ ...f, currency: e.target.value })}>{CURRENCIES.map((c) => <option key={c}>{c}</option>)}</Select>}</Field>
      </div>
      <div className="mt-4"><Field label="Business justification">{(id) => <Textarea id={id} value={f.justification} onChange={(e) => setF({ ...f, justification: e.target.value })} placeholder="Why this purchase is needed" />}</Field></div>
      <fieldset className="mt-5">
        <legend className="mb-2 text-[13px] font-medium">Items</legend>
        <div className="space-y-2">
          {items.map((it, n) => (
            <div key={n} className="grid grid-cols-[1fr_72px_110px_auto] items-center gap-2">
              <Input aria-label={`Item ${n + 1} description`} placeholder="Description" value={it.description} onChange={(e) => setItem(n, { description: e.target.value })} />
              <Input aria-label={`Item ${n + 1} quantity`} type="number" min="0" step="any" value={it.quantity} onChange={(e) => setItem(n, { quantity: e.target.value })} />
              <Input aria-label={`Item ${n + 1} unit cost`} type="number" min="0" step="any" placeholder="Unit cost" value={it.unit_cost} onChange={(e) => setItem(n, { unit_cost: e.target.value })} />
              <button type="button" aria-label={`Remove item ${n + 1}`} disabled={items.length === 1} onClick={() => setItems(items.filter((_, i) => i !== n))} className="rounded-control p-2 text-muted hover:bg-raised hover:text-danger disabled:opacity-30"><Trash2 className="h-4 w-4" /></button>
            </div>
          ))}
        </div>
        <div className="mt-3 flex items-center justify-between">
          <Button size="sm" variant="quiet" icon={<Plus className="h-3.5 w-3.5" />} onClick={() => setItems([...items, { description: "", quantity: "1", unit_cost: "" }])}>Add item</Button>
          <div className="text-[13.5px] text-muted">Estimated total <span className="num ml-1 text-[16px] font-medium text-text">{money(total, f.currency)}</span></div>
        </div>
      </fieldset>
    </Dialog>
  );
}

export function Requests() {
  const me = useIdentity();
  const nav = useNavigate();
  const [status, setStatus] = useState("");
  const [q, setQ] = useState("");
  const [open, setOpen] = useState(false);
  const reqs = useRequests(status || undefined);
  const queue = useQueue("submitted,assessed,info_requested");
  const ai = useMemo(() => new Map((queue.data ?? []).map((x) => [x.id, x.latest_assessment])), [queue.data]);
  const rows = useMemo(() => {
    const needle = q.trim().toLowerCase();
    return (reqs.data ?? []).filter((r) => !needle || [r.request_no, r.supplier_name, r.requester_name, r.department].some((v) => v?.toLowerCase().includes(needle)));
  }, [reqs.data, q]);

  return (
    <>
      <PageHeader title="Purchase requests" subtitle="Every request, its AI assessment and where it stands."
        actions={<Button variant="primary" icon={<Plus className="h-4 w-4" />} onClick={() => setOpen(true)}>New request</Button>} />
      <Panel flush>
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <div className="relative min-w-[220px] flex-1 sm:max-w-sm">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-faint" aria-hidden />
            <Input aria-label="Search requests" placeholder="Search by number, supplier or requester" value={q} onChange={(e) => setQ(e.target.value)} className="pl-9" />
          </div>
          <Select aria-label="Filter by status" value={status} onChange={(e) => setStatus(e.target.value)} className="w-auto">{STATUSES.map((s) => <option key={s} value={s}>{STATUS_TEXT[s]}</option>)}</Select>
          <span className="num ml-auto text-[13px] text-muted">{rows.length} shown</span>
        </div>
        {reqs.isLoading ? <div className="space-y-2 p-5"><Skeleton className="h-9" /><Skeleton className="h-9" /><Skeleton className="h-9" /></div>
          : reqs.error ? <div className="p-5"><ErrorState error={reqs.error} retry={() => reqs.refetch()} /></div>
          : rows.length === 0 ? <EmptyState title="No requests match" body={q || status ? "Try clearing the search or the status filter." : "Create the first purchase request to get started."} />
          : (
            <div className={t.wrap}>
              <table className={t.table}>
                <thead><tr><th className={t.th}>Request</th><th className={t.th}>Requester</th><th className={cn(t.th, "text-right")}>Amount</th><th className={t.th}>Status</th>{isReviewer(me) && <th className={t.th}>AI assessment</th>}<th className={t.th}>Submitted</th></tr></thead>
                <tbody>
                  {rows.map((r) => {
                    const a = ai.get(r.id);
                    return (
                      <tr key={r.id} className={cn(t.row, "cursor-pointer")} onClick={() => nav(`/requests/${r.id}`)}>
                        <td className={t.td}><Link to={`/requests/${r.id}`} onClick={(e) => e.stopPropagation()} className="whitespace-nowrap font-medium hover:text-[#b4a8ff]">{r.request_no}</Link><div className="max-w-[260px] truncate text-[12.5px] text-muted">{r.supplier_name ?? "No supplier"}</div></td>
                        <td className={t.td}>{r.requester_name ?? "Unknown"}<div className="text-[12.5px] text-muted">{r.department ?? "No department"}</div></td>
                        <td className={cn(t.td, "num text-right")}>{money(r.total_amount, r.currency)}</td>
                        <td className={t.td}><StatusBadge status={r.status} /></td>
                        {isReviewer(me) && <td className={t.td}>{a ? <div className="flex flex-wrap gap-1.5"><RiskBadge risk={a.risk} /><ComplianceBadge status={a.status} /></div> : queue.isLoading ? <Skeleton className="h-5 w-28" /> : <span className="text-faint">{r.status === "approved" || r.status === "rejected" ? "Decided" : "Not assessed"}</span>}</td>}
                        <td className={cn(t.td, "text-muted")}>{date(r.submitted_at)}</td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
      </Panel>
      <NewRequest open={open} onClose={() => setOpen(false)} />
    </>
  );
}
