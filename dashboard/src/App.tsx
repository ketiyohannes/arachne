import { useEffect, useMemo, useState } from "react";
import { Panel, Tabs } from "./components/bits";
import { Devices } from "./components/Devices";
import { RunningNow, Trace } from "./components/Trace";
import { demoState } from "./demo";
import { trace } from "./format";
import type { State } from "./types";

const DEMO = new URLSearchParams(location.search).has("demo");

type Tab = "resources" | "running" | "trace";
const TABS: Tab[] = ["resources", "running", "trace"];
const tabFromHash = (): Tab => TABS.find((t) => t === location.hash.slice(1)) ?? "resources";

function useFleet(): { state: State | null; stale: boolean } {
  const [state, setState] = useState<State | null>(DEMO ? demoState() : null);
  const [stale, setStale] = useState(false);
  useEffect(() => {
    if (DEMO) return;
    let timer: number;
    let stopped = false;
    const tick = async () => {
      let wait = 5;
      try {
        const next: State = await (await fetch("/api/state", { cache: "no-store" })).json();
        wait = next.starting ? 1 : next.interval ?? 5;
        if (!next.starting) setState(next);
        setStale(false);
      } catch {
        setStale(true);
      }
      if (!stopped) timer = window.setTimeout(tick, wait * 1000);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, []);
  return { state, stale };
}

/** Current time in epoch seconds, ticking so "running for 12s" keeps counting between refreshes. */
function useNow(): number {
  const [now, setNow] = useState(Date.now() / 1000);
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

function Filter({ label, value, options, onChange }: { label: string; value: string; options: string[]; onChange: (v: string) => void }) {
  return (
    <select
      aria-label={label}
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="rounded-md border border-line bg-panel px-1.5 py-1 font-[inherit] text-[12px] text-ink"
    >
      <option value="">{label}</option>
      {options.map((o) => <option key={o} value={o}>{o}</option>)}
    </select>
  );
}

export function App() {
  const { state, stale } = useFleet();
  const now = useNow();
  const [tab, setTab] = useState<Tab>(tabFromHash);
  const [device, setDevice] = useState("");
  const [actor, setActor] = useState("");

  // The tab lives in the URL, so a reload or a shared link opens the same view.
  const showTab = (next: Tab) => {
    setTab(next);
    history.replaceState(null, "", `${location.pathname}${location.search}#${next}`);
  };

  const devices = state?.devices ?? [];
  const items = useMemo(() => trace(devices), [devices]);
  const running = items.filter((i) => i.status === "running");
  const actors = [...new Set(items.map((i) => i.actor).filter(Boolean))].sort();
  const shown = items.filter((i) => (!device || i.device === device) && (!actor || i.actor === actor));
  const online = devices.filter((d) => d.online).length;

  let warning = state?.error ?? "";
  if (!warning && state?.tailscale && state.tailscale !== "Running") {
    warning = `Tailscale is ${state.tailscale.toLowerCase()} on this machine, so other devices cannot be reached. Run "tailscale up" or open the Tailscale app.`;
  }

  return (
    <div className="mx-auto max-w-[1200px] px-3 pb-10 pt-4 sm:px-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="m-0 text-[16px] font-semibold">arachne</h1>
        {state?.tailnet && <span className="text-[13px] text-ink-3">{state.tailnet}</span>}
        <span className={`ml-auto text-[12px] ${stale ? "text-bad" : "text-ink-3"}`}>
          {stale
            ? "dashboard server not responding"
            : state
              ? `${DEMO ? "demo data" : "updated"} ${new Date(state.generated * 1000).toLocaleTimeString()}`
              : "loading…"}
        </span>
      </header>

      {warning && (
        <p className="mb-0 mt-3 rounded-lg border border-line border-l-[3px] border-l-warn bg-panel px-3 py-2 text-[13px]">{warning}</p>
      )}

      {devices.length > 0 && (
        <>
          <Tabs
            active={tab}
            onChange={showTab}
            tabs={[
              { id: "resources", label: "Resources" },
              { id: "running", label: "Running", count: running.length },
              { id: "trace", label: "Trace" },
            ]}
          />

          {tab === "resources" && (
            <Panel aside={`${online} of ${devices.length} online`}>
              <Devices devices={devices} />
            </Panel>
          )}

          {tab === "running" && (
            <Panel>
              <RunningNow items={running} demo={DEMO} now={now} />
            </Panel>
          )}

          {tab === "trace" && (
            <Panel
              aside={
                <>
                  <Filter label="All devices" value={device} options={devices.map((d) => d.name)} onChange={setDevice} />
                  {actors.length > 1 && <Filter label="Anyone" value={actor} options={actors} onChange={setActor} />}
                </>
              }
            >
              <Trace items={shown.slice(0, 60)} demo={DEMO} />
            </Panel>
          )}
        </>
      )}
    </div>
  );
}
