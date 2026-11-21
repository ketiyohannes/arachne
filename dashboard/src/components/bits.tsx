import type { ReactNode } from "react";
import type { Health, TraceItem } from "../format";

export interface TabSpec<T extends string> {
  id: T;
  label: string;
  /** Shown next to the label, e.g. how many things are running. */
  count?: number;
}

/** Full-width on a phone so each tab is an easy thumb target; compact on larger screens. */
export function Tabs<T extends string>({ tabs, active, onChange }: { tabs: TabSpec<T>[]; active: T; onChange: (id: T) => void }) {
  return (
    <div role="tablist" className="mt-4 flex border-b border-line">
      {tabs.map((tab) => {
        const selected = tab.id === active;
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={selected}
            onClick={() => onChange(tab.id)}
            className={`-mb-px flex min-h-11 flex-1 cursor-pointer items-center justify-center gap-1.5 border-0 border-b-2 border-solid bg-transparent px-4 font-[inherit] text-[14px] sm:flex-none ${
              selected ? "border-accent font-semibold text-ink" : "border-transparent text-ink-2 hover:text-ink"
            }`}
          >
            {tab.label}
            {tab.count ? <span className="rounded-full bg-track px-1.5 text-[12px] font-medium text-ink-2">{tab.count}</span> : null}
          </button>
        );
      })}
    </div>
  );
}

export function Panel({ aside, children }: { aside?: ReactNode; children: ReactNode }) {
  return (
    <section role="tabpanel" className="mt-3 overflow-hidden rounded-xl border border-line bg-panel">
      {aside && (
        <div className="flex flex-wrap items-center justify-end gap-2 border-b border-line px-4 py-2 text-[12px] text-ink-3">{aside}</div>
      )}
      {children}
    </section>
  );
}

const HEALTH_STYLE: Record<Health, string> = {
  online: "bg-good",
  unreachable: "bg-bad",
  offline: "border border-ink-3",
};

export function HealthDot({ state }: { state: Health }) {
  return <span className={`inline-block size-2 shrink-0 rounded-full ${HEALTH_STYLE[state]}`} title={state} />;
}

/** Status is a word, with colour as reinforcement only. */
export function StatusTag({ item }: { item: TraceItem }) {
  const styles = { running: "text-accent", ok: "text-good", failed: "text-bad", killed: "text-ink-3", lost: "text-ink-3" };
  const text = item.status === "failed" ? `exit ${item.exit}` : item.status;
  return <span className={`shrink-0 whitespace-nowrap text-[12px] font-medium ${styles[item.status]}`}>{text}</span>;
}

/** Accent normally; amber and red as a resource approaches its limit. */
export function levelColor(percent: number): string {
  return percent >= 90 ? "var(--bad)" : percent >= 75 ? "var(--warn)" : "var(--accent)";
}

export function Bar({ percent }: { percent: number }) {
  const width = Math.max(0, Math.min(100, percent));
  return (
    <div className="h-1.5 overflow-hidden rounded-full bg-track" role="img" aria-label={`${Math.round(percent)}%`}>
      <div className="h-full rounded-full transition-[width] duration-500" style={{ width: `${width}%`, background: levelColor(percent) }} />
    </div>
  );
}

/** Recent readings (0-100) as a filled line, newest on the right. */
export function Sparkline({ values }: { values: number[] }) {
  if (values.length < 2) return <div className="h-8 rounded bg-track/50" />;
  const step = 100 / (values.length - 1);
  const points = values.map((v, i) => `${(i * step).toFixed(2)},${(27 - (Math.max(0, Math.min(100, v)) / 100) * 26).toFixed(2)}`);
  const color = levelColor(values[values.length - 1]);
  return (
    <svg viewBox="0 0 100 28" preserveAspectRatio="none" className="block h-8 w-full" aria-hidden="true">
      <polygon points={`0,28 ${points.join(" ")} 100,28`} fill={color} opacity="0.12" />
      <polyline points={points.join(" ")} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
}

/** One headline number in the summary row. */
export function Stat({ label, value, detail, tone, onClick }: { label: string; value: ReactNode; detail?: string; tone?: "bad" | "accent"; onClick?: () => void }) {
  const color = tone === "bad" ? "text-bad" : tone === "accent" ? "text-accent" : "text-ink";
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex min-w-0 cursor-pointer flex-col items-stretch justify-start rounded-xl border border-solid border-line bg-panel px-3.5 py-3 text-left font-[inherit] text-ink hover:border-ink-3"
    >
      <div className="truncate text-[12px] text-ink-3">{label}</div>
      <div className={`mt-0.5 text-[22px] font-semibold leading-tight ${color}`}>{value}</div>
      {detail && <div className="truncate text-[12px] text-ink-3">{detail}</div>}
    </button>
  );
}
