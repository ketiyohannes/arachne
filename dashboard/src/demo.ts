import type { TraceItem } from "./format";
import type { Device, State, Stats } from "./types";

/** A made-up fleet, shown with `?demo` so the layout can be previewed before real devices exist. */
export function demoState(): State {
  const now = Date.now() / 1000;
  const stats = (cpu: number, cores: number, mem: [number, number], disk: [number, number], extra: Partial<Stats> = {}): Stats => ({
    time: now, boot_time: now - 380_000,
    cpu: { percent: cpu, cores },
    memory: { percent: (100 * mem[0]) / mem[1], used_gb: mem[0], total_gb: mem[1] },
    disk: { percent: (100 * disk[0]) / disk[1], used_gb: disk[0], total_gb: disk[1] },
    gpus: [], processes: [], jobs: [], activity: [], desktop: { running: true, installed: true },
    ...extra,
  });

  const devices: Device[] = [
    {
      name: "macbook", ip: "100.64.0.1", os: "macos", online: true, self: true, link: "self", relay: "",
      stats: stats(19, 10, [7.9, 17.2], [419, 494], {
        processes: [{ pid: 1, name: "claude", cpu: 22, mem_mb: 610 }, { pid: 2, name: "zen", cpu: 14, mem_mb: 392 }, { pid: 3, name: "Tailscale", cpu: 2, mem_mb: 88 }],
        activity: [{ id: "m1", ts: now - 47, from: "macbook", actor: "you", command: "uv run pytest -q", exit: 0, end: now - 44 }],
      }),
    },
    {
      name: "desktop", ip: "100.64.0.2", os: "windows", online: true, self: false, link: "direct", relay: "fra",
      stats: stats(63, 16, [15.4, 32], [710, 1000], {
        gpus: [{ name: "NVIDIA GeForce RTX 4070", util: 97, mem_used_mb: 10240, mem_total_mb: 12282, temp_c: 71 }],
        processes: [{ pid: 4, name: "python.exe", cpu: 380, mem_mb: 9120 }, { pid: 5, name: "explorer.exe", cpu: 3, mem_mb: 210 }],
        jobs: [
          { id: "ab12cd", name: "finetune", command: "uv run train.py --epochs 3 --lora", status: "running", started: now - 1900, from: "macbook", actor: "claude-code" },
          { id: "ee01aa", name: "ci", command: "cargo test --workspace", status: "failed", exit: 101, started: now - 9000, from: "macbook" },
        ],
        activity: [
          { id: "d1", ts: now - 6, from: "macbook", actor: "claude-code", command: "nvidia-smi --query-gpu=utilization.gpu,memory.used --format=csv" },
          { id: "d2", ts: now - 300, from: "macbook", actor: "claude-code", command: "git pull && uv sync", exit: 0, end: now - 280 },
          { id: "d4", ts: now - 600, from: "macbook", actor: "claude-code", kind: "desktop", command: "agent-desktop snapshot --app Notepad -i", exit: 0, end: now - 598 },
          { id: "d3", ts: now - 900, from: "studio", command: "pytest tests/test_gpu.py", exit: 2, end: now - 880 },
        ],
      }),
    },
    {
      name: "studio", ip: "100.64.0.5", os: "macos", online: true, self: false, link: "direct", relay: "lhr",
      stats: stats(41, 12, [39.1, 64], [1210, 2000], {
        processes: [{ pid: 6, name: "xcodebuild", cpu: 290, mem_mb: 4100 }, { pid: 7, name: "Simulator", cpu: 31, mem_mb: 1900 }],
        jobs: [{ id: "77aa10", name: "ios-build", command: "xcodebuild -scheme App -configuration Release", status: "done", exit: 0, started: now - 4000, from: "macbook" }],
        activity: [{ id: "s1", ts: now - 120, from: "macbook", command: "xcodebuild -scheme App test", exit: 0, end: now - 15 }],
      }),
    },
    {
      name: "devbox", ip: "100.64.0.3", os: "linux", online: true, self: false, link: "relay", relay: "lhr",
      error: "could not open an SSH session to devbox (100.64.0.3). Check that its SSH server is on and your key is authorized (`arachne setup` there).",
    },
    { name: "deck", ip: "100.64.0.4", os: "linux", online: false, self: false, link: "offline", relay: "lhr" },
  ];
  // A plausible ten minutes of load around each device's current reading.
  for (const d of devices) {
    const s = d.stats;
    if (!s) continue;
    const wobble = (base: number, i: number, seed: number) =>
      Math.max(1, Math.min(100, base + 14 * Math.sin(i / 7 + seed) + 6 * Math.sin(i / 2.3 + seed * 3)));
    d.history = Array.from({ length: 120 }, (_, i) => [
      now - (119 - i) * 5,
      i === 119 ? s.cpu.percent : wobble(s.cpu.percent, i, d.name.length),
      i === 119 ? s.memory.percent : wobble(s.memory.percent, i / 4, d.name.length + 2),
      s.gpus[0]?.util != null ? (i === 119 ? s.gpus[0].util : wobble(s.gpus[0].util, i, 1)) : null,
    ]);
  }
  return { generated: now, interval: 5, tailnet: "tail0000.ts.net", tailscale: "Running", devices };
}

export function demoOutput(item: TraceItem): { text: string; missing?: boolean } {
  if (item.name === "finetune") {
    return { text: Array.from({ length: 14 }, (_, i) => `step ${1180 + i * 10}/3000  loss ${(1.42 - i * 0.011).toFixed(3)}  lr 1.8e-4  3.1 it/s`).join("\n") };
  }
  if (item.status === "failed") return { text: "FAILED tests/test_gpu.py::test_cuda_available - AssertionError\n1 failed, 7 passed in 4.21s" };
  if (item.kind === "desktop") return { text: '{"version":"2.6","ok":true,"command":"snapshot","data":{"app":"Notepad","ref_count":12}}' };
  if (item.id === "m1") return { text: "", missing: true };
  return { text: "Already up to date.\nResolved 42 packages in 12ms\nAudited 42 packages in 3ms" };
}
