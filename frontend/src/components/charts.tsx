import { Area, AreaChart, CartesianGrid, Cell, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { cn } from "../lib/cn";

export const COLORS = {
  iris: "rgb(143 123 255)", cobalt: "rgb(79 124 255)", danger: "rgb(239 122 133)", amber: "rgb(231 185 90)",
  ok: "rgb(92 207 154)", quiet: "rgb(167 160 214)", line: "rgb(39 46 69)", muted: "rgb(138 147 178)", neutral: "rgb(88 97 128)",
};

const tooltipStyle = {
  contentStyle: { background: "rgb(27 33 51)", border: "1px solid rgb(58 67 98)", borderRadius: 8, fontSize: 13, color: "rgb(232 234 243)" },
  itemStyle: { color: "rgb(232 234 243)" }, labelStyle: { color: "rgb(138 147 178)" }, cursor: { stroke: "rgb(58 67 98)" },
};

/** Horizontal bars with the number beside each: easier to read exactly than a chart, and fully accessible. */
export function BarList({ rows, className }: { rows: { label: string; value: number; color?: string; note?: string }[]; className?: string }) {
  const max = Math.max(1, ...rows.map((r) => r.value));
  if (rows.length === 0) return <p className="text-[13.5px] text-muted">No data yet.</p>;
  return (
    <ul className={cn("space-y-2.5", className)}>
      {rows.map((r) => (
        <li key={r.label} className="grid grid-cols-[minmax(110px,150px)_1fr_auto] items-center gap-3 text-[13.5px]">
          <span className="truncate text-muted" title={r.label}>{r.label}</span>
          <span className="h-2 overflow-hidden rounded-full bg-ink" aria-hidden>
            <span className="block h-full rounded-full" style={{ width: `${(r.value / max) * 100}%`, background: r.color ?? COLORS.iris }} />
          </span>
          <span className="num min-w-[2ch] text-right font-medium">{r.value}{r.note && <span className="ml-1.5 font-normal text-faint">{r.note}</span>}</span>
        </li>
      ))}
    </ul>
  );
}

export function Donut({ data, centerLabel }: { data: { name: string; value: number; color: string }[]; centerLabel?: string }) {
  const total = data.reduce((s, d) => s + d.value, 0);
  if (total === 0) return <p className="text-[13.5px] text-muted">No data yet.</p>;
  return (
    <div className="flex items-center gap-6">
      <div className="relative h-[150px] w-[150px] shrink-0" role="img" aria-label={data.map((d) => `${d.name} ${d.value}`).join(", ")}>
        <ResponsiveContainer>
          <PieChart>
            <Pie data={data} dataKey="value" innerRadius={50} outerRadius={70} paddingAngle={2} stroke="none">{data.map((d) => <Cell key={d.name} fill={d.color} />)}</Pie>
            <Tooltip {...tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center"><span className="num text-[22px] font-medium leading-none">{total}</span>{centerLabel && <span className="mt-1 text-[12px] text-muted">{centerLabel}</span>}</div>
      </div>
      <ul className="space-y-1.5 text-[13.5px]">{data.map((d) => <li key={d.name} className="flex items-center gap-2"><span className="h-2.5 w-2.5 rounded-full" style={{ background: d.color }} aria-hidden /><span className="text-muted">{d.name}</span><span className="num ml-auto pl-4 font-medium">{d.value}</span></li>)}</ul>
    </div>
  );
}

export function WeeklyArea({ data }: { data: { week: string; n: number }[] }) {
  if (data.length === 0) return <p className="text-[13.5px] text-muted">No requests in this period.</p>;
  return (
    <div className="h-[190px]" role="img" aria-label={`Requests submitted per week, ${data.length} weeks`}>
      <ResponsiveContainer>
        <AreaChart data={data} margin={{ left: -18, right: 8, top: 8 }}>
          <defs><linearGradient id="wk" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={COLORS.iris} stopOpacity={0.4} /><stop offset="100%" stopColor={COLORS.iris} stopOpacity={0} /></linearGradient></defs>
          <CartesianGrid stroke={COLORS.line} vertical={false} />
          <XAxis dataKey="week" tick={{ fill: COLORS.muted, fontSize: 12 }} tickLine={false} axisLine={false} tickFormatter={(v: string) => v.slice(5)} />
          <YAxis allowDecimals={false} tick={{ fill: COLORS.muted, fontSize: 12 }} tickLine={false} axisLine={false} />
          <Tooltip {...tooltipStyle} labelFormatter={(v) => `Week of ${v}`} formatter={(v) => [v, "Requests"]} />
          <Area type="monotone" dataKey="n" stroke={COLORS.iris} strokeWidth={2} fill="url(#wk)" />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  );
}

export const RISK_COLORS: Record<string, string> = { low: COLORS.ok, medium: COLORS.amber, high: COLORS.danger, critical: "rgb(214 84 104)" };
export const CATEGORY_COLORS: Record<string, string> = {
  confirmed_violation: COLORS.danger, potential_violation: COLORS.amber, missing_information: COLORS.cobalt, inconclusive: COLORS.quiet, compliant: COLORS.ok,
};
