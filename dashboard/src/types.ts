/** Shapes served by `arachne dashboard` at /api/state. */

export type JobStatus = "running" | "done" | "failed" | "killed" | "lost";

export interface Job {
  id: string;
  name: string;
  command: string;
  status: JobStatus;
  started: number;
  ended?: number;
  exit?: number | null;
  from?: string;
  actor?: string | null;
}

export interface Activity {
  id: string;
  ts: number;
  from: string;
  kind?: "run" | "desktop";
  /** Who issued it: an agent's name, "you" or "script". */
  actor?: string | null;
  command: string;
  /** Absent while the command is still running; null when its runner vanished. */
  exit?: number | null;
  end?: number;
}

export interface Gpu {
  name: string;
  util: number | null;
  mem_used_mb: number | null;
  mem_total_mb: number | null;
  temp_c: number | null;
}

export interface Stats {
  time: number;
  boot_time: number;
  cpu: { percent: number; cores: number };
  memory: { percent: number; used_gb: number; total_gb: number };
  disk: { percent: number; used_gb: number; total_gb: number };
  gpus: Gpu[];
  processes: { pid: number; name: string; cpu: number; mem_mb: number }[];
  jobs: Job[];
  activity: Activity[];
  desktop: { running: boolean; installed: boolean };
}

export interface Device {
  name: string;
  ip: string;
  os: string;
  online: boolean;
  self: boolean;
  link: "self" | "direct" | "relay" | "offline";
  relay: string;
  stats?: Stats;
  error?: string;
}

export interface State {
  generated: number;
  interval?: number;
  starting?: boolean;
  tailnet?: string;
  tailscale?: string;
  error?: string;
  devices: Device[];
}
