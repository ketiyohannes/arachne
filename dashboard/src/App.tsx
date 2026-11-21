import { useEffect, useMemo, useState } from "react";
import { ApiError, adoptKeyFromLink, getJson, saveKey } from "./api";
import { Panel, Stat, Tabs } from "./components/bits";
import { Devices } from "./components/Devices";
import { RunningNow, Trace } from "./components/Trace";
import { demoState } from "./demo";
import { trace } from "./format";
import type { State } from "./types";

const DEMO = new URLSearchParams(location.search).has("demo");

type Tab = "resources" | "running" | "trace";
const TABS: Tab[] = ["resources", "running", "trace"];
adoptKeyFromLink();

const tabFromHash = (): Tab => TABS.find((t) => t === location.hash.slice(1)) ?? "resources";

/** ok: live data. locked: the hosted proxy wants an access key. waking: the hub is resuming. down: no answer. */
type Link = "ok" | "locked" | "waking" | "down";

function useFleet(attempt: number): { state: State | null; link: Link } {
  const [state, setState] = useState<State | null>(DEMO ? demoState() : null);
  const [link, setLink] = useState<Link>("ok");
  useEffect(() => {
    if (DEMO) return;
    let timer: number;
    let stopped = false;
    const tick = async () => {
      let wait = 5;
      try {
        const next = await getJson<State>("/api/state");
        wait = next.starting ? 1 : next.interval ?? 5;
        if (!next.starting) setState(next);
        setLink("ok");
      } catch (e) {
        const status = e instanceof ApiError ? e.status : 0;
        setLink(status === 401 ? "locked" : status === 503 ? "waking" : "down");
        if (status === 401) return; // wait for a key instead of retrying
      }
      if (!stopped) timer = window.setTimeout(tick, wait * 1000);
    };
    tick();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [attempt]);
  return { state, link };
}

function KeyPrompt({ onSubmit }: { onSubmit: (key: string) => void }) {
  const [value, setValue] = useState("");
  return (
    <form
      className="mx-auto mt-[18vh] max-w-sm rounded-xl border border-line bg-panel p-5"
      onSubmit={(e) => {
        e.preventDefault();
        if (value.trim()) onSubmit(value);
      }}
    >
      <h1 className="m-0 text-[16px] font-semibold">arachne</h1>
      <p className="mb-3 mt-1 text-[13px] text-ink-2">Enter the access key for this dashboard. It is remembered on this device.</p>
      <input
        type="password"
        autoFocus
        autoComplete="current-password"
        aria-label="Access key"
        placeholder="Access key"
        value={value}
        onChange={(e) => setValue(e.target.value)}
        className="box-border w-full rounded-md border border-solid border-line bg-bg px-3 py-2 font-[inherit] text-[16px] text-ink"
      />
      <button type="submit" className="mt-3 w-full cursor-pointer rounded-md border-0 bg-accent px-3 py-2 font-[inherit] text-[14px] font-medium text-white">
        Open dashboard
      </button>
    </form>
  );
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
  const [attempt, setAttempt] = useState(0);
  const { state, link } = useFleet(attempt);
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
  const lastDay = items.filter((i) => i.started > now - 86_400);
  const failed = lastDay.filter((i) => i.status === "failed" || i.status === "lost").length;
  const age = state ? Math.max(0, Math.round(now - state.generated)) : 0;

  if (link === "locked") {
    return (
      <KeyPrompt
        onSubmit={(key) => {
          saveKey(key);
          setAttempt(attempt + 1);
        }}
      />
    );
  }

  let warning = state?.error ?? "";
  if (!warning && state?.tailscale && state.tailscale !== "Running") {
    warning = `Tailscale is ${state.tailscale.toLowerCase()} on this machine, so other devices cannot be reached. Run "tailscale up" or open the Tailscale app.`;
  }

  return (
    <div className="mx-auto max-w-[1200px] px-3 pb-10 pt-4 sm:px-5">
      <header className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h1 className="m-0 text-[17px] font-semibold tracking-tight">arachne</h1>
        {state?.tailnet && <span className="text-[13px] text-ink-3">{state.tailnet}</span>}
        <span className={`ml-auto flex items-center gap-1.5 text-[12px] ${link === "down" ? "text-bad" : "text-ink-3"}`}>
          {link === "ok" && state && <span className={`inline-block size-1.5 rounded-full ${age < 30 ? "animate-pulse bg-good" : "bg-warn"}`} />}
          {link === "down"
            ? "dashboard server not responding"
            : link === "waking"
              ? "hub is waking up…"
              : state
                ? DEMO ? "demo data" : age < 30 ? "live" : `last update ${age}s ago`
                : "loading…"}
        </span>
      </header>

      {link === "waking" && !state && (
        <p className="mt-3 rounded-xl border border-line bg-panel px-4 py-3 text-[13px] text-ink-2">
          The hub was asleep and is starting. This page fills in by itself, usually within a minute.
        </p>
      )}

      {warning && (
        <p className="mb-0 mt-3 rounded-lg border border-line border-l-[3px] border-l-warn bg-panel px-3 py-2 text-[13px]">{warning}</p>
      )}

      {devices.length > 0 && (
        <>
          <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Devices online" value={<>{online}<span className="text-ink-3"> / {devices.length}</span></>} onClick={() => showTab("resources")} />
            <Stat label="Running now" value={running.length} tone={running.length ? "accent" : undefined} detail={running[0]?.device} onClick={() => showTab("running")} />
            <Stat label="Commands, 24 h" value={lastDay.length} detail={items[0] ? `latest on ${items[0].device}` : undefined} onClick={() => showTab("trace")} />
            <Stat label="Failed, 24 h" value={failed} tone={failed ? "bad" : undefined} onClick={() => showTab("trace")} />
          </div>

          <Tabs
            active={tab}
            onChange={showTab}
            tabs={[
              { id: "resources", label: "Resources" },
              { id: "running", label: "Running", count: running.length },
              { id: "trace", label: "Trace" },
            ]}
          />

          {tab === "resources" && <Devices devices={devices} items={items} />}

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
