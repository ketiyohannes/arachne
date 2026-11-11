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
    <section role="tabpanel" className="mt-3 overflow-hidden rounded-lg border border-line bg-panel">
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

/** A value with a thin bar under it. Empty when the device has no such resource. */
export function Gauge({ percent, text }: { percent: number | null; text: string }) {
  if (percent === null) return <span className="text-ink-3">–</span>;
  return (
    <div className="min-w-0" title={`${Math.round(percent)}%`}>
      <div className="truncate text-[13px]">{text}</div>
      <div className="mt-1 h-1 overflow-hidden rounded-full bg-track">
        <div className="h-full rounded-full bg-accent" style={{ width: `${Math.max(0, Math.min(100, percent))}%` }} />
      </div>
    </div>
  );
}
