import { Fragment, useState } from "react";
import { health, osName, pct, runningJobs, uptime } from "../format";
import type { Device } from "../types";
import { Gauge, HealthDot } from "./bits";

// One grid for header and rows keeps columns aligned; below `md` each device becomes a small block instead.
const COLUMNS = "md:grid md:grid-cols-[minmax(150px,1.5fr)_repeat(5,minmax(0,1fr))_70px] md:items-center md:gap-4";

function Cell({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="min-w-0">
      <div className="mb-0.5 text-[11px] text-ink-3 md:hidden">{label}</div>
      {children}
    </div>
  );
}

export function Devices({ devices }: { devices: Device[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <div>
      <div className={`hidden border-b border-line px-4 py-2 text-[12px] text-ink-3 ${COLUMNS}`}>
        <span>Device</span><span>CPU</span><span>Memory</span><span>Disk</span><span>GPU</span><span>VRAM</span><span>Jobs</span>
      </div>
      {devices.map((d) => {
        const state = health(d);
        const s = d.stats;
        const gpu = s?.gpus[0];
        const vram = gpu?.mem_total_mb ? (100 * (gpu.mem_used_mb ?? 0)) / gpu.mem_total_mb : null;
        const jobs = runningJobs(d).length;
        const expanded = open === d.name;
        const link = { self: "this device", direct: "direct", relay: "relayed", offline: "" }[d.link];
        return (
          <Fragment key={d.name}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : d.name)}
              aria-expanded={expanded}
              className={`block w-full cursor-pointer border-0 border-b border-solid border-line bg-transparent px-4 py-3 text-left font-[inherit] text-ink last:border-b-0 hover:bg-track/40 ${COLUMNS} ${state === "offline" ? "opacity-55" : ""}`}
            >
              <div className="min-w-0">
                <div className="flex items-center gap-2">
                  <HealthDot state={state} />
                  <span className="truncate text-[14px] font-medium">{d.name}</span>
                </div>
                <div className="truncate pl-4 text-[12px] text-ink-3">
                  {[osName(d.os), state === "online" ? link : state].filter(Boolean).join(" · ")}
                </div>
              </div>
              {s ? (
                <div className="mt-3 grid grid-cols-3 gap-x-4 gap-y-3 pl-4 md:contents">
                  <Cell label="CPU"><Gauge percent={s.cpu.percent} text={pct(s.cpu.percent)} /></Cell>
                  <Cell label="Memory"><Gauge percent={s.memory.percent} text={`${s.memory.used_gb} / ${s.memory.total_gb} GB`} /></Cell>
                  <Cell label="Disk"><Gauge percent={s.disk.percent} text={`${s.disk.used_gb} / ${s.disk.total_gb} GB`} /></Cell>
                  <Cell label="GPU"><Gauge percent={gpu?.util ?? null} text={gpu?.util != null ? pct(gpu.util) : ""} /></Cell>
                  <Cell label="VRAM">
                    <Gauge percent={vram} text={gpu ? `${((gpu.mem_used_mb ?? 0) / 1024).toFixed(1)} / ${((gpu.mem_total_mb ?? 0) / 1024).toFixed(0)} GB` : ""} />
                  </Cell>
                  <Cell label="Jobs"><span className={jobs ? "text-accent" : "text-ink-3"}>{jobs ? `${jobs} running` : "–"}</span></Cell>
                </div>
              ) : (
                <div className="mt-1 pl-4 text-[13px] text-ink-3 md:col-span-6 md:mt-0 md:pl-0">
                  {state === "offline" ? "Not connected to the tailnet." : d.error}
                </div>
              )}
            </button>
            {expanded && (
              <div className="border-b border-line bg-bg/60 px-4 py-3 text-[13px] last:border-b-0 md:pl-8">
                <div className="text-ink-2">
                  {[d.ip, s && `up ${uptime(s.time - s.boot_time)}`, s && `${s.cpu.cores} cores`, gpu?.name, gpu?.temp_c != null && `${Math.round(gpu.temp_c)}°C`,
                    s && `desktop control ${s.desktop.running ? "ready" : "off"}`].filter(Boolean).join(" · ")}
                </div>
                {s && s.processes.length > 0 && (
                  <table className="mt-2 w-full max-w-md border-collapse text-[12px]">
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
          </Fragment>
        );
      })}
    </div>
  );
}
