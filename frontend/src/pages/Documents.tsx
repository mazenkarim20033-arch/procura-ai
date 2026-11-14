import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { Badge, Button, Drawer, EmptyState, ErrorState, PageHeader, Panel, Select, Skeleton, tableClasses as t, useToast } from "../components/ui";
import { api, ApiError, type DocumentSummary } from "../lib/api";
import { cn } from "../lib/cn";
import { date, label, percent } from "../lib/format";
import { useDocument, useDocuments } from "../lib/queries";

const TYPES = ["", "policy", "quotation", "invoice", "contract", "purchase_request", "other"];

function DocumentDrawer({ id, onClose }: { id: string | null; onClose: () => void }) {
  const doc = useDocument(id);
  const d = doc.data;
  const [showText, setShowText] = useState(false);
  return (
    <Drawer open={!!id} onClose={onClose} title={d?.filename ?? "Document"} subtitle={d && <span className="flex flex-wrap items-center gap-2"><Badge tone="cobalt">{label(d.doc_type)}</Badge>{d.doc_type_confidence !== null && <span>classified with {percent(d.doc_type_confidence)} share of the evidence</span>}</span>}>
      {doc.isLoading && <Skeleton className="h-64" />}
      {doc.error && <ErrorState error={doc.error} />}
      {d && (
        <div className="space-y-6">
          <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-[13.5px]">
            <div><dt className="text-muted">Status</dt><dd>{label(d.status)}</dd></div>
            <div><dt className="text-muted">Pages</dt><dd>{d.page_count}{d.ocr_used ? " (read with OCR)" : ""}</dd></div>
            <div><dt className="text-muted">Language</dt><dd>{d.language === "en" ? "English" : d.language === "ar" ? "Arabic" : label(d.language)}</dd></div>
            <div><dt className="text-muted">Searchable clauses</dt><dd>{d.chunk_count}</dd></div>
          </dl>

          {d.extraction ? (
            <section>
              <h3 className="mb-1 font-sans text-[14px] font-semibold tracking-normal">What was read from it</h3>
              <p className="mb-3 text-[13px] text-muted">Extracted by {d.extraction.method === "rules" ? "layout rules, not a model" : d.extraction.method}. Each value shows where in the document it was found.</p>
              {d.extraction.validation_issues.length > 0 && (
                <ul className="mb-4 space-y-1.5">{d.extraction.validation_issues.map((v, i) => <li key={i} className="flex gap-2 rounded-control border border-amber/25 bg-amber/5 px-3 py-2 text-[13px]"><Badge tone="amber">{label(v.code)}</Badge><span>{v.field}: {v.message}</span></li>)}</ul>
              )}
              <div className="overflow-hidden rounded-control border border-line">
                <table className="w-full text-left text-[13px]">
                  <tbody>
                    {Object.entries(d.extraction.data).filter(([k]) => k !== "items").map(([k, v]) => (
                      <tr key={k} className="border-b border-line/70 last:border-0">
                        <th className="w-[36%] px-3 py-2 align-top font-medium text-muted">{label(k)}</th>
                        <td className="px-3 py-2 align-top break-words">{String(v)}{d.extraction!.provenance[k] && <div className="text-[12px] text-faint">page {d.extraction!.provenance[k].page}: “{d.extraction!.provenance[k].text}”</div>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {Array.isArray(d.extraction.data.items) && (
                <div className="mt-4 overflow-x-auto rounded-control border border-line">
                  <table className="w-full text-left text-[13px]">
                    <thead><tr className="border-b border-line text-muted"><th className="px-3 py-2 font-medium">Item</th><th className="px-3 py-2 text-right font-medium">Qty</th><th className="px-3 py-2 text-right font-medium">Unit price</th><th className="px-3 py-2 text-right font-medium">Line total</th></tr></thead>
                    <tbody>{(d.extraction.data.items as { description: string; quantity: string; unit_price: string; line_total: string }[]).map((it, i) => (
                      <tr key={i} className="border-b border-line/70 last:border-0"><td className="px-3 py-2">{it.description}</td><td className="num px-3 py-2 text-right">{it.quantity}</td><td className="num px-3 py-2 text-right">{it.unit_price}</td><td className="num px-3 py-2 text-right">{it.line_total}</td></tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </section>
          ) : <p className="text-[13.5px] text-muted">This kind of document has no structured fields to extract.</p>}

          <section>
            <Button size="sm" variant="outline" onClick={() => setShowText(!showText)}>{showText ? "Hide the document text" : "Show the document text"}</Button>
            {showText && <div className="reveal mt-3 space-y-3">{d.pages.map((p) => <pre key={p.page_no} className="max-h-96 overflow-auto whitespace-pre-wrap rounded-control border border-line bg-ink p-3 font-mono text-[12px] leading-relaxed text-muted"><span className="mb-1 block text-faint">Page {p.page_no}</span>{p.text}</pre>)}</div>}
          </section>
        </div>
      )}
    </Drawer>
  );
}

export function Documents() {
  const [params, setParams] = useSearchParams();
  const [type, setType] = useState("");
  const docs = useDocuments();
  const toast = useToast();
  const qc = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const open = params.get("open");

  const upload = useMutation({
    mutationFn: (file: File) => api.upload<DocumentSummary & { duplicate: boolean; chunk_count: number; validation_issues: unknown[]; warnings: string[] }>("/documents", file),
    onSuccess: (r) => {
      qc.invalidateQueries({ queryKey: ["documents"] });
      toast({ tone: r.duplicate ? "neutral" : "ok", title: r.duplicate ? "Already uploaded" : `${label(r.doc_type)} read`, body: r.duplicate ? "An identical file is already in the system." : `${r.validation_issues.length} issue(s) to review; ${r.chunk_count} searchable section(s).${r.warnings.length ? " " + r.warnings[0] : ""}` });
      setParams({ open: r.id });
    },
    onError: (e) => toast({ tone: "danger", title: "Upload failed", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const rows = (docs.data ?? []).filter((d) => !type || d.doc_type === type);

  return (
    <>
      <PageHeader title="Documents" subtitle="Policies, quotations, invoices and contracts, and what the system read from each."
        actions={<><input ref={input} type="file" accept=".pdf,.txt,application/pdf,text/plain" className="sr-only" aria-label="Choose a file to upload" onChange={(e) => { const f = e.target.files?.[0]; if (f) upload.mutate(f); e.target.value = ""; }} />
          <Button variant="primary" icon={<Upload className="h-4 w-4" />} loading={upload.isPending} onClick={() => input.current?.click()}>Upload document</Button></>} />
      <Panel flush>
        <div className="flex items-center gap-3 border-b border-line px-5 py-3">
          <Select aria-label="Filter by type" value={type} onChange={(e) => setType(e.target.value)} className="w-auto">{TYPES.map((x) => <option key={x} value={x}>{x ? label(x) : "All types"}</option>)}</Select>
          <span className="num ml-auto text-[13px] text-muted">{rows.length} documents</span>
        </div>
        {docs.isLoading ? <div className="space-y-2 p-5"><Skeleton className="h-9" /><Skeleton className="h-9" /></div> : docs.error ? <div className="p-5"><ErrorState error={docs.error} retry={() => docs.refetch()} /></div>
          : rows.length === 0 ? <EmptyState title="No documents" body="Upload a PDF to see what the system reads from it. Supported: PDF and plain text." /> : (
            <div className={t.wrap}>
              <table className={t.table}>
                <thead><tr><th className={t.th}>File</th><th className={t.th}>Type</th><th className={t.th}>Status</th><th className={cn(t.th, "text-right")}>Pages</th><th className={t.th}>Added</th></tr></thead>
                <tbody>{rows.map((d) => (
                  <tr key={d.id} className={cn(t.row, "cursor-pointer")} onClick={() => setParams({ open: d.id })}>
                    <td className={t.td}><button className="max-w-[360px] break-all text-left font-medium hover:text-[#b4a8ff]">{d.filename}</button>{d.is_synthetic && <Badge tone="neutral" className="ml-2 border-dashed">Synthetic</Badge>}</td>
                    <td className={t.td}><Badge tone={d.doc_type === "other" ? "neutral" : "cobalt"}>{label(d.doc_type)}</Badge></td>
                    <td className={t.td}>{label(d.status)}</td><td className={cn(t.td, "num text-right")}>{d.page_count}</td><td className={cn(t.td, "text-muted")}>{date(d.created_at)}</td>
                  </tr>
                ))}</tbody>
              </table>
            </div>
          )}
      </Panel>
      <DocumentDrawer id={open} onClose={() => setParams({})} />
    </>
  );
}
