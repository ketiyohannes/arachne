import { useEffect, useRef, useState } from "react";
import { demoOutput } from "../demo";
import { ago, duration, type TraceItem } from "../format";
import { StatusTag } from "./bits";

interface Output {
  text: string;
  truncated?: boolean;
  missing?: boolean;
  error?: string;
}

/** What a command printed, fetched from its device; refreshed while the command is still running. */
function OutputView({ item, demo, lines }: { item: TraceItem; demo: boolean; lines?: number }) {
  const [output, setOutput] = useState<Output | null>(null);
  const box = useRef<HTMLPreElement>(null);
  const running = item.status === "running";

  useEffect(() => {
    let stopped = false;
    let timer: number;
    const load = async () => {
      try {
        const kind = item.kind === "job" ? "job" : "run";
        const next: Output = demo
          ? demoOutput(item)
          : await (await fetch(`/api/output?device=${encodeURIComponent(item.device)}&id=${encodeURIComponent(item.id)}&kind=${kind}`)).json();
        if (!stopped) setOutput(next);
      } catch {
        if (!stopped) setOutput({ text: "", error: "could not load the output" });
      }
      if (!stopped && running) timer = window.setTimeout(load, 3000);
    };
    load();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [item.device, item.id, item.kind, running, demo]);

  // Keep the newest lines in view, like `tail -f`.
  useEffect(() => {
    if (box.current) box.current.scrollTop = box.current.scrollHeight;
  }, [output]);

  if (!output) return <p className="m-0 text-[12px] text-ink-3">Loading output…</p>;
  if (output.error) return <p className="m-0 text-[12px] text-bad">{output.error}</p>;
  let text = output.text.replace(/\n+$/, "");
  if (lines) text = text.split("\n").slice(-lines).join("\n");
  if (!text) {
    return (
      <p className="m-0 text-[12px] text-ink-3">
        {output.missing ? "No output was recorded (run from a terminal, or already cleaned up)." : running ? "No output yet." : "No output."}
      </p>
    );
  }
  return (
    <>
      {output.truncated && !lines && <p className="m-0 mb-1 text-[12px] text-ink-3">Showing the end of a longer output.</p>}
      <pre
        ref={box}
        className={`m-0 overflow-auto whitespace-pre-wrap break-words rounded-md border border-line bg-bg p-2.5 font-mono text-[12px] leading-[1.5] ${lines ? "max-h-52" : "max-h-96"}`}
      >
        {text}
      </pre>
    </>
  );
}

function Who({ item }: { item: TraceItem }) {
  const route = item.from === item.device ? item.device : `${item.from} → ${item.device}`;
  return (
    <span className="min-w-0 truncate">
      {item.actor && item.actor !== "you" && item.actor !== "script" && (
        <span className="mr-1.5 rounded border border-line px-1 py-px text-[11px] text-ink-2">{item.actor}</span>
      )}
      {route}
    </span>
  );
}

const KIND_LABEL = { run: "", desktop: "desktop", job: "job" };

/** Everything still running, each with a live tail of its output. */
export function RunningNow({ items, demo, now }: { items: TraceItem[]; demo: boolean; now: number }) {
  if (items.length === 0) return <p className="m-0 px-4 py-3 text-[13px] text-ink-3">Nothing is running.</p>;
  return (
    <ul className="m-0 list-none divide-y divide-line p-0">
      {items.map((item) => (
        <li key={item.key} className="px-4 py-3">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-0.5 text-[12px] text-ink-3">
            <Who item={item} />
            {KIND_LABEL[item.kind] && <span>{KIND_LABEL[item.kind]}{item.name && item.name !== item.id ? ` ${item.name}` : ""}</span>}
            <span className="ml-auto shrink-0">running for {duration(item.started, now)}</span>
          </div>
          <code className="mb-2 mt-1 block break-all font-mono text-[13px]">{item.command}</code>
          <OutputView item={item} demo={demo} lines={12} />
        </li>
      ))}
    </ul>
  );
}

/** History of commands, jobs and desktop actions, newest first. Click a row for its output. */
export function Trace({ items, demo }: { items: TraceItem[]; demo: boolean }) {
  const [open, setOpen] = useState<string | null>(null);
  if (items.length === 0) return <p className="m-0 px-4 py-3 text-[13px] text-ink-3">Nothing matches. Commands run through arachne appear here.</p>;
  return (
    <ul className="m-0 list-none divide-y divide-line p-0">
      {items.map((item) => {
        const expanded = open === item.key;
        return (
          <li key={item.key}>
            <button
              type="button"
              onClick={() => setOpen(expanded ? null : item.key)}
              aria-expanded={expanded}
              className="block w-full cursor-pointer border-0 bg-transparent px-4 py-2 text-left font-[inherit] text-ink hover:bg-track/40"
            >
              <code className={`block font-mono text-[13px] ${expanded ? "break-all" : "truncate"}`}>
                {KIND_LABEL[item.kind] && item.kind === "job" && <span className="font-sans font-medium">{item.name} </span>}
                {item.command}
              </code>
              <div className="mt-0.5 flex items-baseline gap-3 text-[12px] text-ink-3">
                <Who item={item} />
                <StatusTag item={item} />
                {item.ended !== undefined && <span className="shrink-0 max-sm:hidden">took {duration(item.started, item.ended)}</span>}
                <span className="ml-auto shrink-0">{ago(item.started)} ago</span>
              </div>
            </button>
            {expanded && (
              <div className="px-4 pb-3">
                <OutputView item={item} demo={demo} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
