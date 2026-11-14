import { useMutation } from "@tanstack/react-query";
import { FileText, Paperclip } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Badge, Button, EmptyState, Field, Panel, Select, useToast } from "../../components/ui";
import { api, ApiError, type RequestDocument } from "../../lib/api";
import { label } from "../../lib/format";
import { useDocuments, useInvalidateRequest } from "../../lib/queries";

export function DocumentsPanel({ requestId, attached, locked }: { requestId: string; attached: RequestDocument[]; locked: boolean }) {
  const all = useDocuments();
  const toast = useToast();
  const refresh = useInvalidateRequest();
  const [choice, setChoice] = useState("");
  const taken = new Set(attached.map((d) => d.id));
  const candidates = (all.data ?? []).filter((d) => !taken.has(d.id) && ["quotation", "invoice", "contract", "other"].includes(d.doc_type));

  const attach = useMutation({
    mutationFn: () => api.post(`/requests/${requestId}/documents`, { document_id: choice }),
    onSuccess: () => { toast({ tone: "ok", title: "Document attached" }); setChoice(""); refresh(requestId); },
    onError: (e) => toast({ tone: "danger", title: "Could not attach", body: e instanceof ApiError ? e.detail : undefined }),
  });

  return (
    <div className="space-y-5">
      <Panel title="Attached documents" description="Quotations feed the price comparison; contracts and invoices are checked for payment terms." flush>
        {attached.length === 0 ? <EmptyState title="Nothing attached yet" body="Attach a quotation below, or upload one on the Documents page first." /> : (
          <ul>{attached.map((d) => (
            <li key={d.id} className="flex items-center gap-3 border-b border-line px-5 py-3 last:border-0">
              <FileText className="h-4 w-4 shrink-0 text-muted" aria-hidden />
              <div className="min-w-0 flex-1"><Link to={`/documents?open=${d.id}`} className="break-all text-[13.5px] font-medium hover:text-[#b4a8ff]">{d.filename}</Link></div>
              <Badge tone={d.doc_type === "quotation" ? "cobalt" : "neutral"}>{label(d.doc_type)}</Badge>
            </li>
          ))}</ul>
        )}
      </Panel>
      {!locked && (
        <Panel title="Attach an existing document" description="Upload new files on the Documents page, then attach them here.">
          <div className="flex flex-wrap items-end gap-3">
            <div className="min-w-[260px] flex-1">
              <Field label="Document">{(id) => (
                <Select id={id} value={choice} onChange={(e) => setChoice(e.target.value)}>
                  <option value="">{candidates.length ? "Choose a document" : "No unattached documents"}</option>
                  {candidates.map((d) => <option key={d.id} value={d.id}>{label(d.doc_type)}: {d.filename}</option>)}
                </Select>
              )}</Field>
            </div>
            <Button variant="primary" icon={<Paperclip className="h-4 w-4" />} disabled={!choice} loading={attach.isPending} onClick={() => attach.mutate()}>Attach to request</Button>
          </div>
        </Panel>
      )}
    </div>
  );
}
