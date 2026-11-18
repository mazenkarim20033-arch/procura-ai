import { useMutation } from "@tanstack/react-query";
import { CheckCircle2, ShieldAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { ActorBadge } from "../components/badges";
import { Button, EmptyState, ErrorState, Input, PageHeader, Panel, Select, Skeleton, tableClasses as t, useToast } from "../components/ui";
import { api, ApiError, type AuditEntry, type AuditVerify } from "../lib/api";
import { cn } from "../lib/cn";
import { dateTime, label } from "../lib/format";
import { useAudit } from "../lib/queries";

export function Audit() {
  const [entityType, setEntityType] = useState("");
  const [action, setAction] = useState("");
  const [actor, setActor] = useState("");
  const [extra, setExtra] = useState<AuditEntry[]>([]);
  const [before, setBefore] = useState<number | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const toast = useToast();
  const filters = { entity_type: entityType || undefined, action: action.trim() || undefined, actor_type: actor || undefined };
  const first = useAudit(filters);
  const older = useAudit({ ...filters, before_id: before ? String(before) : undefined });
  useEffect(() => { setExtra([]); setBefore(null); }, [entityType, action, actor]);
  useEffect(() => { if (before && older.data) setExtra((x) => (x.some((e) => e.id === older.data!.entries[0]?.id) ? x : [...x, ...older.data!.entries])); }, [older.data, before]);

  const verify = useMutation({
    mutationFn: () => api.get<AuditVerify>("/audit/verify"),
    onError: (e) => toast({ tone: "danger", title: "Verification failed", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const entries = [...(first.data?.entries ?? []), ...extra];
  const nextBefore = extra.length ? older.data?.next_before_id ?? null : first.data?.next_before_id ?? null;
  const v = verify.data;

  return (
    <>
      <PageHeader title="Audit history" subtitle="Every action in the system, in order. Each entry is chained to the one before it, so edits are detectable."
        actions={<Button variant="primary" loading={verify.isPending} onClick={() => verify.mutate()}>Verify the chain</Button>} />
      {v && (
        <div role="status" className={cn("reveal mb-5 flex items-start gap-3 rounded-panel border p-4 text-[13.5px]", v.ok ? "border-ok/30 bg-ok/5" : "border-danger/40 bg-danger/10")}>
          {v.ok ? <CheckCircle2 className="mt-0.5 h-5 w-5 shrink-0 text-ok" /> : <ShieldAlert className="mt-0.5 h-5 w-5 shrink-0 text-danger" />}
          <div className="min-w-0">
            <div className="font-medium">{v.ok ? (v.snapshot ? `The chain was intact when this snapshot was recorded: ${v.entries_checked} entries recomputed and matched at that time.` : `The chain is intact: ${v.entries_checked} entries recomputed and matched.`) : `The chain is broken at entry ${v.first_bad_id}.`}</div>
            {v.ok && v.head_hash && <div className="mt-1 break-all text-muted">Latest hash <span className="font-mono text-[12px]">{v.head_hash}</span></div>}
            {v.snapshot ? <p className="mt-1 text-[12.5px] text-faint">Recorded {dateTime(v.verified_at)}. The running app recomputes the whole chain every time you click; this recorded demo replays that saved result.</p> : v.scope && <p className="mt-1 text-[12.5px] text-faint">{v.scope}</p>}
          </div>
        </div>
      )}
      <Panel flush>
        <div className="flex flex-wrap items-center gap-3 border-b border-line px-5 py-3">
          <Select aria-label="Filter by subject" value={entityType} onChange={(e) => setEntityType(e.target.value)} className="w-auto"><option value="">All subjects</option><option value="request">Requests</option><option value="document">Documents</option><option value="vendor">Vendors</option><option value="setting">Settings</option><option value="chunk">Policy index</option></Select>
          <Select aria-label="Filter by actor" value={actor} onChange={(e) => setActor(e.target.value)} className="w-auto"><option value="">Anyone</option><option value="user">People</option><option value="ai">AI</option><option value="system">System</option></Select>
          <Input aria-label="Filter by action" placeholder="Action, e.g. decision.recorded" value={action} onChange={(e) => setAction(e.target.value)} className="w-[230px]" />
          <span className="num ml-auto text-[13px] text-muted">{entries.length} shown</span>
        </div>
        {first.isLoading ? <div className="space-y-2 p-5"><Skeleton className="h-9" /><Skeleton className="h-9" /></div> : first.error ? <div className="p-5"><ErrorState error={first.error} retry={() => first.refetch()} /></div> : entries.length === 0 ? <EmptyState title="No entries match" body="Clear the filters to see the whole trail." /> : (
          <div className={t.wrap}>
            <table className={t.table}>
              <thead><tr><th className={t.th}>When</th><th className={t.th}>Who</th><th className={t.th}>What happened</th><th className={t.th}>Subject</th><th className={t.th}>Hash</th></tr></thead>
              <tbody>{entries.map((e) => (
                <>
                  <tr key={e.id} className={cn(t.row, "cursor-pointer")} onClick={() => setExpanded(expanded === e.id ? null : e.id)} aria-expanded={expanded === e.id}>
                    <td className={cn(t.td, "whitespace-nowrap text-muted")}>{dateTime(e.ts)}</td>
                    <td className={t.td}><div className="flex items-center gap-2"><ActorBadge type={e.actor_type} /><span className="max-w-[180px] truncate text-muted">{e.actor}</span></div></td>
                    <td className={t.td}>{label(e.action.replace(".", " "))}<div className="text-[12px] text-faint">{e.action}</div></td>
                    <td className={t.td}>{label(e.entity_type)}{e.entity_id && <div className="max-w-[140px] truncate font-mono text-[12px] text-faint">{e.entity_id}</div>}</td>
                    <td className={cn(t.td, "font-mono text-[12px] text-faint")}>{e.hash}</td>
                  </tr>
                  {expanded === e.id && <tr key={`${e.id}x`}><td colSpan={5} className="border-b border-line bg-ink/60 px-5 py-3"><pre className="reveal max-h-64 overflow-auto whitespace-pre-wrap font-mono text-[12px] text-muted">{JSON.stringify(e.payload, null, 2)}</pre><div className="mt-1 text-[12px] text-faint">Entry {e.id}, chained from {e.prev_hash}</div></td></tr>}
                </>
              ))}</tbody>
            </table>
          </div>
        )}
        {nextBefore && <div className="border-t border-line p-3 text-center"><Button variant="quiet" loading={older.isFetching && !!before} onClick={() => setBefore(nextBefore)}>Show older entries</Button></div>}
      </Panel>
    </>
  );
}
