import { useState, type ReactNode } from "react";
import { ago, health, osName, pct, runningJobs, uptime, type TraceItem } from "../format";
import type { Device } from "../types";
import { Bar, HealthDot, Sparkline } from "./bits";

function Metric({ label, value, children }: { label: string; value: string; children: ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-1 flex items-baseline justify-between gap-2">
        <span className="text-[12px] text-ink-3">{label}</span>
        <span className="truncate text-[13px] font-medium">{value}</span>
      </div>
      {children}
    </div>
  );
}

const gb = (mb: number | null) => ((mb ?? 0) / 1024).toFixed(1);

function DeviceCard({ device: d, latest }: { device: Device; latest?: TraceItem }) {
  const [open, setOpen] = useState(false);
  const state = health(d);
  const s = d.stats;
  const gpu = s?.gpus[0];
  const history = d.history ?? [];
  const jobs = runningJobs(d).length;
  const link = { self: "this hub", direct: "direct", relay: `relayed${d.relay ? ` via ${d.relay}` : ""}`, offline: "offline" }[d.link];

  return (
    <article className={`rounded-xl border border-line bg-panel ${state === "offline" ? "opacity-60" : ""}`}>
      <header className="flex items-center gap-2 px-4 pt-3.5">
        <HealthDot state={state} />
        <h2 className="m-0 min-w-0 truncate text-[15px] font-semibold">{d.name}</h2>
        {jobs > 0 && <span className="shrink-0 rounded-full bg-accent/12 px-2 py-px text-[12px] font-medium text-accent">{jobs} running</span>}
        <span className="ml-auto shrink-0 text-[12px] text-ink-3">{[osName(d.os), state === "unreachable" ? "unreachable" : link].filter(Boolean).join(" · ")}</span>
      </header>

      {s ? (
        <>
          <div className="grid grid-cols-2 gap-x-5 gap-y-4 px-4 pb-3 pt-3 sm:grid-cols-3">
            <Metric label="CPU" value={pct(s.cpu.percent)}><Sparkline values={history.map((h) => h[1])} /></Metric>
            <Metric label="Memory" value={`${s.memory.used_gb} / ${s.memory.total_gb} GB`}><Sparkline values={history.map((h) => h[2])} /></Metric>
            <Metric label="Disk" value={`${s.disk.used_gb} / ${s.disk.total_gb} GB`}><div className="flex h-8 items-center"><div className="w-full"><Bar percent={s.disk.percent} /></div></div></Metric>
            {gpu && (
              <>
                <Metric label="GPU" value={gpu.util != null ? pct(gpu.util) : "–"}><Sparkline values={history.map((h) => h[3] ?? 0)} /></Metric>
                <Metric label="VRAM" value={`${gb(gpu.mem_used_mb)} / ${gb(gpu.mem_total_mb)} GB`}>
                  <div className="flex h-8 items-center"><div className="w-full"><Bar percent={gpu.mem_total_mb ? (100 * (gpu.mem_used_mb ?? 0)) / gpu.mem_total_mb : 0} /></div></div>
                </Metric>
                <Metric label="GPU model" value={gpu.temp_c != null ? `${Math.round(gpu.temp_c)}°C` : ""}>
                  <div className="flex h-8 items-center truncate text-[12px] text-ink-2">{gpu.name.replace(/^NVIDIA GeForce /, "")}</div>
                </Metric>
              </>
            )}
          </div>

          <button
            type="button"
            onClick={() => setOpen(!open)}
            aria-expanded={open}
            className="flex w-full cursor-pointer items-baseline gap-3 rounded-b-xl border-0 border-t border-solid border-line bg-transparent px-4 py-2.5 text-left font-[inherit] text-[12px] text-ink-3 hover:bg-track/40"
          >
            {latest ? (
              <>
                <code className="min-w-0 truncate font-mono text-ink-2">{latest.command}</code>
                <span className="shrink-0">{latest.status === "running" ? "running" : `${ago(latest.started)} ago`}</span>
              </>
            ) : (
              <span>No commands yet</span>
            )}
            <span className="ml-auto shrink-0">{open ? "Hide details" : "Details"}</span>
          </button>

          {open && (
            <div className="border-t border-line px-4 py-3 text-[12px]">
              <div className="text-ink-2">
                {[d.ip, `up ${uptime(s.time - s.boot_time)}`, `${s.cpu.cores} cores`, `desktop control ${s.desktop.running ? "ready" : "off"}`].join(" · ")}
              </div>
              {s.processes.length > 0 && (
                <table className="mt-2 w-full border-collapse">
                  <thead>
                    <tr className="text-left text-ink-3"><th className="py-0.5 font-normal">Top processes</th><th className="py-0.5 text-right font-normal">CPU</th><th className="py-0.5 text-right font-normal">Memory</th></tr>
                  </thead>
                  <tbody>
                    {s.processes.map((p) => (
                      <tr key={p.pid}><td className="max-w-0 truncate py-0.5 pr-3">{p.name}</td><td className="py-0.5 text-right">{pct(p.cpu)}</td><td className="py-0.5 text-right">{p.mem_mb} MB</td></tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          )}
        </>
      ) : (
        <p className="m-0 px-4 pb-3.5 pt-2 text-[13px] text-ink-3">{state === "offline" ? "Not connected to the tailnet." : d.error}</p>
      )}
    </article>
  );
}

export function Devices({ devices, items }: { devices: Device[]; items: TraceItem[] }) {
  return (
    <div className="mt-3 grid grid-cols-[minmax(0,1fr)] items-start gap-3 lg:grid-cols-2">
      {devices.map((d) => <DeviceCard key={d.name} device={d} latest={items.find((i) => i.device === d.name)} />)}
    </div>
  );
}
