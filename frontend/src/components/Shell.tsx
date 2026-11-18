import { Activity, BarChart3, BookOpenCheck, ClipboardList, FileSearch, LayoutDashboard, Menu, ScrollText, Settings, Store, X } from "lucide-react";
import { useState } from "react";
import { NavLink, Outlet, useLocation } from "react-router-dom";
import { cn } from "../lib/cn";
import { AUTHORITIES, PERSONAS, isReviewer, setIdentity, type Identity, type Role } from "../lib/identity";
import { useHealth, useIdentity, useQueue } from "../lib/queries";
import { MockBadge } from "./badges";
import { Badge, Select } from "./ui";

const NAV = [
  { to: "/", label: "Overview", icon: LayoutDashboard, end: true },
  { to: "/requests", label: "Purchase requests", icon: ClipboardList },
  { to: "/documents", label: "Documents", icon: FileSearch },
  { to: "/vendors", label: "Vendors", icon: Store },
  { to: "/policies", label: "Policies", icon: BookOpenCheck },
  { to: "/analytics", label: "Analytics", icon: BarChart3 },
  { to: "/audit", label: "Audit history", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: Settings },
];

function Wordmark({ hideTextOnXs }: { hideTextOnXs?: boolean }) {
  return (
    <div className="flex items-center gap-2.5 px-1">
      <svg viewBox="0 0 32 32" className="h-7 w-7" aria-hidden>
        <rect width="32" height="32" rx="8" fill="rgb(var(--raised))" />
        <path d="M10.5 23V9h6.5a5 5 0 0 1 0 10h-3.5" fill="none" stroke="url(#g)" strokeWidth="3" strokeLinecap="round" />
        <defs><linearGradient id="g" x1="8" y1="8" x2="24" y2="24"><stop stopColor="#8f7bff" /><stop offset="1" stopColor="#4f7cff" /></linearGradient></defs>
      </svg>
      <span className={cn("font-display text-[20px] font-medium leading-none tracking-tight", hideTextOnXs && "max-[440px]:hidden")}>Procura</span>
    </div>
  );
}

function AiStatus() {
  const { data } = useHealth();
  if (!data) return <div className="text-[12.5px] text-faint">Checking the API</div>;
  const llm = data.checks.llm;
  const healthy = data.status === "ok";
  return (
    <div className="space-y-1.5 text-[12.5px]">
      <div className="flex items-center gap-2 text-muted">
        <span className={cn("h-1.5 w-1.5 rounded-full", healthy ? "bg-ok" : "bg-danger")} aria-hidden />
        {data.snapshot ? "Recorded snapshot" : healthy ? "API connected" : "API degraded"}
      </div>
      <div className="flex items-center gap-2">
        {llm.mock ? <MockBadge /> : <Badge tone="quiet">Live model</Badge>}
        <span className="truncate text-faint">{llm.mock ? "recorded heuristics" : llm.provider}</span>
      </div>
    </div>
  );
}

export function IdentityPicker({ compact }: { compact?: boolean }) {
  const id = useIdentity();
  const key = `${id.role}|${id.user}|${id.authority ?? ""}`;
  const preset = PERSONAS.find((p) => `${p.role}|${p.user}|${p.authority ?? ""}` === key);
  const pick = (v: string) => {
    if (v === "custom") return;
    setIdentity(PERSONAS[Number(v)]);
  };
  return (
    <div className={cn("flex items-center gap-2", compact && "w-full")}>
      <Select aria-label="Acting as" value={preset ? String(PERSONAS.indexOf(preset)) : "custom"} onChange={(e) => pick(e.target.value)} className={compact ? "h-8 text-[13px]" : "h-8 w-[170px] text-[13px] sm:w-[240px]"}>
        {PERSONAS.map((p, i) => <option key={p.user} value={i}>{p.label}: {p.user}</option>)}
        {!preset && <option value="custom">Custom: {id.user}</option>}
      </Select>
    </div>
  );
}

export function IdentityEditor() {
  const id = useIdentity();
  const set = (patch: Partial<Identity>) => setIdentity({ ...id, ...patch, label: "Custom" });
  return (
    <div className="grid gap-4 sm:grid-cols-3">
      <label className="space-y-1.5 text-[13px] font-medium">Name
        <input className="mt-1.5 block h-9 w-full rounded-control border border-line-strong bg-ink px-3 text-[14px] font-normal" value={id.user} onChange={(e) => set({ user: e.target.value })} />
      </label>
      <label className="space-y-1.5 text-[13px] font-medium">Role
        <Select className="mt-1.5" value={id.role} onChange={(e) => set({ role: e.target.value as Role })}>
          <option value="requester">Requester</option><option value="reviewer">Reviewer</option><option value="admin">Administrator</option>
        </Select>
      </label>
      <label className="space-y-1.5 text-[13px] font-medium">Approval authority
        <Select className="mt-1.5" value={id.authority ?? ""} onChange={(e) => set({ authority: e.target.value || null })}>
          <option value="">None</option>{AUTHORITIES.map((a) => <option key={a} value={a}>{a}</option>)}
        </Select>
      </label>
    </div>
  );
}

export function Shell() {
  const [open, setOpen] = useState(false);
  const id = useIdentity();
  const loc = useLocation();
  const queue = useQueue();
  const health = useHealth().data;
  const readOnly = health?.read_only === true;
  const snapshot = health?.snapshot === true;
  const waiting = queue.data?.length;

  const nav = (
    <nav aria-label="Main" className="flex flex-1 flex-col gap-0.5">
      {NAV.map(({ to, label, icon: Icon, end }) => (
        <NavLink key={to} to={to} end={end} onClick={() => setOpen(false)}
          className={({ isActive }) => cn("group relative flex items-center gap-3 rounded-control px-3 py-2 text-[14px] transition-colors", isActive ? "bg-raised text-text" : "text-muted hover:bg-raised/60 hover:text-text")}>
          {({ isActive }) => (
            <>
              {isActive && <span className="absolute -left-3 top-2 bottom-2 w-[3px] rounded-full bg-gradient-to-b from-iris to-cobalt" />}
              <Icon className="h-[17px] w-[17px] shrink-0" aria-hidden />
              <span className="flex-1">{label}</span>
              {to === "/requests" && isReviewer(id) && waiting ? <span className="num rounded-full bg-iris/15 px-1.5 text-[11.5px] text-[#b4a8ff]" title="Awaiting a decision">{waiting}</span> : null}
            </>
          )}
        </NavLink>
      ))}
    </nav>
  );

  return (
    <div className="min-h-screen lg:grid lg:grid-cols-[248px_1fr]">
      <aside className="sticky top-0 hidden h-screen flex-col gap-6 border-r border-line bg-panel/60 px-5 py-5 lg:flex">
        <Wordmark />
        {nav}
        <div className="space-y-3 border-t border-line pt-4"><AiStatus /></div>
      </aside>

      <div className="min-w-0 overflow-x-clip">
        <header className="sticky top-0 z-30 flex min-w-0 items-center justify-between gap-2 border-b border-line bg-ink/85 px-4 py-2.5 backdrop-blur lg:px-8">
          <div className="flex items-center gap-3 lg:hidden">
            <button aria-label="Open menu" onClick={() => setOpen(true)} className="rounded-control p-1.5 text-muted hover:bg-raised"><Menu className="h-5 w-5" /></button>
            <Wordmark hideTextOnXs />
          </div>
          <div className="hidden items-center gap-2 text-[13px] text-faint lg:flex"><Activity className="h-3.5 w-3.5" aria-hidden />Synthetic demo data. Every decision is made by a person.</div>
          <div className="flex items-center gap-3">{readOnly && <Badge tone="amber" title={snapshot ? "A recorded snapshot of the demo: nothing can be created, assessed or decided here, and live policy search is off" : "Creating requests, uploading documents and recording decisions are disabled on this public demo"}>{snapshot ? "Snapshot" : "Read-only"}</Badge>}<span className="hidden text-[13px] text-muted sm:inline">Acting as</span><IdentityPicker /></div>
        </header>

        <main key={loc.pathname} className="mx-auto w-full max-w-[1280px] px-4 py-8 lg:px-8"><Outlet /></main>
      </div>

      {open && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={() => setOpen(false)} aria-hidden />
          <div className="reveal absolute inset-y-0 left-0 flex w-[280px] flex-col gap-6 border-r border-line bg-panel px-5 py-5">
            <div className="flex items-center justify-between"><Wordmark /><button aria-label="Close menu" onClick={() => setOpen(false)} className="rounded-control p-1.5 text-muted hover:bg-raised"><X className="h-5 w-5" /></button></div>
            {nav}
            <div className="border-t border-line pt-4"><AiStatus /></div>
          </div>
        </div>
      )}
    </div>
  );
}
