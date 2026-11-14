import { AlertTriangle, CheckCircle2, Info, Loader2, X } from "lucide-react";
import {
  createContext, useCallback, useContext, useEffect, useId, useRef, useState,
  type ButtonHTMLAttributes, type InputHTMLAttributes, type ReactNode, type SelectHTMLAttributes, type TextareaHTMLAttributes,
} from "react";
import { createPortal } from "react-dom";
import { ApiError } from "../lib/api";
import { cn } from "../lib/cn";

/* ------------------------------------------------------------------ buttons */
type ButtonVariant = "primary" | "quiet" | "outline" | "danger";
interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: "sm" | "md";
  loading?: boolean;
  icon?: ReactNode;
}

const buttonStyles: Record<ButtonVariant, string> = {
  // The one gradient in the interface: the primary action.
  primary: "bg-gradient-to-b from-iris to-cobalt text-white shadow-[0_1px_0_rgb(255_255_255/0.18)_inset,0_6px_16px_-8px_rgb(var(--iris)/0.7)] hover:brightness-110",
  quiet: "text-muted hover:bg-raised hover:text-text",
  outline: "border border-line-strong bg-panel text-text hover:bg-raised",
  danger: "border border-danger/40 bg-danger/10 text-danger hover:bg-danger/20",
};

export function Button({ variant = "outline", size = "md", loading, icon, className, children, disabled, ...rest }: ButtonProps) {
  return (
    <button
      {...rest}
      disabled={disabled || loading}
      className={cn(
        "inline-flex select-none items-center justify-center gap-2 rounded-control font-medium transition-colors duration-100 disabled:cursor-not-allowed disabled:opacity-50",
        size === "sm" ? "h-8 px-3 text-[13px]" : "h-9 px-4 text-[14px]",
        buttonStyles[variant],
        className,
      )}
    >
      {loading ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : icon}
      {children}
    </button>
  );
}

/* ------------------------------------------------------------------ badges */
export type Tone = "danger" | "amber" | "ok" | "cobalt" | "quiet" | "neutral";
const toneStyles: Record<Tone, string> = {
  danger: "border-danger/30 bg-danger/10 text-danger",
  amber: "border-amber/30 bg-amber/10 text-amber",
  ok: "border-ok/30 bg-ok/10 text-ok",
  cobalt: "border-cobalt/35 bg-cobalt/10 text-[#8fb0ff]",
  quiet: "border-quiet/30 bg-quiet/10 text-quiet",
  neutral: "border-line-strong bg-raised text-muted",
};

export function Badge({ tone = "neutral", children, className, title }: { tone?: Tone; children: ReactNode; className?: string; title?: string }) {
  return (
    <span title={title} className={cn("inline-flex items-center gap-1.5 whitespace-nowrap rounded-full border px-2.5 py-0.5 text-[12px] font-medium leading-5", toneStyles[tone], className)}>
      {children}
    </span>
  );
}

/* ------------------------------------------------------------------ surfaces */
export function Panel({ title, description, action, children, className, flush }: {
  title?: ReactNode; description?: ReactNode; action?: ReactNode; children: ReactNode; className?: string; flush?: boolean;
}) {
  return (
    <section className={cn("rounded-panel border border-line bg-panel", className)}>
      {(title || action) && (
        <header className="flex flex-wrap items-start justify-between gap-3 border-b border-line px-5 py-3.5">
          <div className="min-w-0">
            {title && <h2 className="font-sans text-[14px] font-semibold tracking-normal text-text">{title}</h2>}
            {description && <p className="mt-0.5 max-w-prose text-[13px] text-muted">{description}</p>}
          </div>
          {action}
        </header>
      )}
      <div className={flush ? "" : "p-5"}>{children}</div>
    </section>
  );
}

export function PageHeader({ title, subtitle, actions }: { title: string; subtitle?: ReactNode; actions?: ReactNode }) {
  return (
    <div className="mb-6 flex flex-wrap items-end justify-between gap-4">
      <div className="min-w-0">
        <h1 className="text-[30px] font-medium leading-tight text-text">{title}</h1>
        {subtitle && <p className="mt-1 max-w-2xl text-[14px] text-muted">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}

export function Stat({ label, value, hint, tone }: { label: string; value: ReactNode; hint?: ReactNode; tone?: Tone }) {
  return (
    <div className="min-w-0">
      <div className="text-[13px] text-muted">{label}</div>
      <div className={cn("num mt-1 text-[26px] font-medium leading-none tracking-tight", tone === "danger" && "text-danger", tone === "ok" && "text-ok", tone === "amber" && "text-amber")}>
        {value}
      </div>
      {hint && <div className="mt-1.5 text-[12px] text-faint">{hint}</div>}
    </div>
  );
}

export function KeyValue({ items, className }: { items: { k: string; v: ReactNode }[]; className?: string }) {
  return (
    <dl className={cn("grid grid-cols-[minmax(110px,auto)_1fr] gap-x-6 gap-y-2.5 text-[13.5px]", className)}>
      {items.map((i) => (
        <div key={i.k} className="contents">
          <dt className="text-muted">{i.k}</dt>
          <dd className="min-w-0 break-words text-text">{i.v}</dd>
        </div>
      ))}
    </dl>
  );
}

/* ------------------------------------------------------------------ forms */
const control = "w-full rounded-control border border-line-strong bg-ink px-3 text-[14px] text-text placeholder:text-faint transition-colors hover:border-faint focus:border-iris focus:outline-none focus:ring-2 focus:ring-iris/30 disabled:opacity-50";

export function Field({ label, hint, error, children }: { label: string; hint?: ReactNode; error?: string | null; children: (id: string) => ReactNode }) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-[13px] font-medium text-text">{label}</label>
      {children(id)}
      {error ? <p className="text-[12.5px] text-danger" role="alert">{error}</p> : hint ? <p className="text-[12.5px] text-faint">{hint}</p> : null}
    </div>
  );
}
export const Input = (p: InputHTMLAttributes<HTMLInputElement>) => <input {...p} className={cn(control, "h-9", p.className)} />;
export const Textarea = (p: TextareaHTMLAttributes<HTMLTextAreaElement>) => <textarea {...p} className={cn(control, "min-h-[88px] resize-y py-2", p.className)} />;
export const Select = (p: SelectHTMLAttributes<HTMLSelectElement>) => <select {...p} className={cn(control, "h-9 pr-8", p.className)} />;

/* ------------------------------------------------------------------ navigation */
export function Tabs<T extends string>({ tabs, value, onChange }: { tabs: { id: T; label: string; count?: number | string }[]; value: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="flex gap-1 overflow-x-auto border-b border-line">
      {tabs.map((t) => (
        <button
          key={t.id} role="tab" aria-selected={value === t.id} onClick={() => onChange(t.id)}
          className={cn("relative -mb-px flex items-center gap-2 whitespace-nowrap px-3.5 py-2.5 text-[13.5px] font-medium transition-colors",
            value === t.id ? "text-text" : "text-muted hover:text-text")}
        >
          {t.label}
          {t.count !== undefined && <span className="num rounded-full bg-raised px-1.5 text-[11.5px] text-muted">{t.count}</span>}
          {value === t.id && <span className="absolute inset-x-2 bottom-0 h-[2px] rounded-full bg-gradient-to-r from-iris to-cobalt" />}
        </button>
      ))}
    </div>
  );
}

/* ------------------------------------------------------------------ overlays */
function useEscape(open: boolean, onClose: () => void) {
  useEffect(() => {
    if (!open) return;
    const h = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", h);
    return () => window.removeEventListener("keydown", h);
  }, [open, onClose]);
}

function useFocusReturn(open: boolean) {
  const prev = useRef<Element | null>(null);
  useEffect(() => {
    if (open) prev.current = document.activeElement;
    else (prev.current as HTMLElement | null)?.focus?.();
  }, [open]);
}

export function Dialog({ open, onClose, title, description, children, footer, wide }: {
  open: boolean; onClose: () => void; title: string; description?: string; children: ReactNode; footer?: ReactNode; wide?: boolean;
}) {
  useEscape(open, onClose);
  useFocusReturn(open);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => { if (open) ref.current?.querySelector<HTMLElement>("input, textarea, select, button")?.focus(); }, [open]);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50 flex items-start justify-center overflow-y-auto p-4 pt-[8vh]">
      <div className="fixed inset-0 bg-black/60 backdrop-blur-[2px]" onClick={onClose} aria-hidden />
      <div ref={ref} role="dialog" aria-modal="true" aria-label={title}
        className={cn("reveal relative w-full rounded-panel border border-line-strong bg-panel shadow-2xl", wide ? "max-w-3xl" : "max-w-lg")}>
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div>
            <h2 className="font-sans text-[16px] font-semibold tracking-normal">{title}</h2>
            {description && <p className="mt-1 text-[13px] text-muted">{description}</p>}
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-control p-1 text-muted hover:bg-raised hover:text-text"><X className="h-4 w-4" /></button>
        </header>
        <div className="p-5">{children}</div>
        {footer && <footer className="flex justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</footer>}
      </div>
    </div>,
    document.body,
  );
}

export function Drawer({ open, onClose, title, subtitle, children }: { open: boolean; onClose: () => void; title: string; subtitle?: ReactNode; children: ReactNode }) {
  useEscape(open, onClose);
  useFocusReturn(open);
  if (!open) return null;
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div className="absolute inset-0 bg-black/55" onClick={onClose} aria-hidden />
      <aside role="dialog" aria-modal="true" aria-label={title}
        className="reveal absolute inset-y-0 right-0 flex w-full max-w-[640px] flex-col border-l border-line-strong bg-panel shadow-2xl">
        <header className="flex items-start justify-between gap-4 border-b border-line px-5 py-4">
          <div className="min-w-0">
            <h2 className="truncate font-sans text-[16px] font-semibold tracking-normal">{title}</h2>
            {subtitle && <div className="mt-1 text-[13px] text-muted">{subtitle}</div>}
          </div>
          <button onClick={onClose} aria-label="Close" className="rounded-control p-1 text-muted hover:bg-raised hover:text-text"><X className="h-4 w-4" /></button>
        </header>
        <div className="flex-1 overflow-y-auto p-5">{children}</div>
      </aside>
    </div>,
    document.body,
  );
}

/* ------------------------------------------------------------------ feedback */
export const Skeleton = ({ className }: { className?: string }) => <div className={cn("animate-pulse rounded-control bg-raised", className)} />;

export function Spinner({ label = "Loading" }: { label?: string }) {
  return <div className="flex items-center gap-2 py-8 text-[13px] text-muted" role="status"><Loader2 className="h-4 w-4 animate-spin" aria-hidden />{label}</div>;
}

export function EmptyState({ title, body, action }: { title: string; body?: ReactNode; action?: ReactNode }) {
  return (
    <div className="flex flex-col items-center px-6 py-12 text-center">
      <div className="text-[15px] font-medium text-text">{title}</div>
      {body && <p className="mt-1.5 max-w-md text-[13.5px] text-muted">{body}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

export function ErrorState({ error, retry }: { error: unknown; retry?: () => void }) {
  const e = error instanceof ApiError ? error : null;
  return (
    <div className="rounded-panel border border-danger/30 bg-danger/5 p-5" role="alert">
      <div className="flex items-start gap-3">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-text">{e?.status === 403 ? "You do not have access to this" : e?.status === 0 ? "The API is not reachable" : "Something went wrong"}</div>
          <p className="mt-1 text-[13.5px] text-muted">{e?.detail ?? (error instanceof Error ? error.message : "Unknown error")}</p>
          {e?.status === 403 && <p className="mt-1 text-[13px] text-faint">Switch persona in the top bar to a reviewer or administrator.</p>}
          {retry && <Button size="sm" variant="outline" className="mt-3" onClick={retry}>Try again</Button>}
        </div>
      </div>
    </div>
  );
}

/* ------------------------------------------------------------------ toasts */
interface Toast { id: number; tone: "ok" | "danger" | "neutral"; title: string; body?: string }
const ToastCtx = createContext<(t: Omit<Toast, "id">) => void>(() => undefined);
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<Toast[]>([]);
  const push = useCallback((t: Omit<Toast, "id">) => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { ...t, id }]);
    setTimeout(() => setItems((x) => x.filter((i) => i.id !== id)), t.tone === "danger" ? 9000 : 4500);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2" aria-live="polite">
          {items.map((t) => (
            <div key={t.id} className="reveal pointer-events-auto flex gap-3 rounded-panel border border-line-strong bg-raised p-3.5 shadow-xl">
              {t.tone === "ok" ? <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-ok" /> : t.tone === "danger" ? <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-danger" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-cobalt" />}
              <div className="min-w-0 text-[13.5px]">
                <div className="font-medium text-text">{t.title}</div>
                {t.body && <div className="mt-0.5 break-words text-muted">{t.body}</div>}
              </div>
            </div>
          ))}
        </div>,
        document.body,
      )}
    </ToastCtx.Provider>
  );
}

/* ------------------------------------------------------------------ tables */
export const tableClasses = {
  wrap: "overflow-x-auto",
  table: "w-full border-collapse text-left text-[13.5px]",
  th: "sticky top-0 whitespace-nowrap border-b border-line bg-panel px-4 py-2.5 text-[12.5px] font-medium text-muted",
  td: "border-b border-line/70 px-4 py-3 align-top",
  row: "transition-colors hover:bg-raised/60",
};
