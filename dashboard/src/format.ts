import type { Device } from "./types";

const OS_NAMES: Record<string, string> = { macos: "macOS", windows: "Windows", linux: "Linux", ios: "iOS", android: "Android" };

export const osName = (os: string) => OS_NAMES[os] ?? os;
export const pct = (n: number) => `${Math.round(n)}%`;

export function ago(ts?: number): string {
  if (!ts) return "";
  const s = Math.max(0, Date.now() / 1000 - ts);
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

export function uptime(seconds: number): string {
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

export type Health = "online" | "unreachable" | "offline";

export function health(d: Device): Health {
  if (!d.online) return "offline";
  return d.error ? "unreachable" : "online";
}

/** Elapsed time between two epoch seconds, e.g. "42s", "3m 05s", "2h 10m". */
export function duration(from: number, to: number): string {
  const s = Math.max(0, Math.round(to - from));
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.floor(s / 60)}m ${String(s % 60).padStart(2, "0")}s`;
  return `${Math.floor(s / 3600)}h ${String(Math.floor((s % 3600) / 60)).padStart(2, "0")}m`;
}

export type TraceStatus = "running" | "ok" | "failed" | "killed" | "lost";

/** One thing that was run on a device: a command, a desktop action or a detached job. */
export interface TraceItem {
  key: string;
  id: string;
  kind: "run" | "desktop" | "job";
  device: string;
  from: string;
  actor: string;
  command: string;
  name?: string;
  status: TraceStatus;
  exit?: number | null;
  started: number;
  ended?: number;
}

export function trace(devices: Device[]): TraceItem[] {
  const items: TraceItem[] = [];
  for (const d of devices) {
    for (const a of d.stats?.activity ?? []) {
      const running = !("exit" in a);
      items.push({
        key: `${d.name}/run/${a.id}`, id: a.id, kind: a.kind ?? "run", device: d.name, from: a.from, actor: a.actor ?? "",
        command: a.command, started: a.ts, ended: a.end, exit: a.exit,
        status: running ? "running" : a.exit === 0 ? "ok" : a.exit == null ? "lost" : "failed",
      });
    }
    for (const j of d.stats?.jobs ?? []) {
      items.push({
        key: `${d.name}/job/${j.id}`, id: j.id, kind: "job", device: d.name, from: j.from ?? d.name, actor: j.actor ?? "",
        command: j.command, name: j.name, started: j.started, ended: j.ended, exit: j.exit,
        status: j.status === "done" ? "ok" : j.status,
      });
    }
  }
  return items.sort((a, b) => b.started - a.started);
}

export const runningJobs = (d: Device) => (d.stats?.jobs ?? []).filter((j) => j.status === "running");
