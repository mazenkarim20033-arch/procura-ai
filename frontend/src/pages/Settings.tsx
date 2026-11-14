import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { IdentityEditor } from "../components/Shell";
import { MockBadge } from "../components/badges";
import { Badge, Button, Field, KeyValue, PageHeader, Panel, Skeleton, Textarea, useToast } from "../components/ui";
import { API_URL, api, ApiError } from "../lib/api";
import { PERSONAS, setIdentity } from "../lib/identity";
import { useApprovedSuppliers, useHealth, useIdentity } from "../lib/queries";

function Suppliers() {
  const me = useIdentity();
  const toast = useToast();
  const qc = useQueryClient();
  const list = useApprovedSuppliers();
  const [text, setText] = useState("");
  useEffect(() => { if (list.data) setText(list.data.names.join("\n")); }, [list.data]);
  const save = useMutation({
    mutationFn: () => api.put("/settings/approved-suppliers", { names: text.split("\n").map((s) => s.trim()).filter(Boolean) }),
    onSuccess: () => { qc.invalidateQueries({ queryKey: ["approved-suppliers"] }); toast({ tone: "ok", title: "Approved suppliers saved", body: "New assessments use this list." }); },
    onError: (e) => toast({ tone: "danger", title: "Not saved", body: e instanceof ApiError ? e.detail : undefined }),
  });
  const admin = me.role === "admin";
  return (
    <Panel title="Approved suppliers" description="Purchases above USD 5,000 must use a supplier on this list (PRC-003:1.1). Without a list, that check reports missing information instead of guessing.">
      {list.isLoading ? <Skeleton className="h-32" /> : (
        <div className="space-y-3">
          {!list.data?.configured && <Badge tone="amber">No list configured yet</Badge>}
          <Field label="One supplier name per line" hint={admin ? "Spelling variants such as Ltd and Limited are matched automatically." : "Only an administrator can change this list. Switch persona in the top bar."}>
            {(id) => <Textarea id={id} rows={8} value={text} readOnly={!admin} onChange={(e) => setText(e.target.value)} />}
          </Field>
          {admin && <Button variant="primary" loading={save.isPending} onClick={() => save.mutate()}>Save list</Button>}
        </div>
      )}
    </Panel>
  );
}

export function SettingsPage() {
  const health = useHealth();
  const c = health.data?.checks;
  return (
    <>
      <PageHeader title="Settings" subtitle="Who you are acting as, how the app is connected, and the rules it applies." />
      <div className="space-y-5">
        <Panel title="Acting as" description="This demo has no passwords. You choose who you are, and the server still enforces what each role may do: only reviewers decide, nobody decides their own request, and the approval level follows the amount.">
          <div className="space-y-5">
            <div className="flex flex-wrap gap-2">{PERSONAS.map((p) => <Button key={p.user} size="sm" variant="outline" onClick={() => setIdentity(p)}>{p.label}</Button>)}</div>
            <IdentityEditor />
          </div>
        </Panel>

        <Panel title="Connection" description={`API at ${API_URL}`}>
          {health.isLoading ? <Skeleton className="h-24" /> : health.error || !c ? <p className="text-[13.5px] text-danger">The API did not answer. Start the backend and reload.</p> : (
            <KeyValue items={[
              { k: "Database", v: <Badge tone={c.database.ok ? "ok" : "danger"}>{c.database.ok ? "Connected" : "Unavailable"}</Badge> },
              { k: "Vector search", v: <Badge tone={c.pgvector.ok ? "ok" : "danger"}>{c.pgvector.ok ? "pgvector ready" : "Unavailable"}</Badge> },
              { k: "Embedding model", v: <span>{c.embedding.model} <span className="text-muted">({c.embedding.loaded ? "loaded" : "loads on first search"})</span></span> },
              { k: "AI provider", v: c.llm.mock ? <span className="flex items-center gap-2"><MockBadge /><span className="text-muted">deterministic keyword rules, no credentials needed</span></span> : <span>{c.llm.provider}</span> },
            ]} />
          )}
        </Panel>

        <Suppliers />

        <Panel title="About this demo">
          <ul className="max-w-prose list-disc space-y-2 pl-5 text-[13.5px] leading-relaxed text-muted">
            <li>All documents, vendors, people and policies are <span className="text-text">synthetic</span>. Nothing here is a real company.</li>
            <li>The AI never approves a purchase. It produces findings with evidence; a person records every decision, with reasons, and decisions cannot be edited.</li>
            <li>Rules decide what is a confirmed violation. A language model can only add potential or inconclusive findings, and each of its quotes is checked against the stored policy text.</li>
            <li>Items marked <MockBadge /> come from the mock provider, which is a set of keyword rules, not an AI model.</li>
            <li>Amount rules work in USD only. There is no exchange-rate source, and no supplier is verified outside the documents you upload.</li>
          </ul>
        </Panel>
      </div>
    </>
  );
}
