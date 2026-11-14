import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Search } from "lucide-react";
import { useState } from "react";
import { Badge, Button, EmptyState, ErrorState, Field, Input, PageHeader, Panel, Skeleton, useToast } from "../components/ui";
import { api, ApiError, type PolicySearch } from "../lib/api";
import { cn } from "../lib/cn";
import { date, label, ms } from "../lib/format";
import { useIdentity, usePolicies, usePolicy } from "../lib/queries";

function Ask() {
  const [query, setQuery] = useState("");
  const toast = useToast();
  const search = useMutation({
    mutationFn: () => api.post<PolicySearch>("/policies/search", { query, k: 5 }),
    onError: (e) => toast({ tone: "danger", title: "Search failed", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const r = search.data;
  return (
    <Panel title="Ask the policies" description="This is the retrieval step the AI assessment uses. It shows which clauses come back and how close each one is, so you can see what the AI was given.">
      <form onSubmit={(e) => { e.preventDefault(); if (query.trim().length >= 3) search.mutate(); }} className="flex flex-wrap items-end gap-3">
        <div className="min-w-[260px] flex-1"><Field label="Question">{(id) => <Input id={id} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="How many quotations does a USD 12,000 purchase need?" />}</Field></div>
        <Button variant="primary" type="submit" loading={search.isPending} disabled={query.trim().length < 3} icon={<Search className="h-4 w-4" />}>Search policies</Button>
      </form>
      {r && (
        <div className="reveal mt-5 space-y-4">
          <div className="flex flex-wrap items-center gap-3 text-[13px]">
            <Badge tone={r.relevance.relevant ? "ok" : "amber"}>{r.relevance.relevant ? "Relevant clauses found" : "Nothing relevant enough"}</Badge>
            <span className="text-muted">Best similarity {r.relevance.best_similarity?.toFixed(2) ?? "n/a"} against a cut-off of {r.relevance.threshold}. {r.relevance.reason !== "ok" && r.relevance.reason}</span>
            <span className="ml-auto text-faint">{r.embedding_model.split("/").pop()}, {ms(Object.values(r.timings_ms).reduce((a, b) => a + b, 0))}</span>
          </div>
          {!r.relevance.relevant && <p className="rounded-control border border-amber/30 bg-amber/10 px-3 py-2 text-[13px] text-amber">When nothing clears the cut-off, an assessment reports the topic as inconclusive instead of reasoning over unrelated text.</p>}
          <ol className="space-y-3">
            {r.hits.map((h) => (
              <li key={h.chunk_id} className="rounded-control border border-line bg-ink/50 p-3.5">
                <div className="mb-1.5 flex items-center gap-3 text-[12.5px] text-muted"><Badge tone="quiet">{h.policy_code}</Badge><span>{h.section_path.split(">").slice(1).join(" / ").trim()}</span>
                  <span className="num ml-auto" title="Cosine similarity">{h.dense_similarity?.toFixed(2) ?? "n/a"}</span>
                  <span className="h-1.5 w-16 overflow-hidden rounded-full bg-raised" aria-hidden><span className="block h-full rounded-full bg-gradient-to-r from-iris to-cobalt" style={{ width: `${Math.max(2, Math.min(100, (h.dense_similarity ?? 0) * 100))}%` }} /></span></div>
                <p className="font-display text-[15.5px] leading-snug">{h.text}</p>
              </li>
            ))}
          </ol>
        </div>
      )}
    </Panel>
  );
}

function Clauses({ id }: { id: string }) {
  const p = usePolicy(id);
  if (p.isLoading) return <Skeleton className="h-48" />;
  if (p.error || !p.data) return <ErrorState error={p.error} />;
  return (
    <Panel title={`${p.data.code}: ${p.data.title}`} description={`Version ${p.data.version}, in force from ${date(p.data.effective_from)}${p.data.effective_to ? ` to ${date(p.data.effective_to)}` : ""}.`} flush>
      <ol>{p.data.clauses.map((c) => (
        <li key={c.id} className="flex gap-4 border-b border-line px-5 py-3.5 last:border-0">
          <span className="num w-12 shrink-0 pt-0.5 text-[13px] font-medium text-[#a89bff]">{c.section_path.split(">").pop()?.trim()}</span>
          <div className="min-w-0"><p className="max-w-prose text-[14px] leading-relaxed">{c.text}</p><div className="mt-0.5 text-[12px] text-faint">{c.section_path.split(">").slice(1, -1).join("").trim()}</div></div>
        </li>
      ))}</ol>
    </Panel>
  );
}

export function Policies() {
  const me = useIdentity();
  const toast = useToast();
  const qc = useQueryClient();
  const list = usePolicies();
  const [open, setOpen] = useState<string | null>(null);
  const reindex = useMutation({
    mutationFn: () => api.post<{ embedded_now: number; chunks: number; model: string }>("/policies/reindex"),
    onSuccess: (r) => { qc.invalidateQueries({ queryKey: ["policies"] }); toast({ tone: "ok", title: r.embedded_now ? `${r.embedded_now} clauses embedded` : "Everything is already embedded", body: r.model }); },
    onError: (e) => toast({ tone: "danger", title: "Could not re-index", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const selected = open ?? list.data?.[0]?.id ?? null;
  return (
    <>
      <PageHeader title="Procurement policies" subtitle="The synthetic company policies the assessments cite, clause by clause."
        actions={me.role === "admin" ? <Button variant="outline" loading={reindex.isPending} onClick={() => reindex.mutate()}>Embed new clauses</Button> : undefined} />
      <div className="mb-5"><Ask /></div>
      {list.isLoading ? <Skeleton className="h-64" /> : list.error ? <ErrorState error={list.error} /> : (list.data ?? []).length === 0 ? <Panel><EmptyState title="No policies loaded" body="Upload a policy PDF as an administrator on the Documents page." /></Panel> : (
        <div className="grid gap-5 lg:grid-cols-[300px_1fr]">
          <Panel flush>
            <ul>{list.data!.map((p) => (
              <li key={p.id}><button onClick={() => setOpen(p.id)} aria-current={selected === p.id}
                className={cn("flex w-full flex-col gap-0.5 border-b border-line px-4 py-3 text-left transition-colors last:border-0", selected === p.id ? "bg-raised" : "hover:bg-raised/50")}>
                <span className="flex items-center gap-2 text-[13.5px] font-medium">{p.code}{selected === p.id && <span className="h-1.5 w-1.5 rounded-full bg-iris" aria-hidden />}</span>
                <span className="text-[13px] text-muted">{p.title}</span>
                <span className="text-[12px] text-faint">{p.chunks} clauses, {p.embedded_chunks === p.chunks ? "all searchable" : `${p.chunks - p.embedded_chunks} not yet embedded`}{p.category ? `, ${label(p.category).toLowerCase()}` : ""}</span>
              </button></li>
            ))}</ul>
          </Panel>
          {selected && <Clauses id={selected} />}
        </div>
      )}
    </>
  );
}
