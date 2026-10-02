"use client";

import { useEffect, useRef, useState, type ReactNode } from "react";
import Architecture from "@/components/Architecture";
import { DataTable, Markdown } from "@/components/Markdown";
import { parseReport, type ParsedReport, type Signal, type Table } from "@/lib/report";

const STAGES = ["Financial Research", "SEC Filings", "Market & Comps", "Analyst", "Writer"];

type Mode = "idle" | "running" | "live" | "saved" | "error";

interface Loaded {
  report: ParsedReport;
  savedAt: string;
  origin: "live" | "saved";
}

export default function Home() {
  const [view, setView] = useState<"research" | "architecture">("research");
  const [ticker, setTicker] = useState("MU");
  const [mode, setMode] = useState<Mode>("idle");
  const [stage, setStage] = useState(0); // 1-5 while running; 6 = all done
  const [elapsed, setElapsed] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    if (mode !== "running") return;
    const start = Date.now();
    const id = setInterval(() => setElapsed(Math.round((Date.now() - start) / 1000)), 1000);
    return () => clearInterval(id);
  }, [mode]);

  async function runLive() {
    const t = ticker.trim().toUpperCase();
    if (!t) return;
    setMode("running");
    setStage(0);
    setElapsed(0);
    setError(null);
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    try {
      const res = await fetch("/api/research", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ticker: t }),
        signal: ctrl.signal,
      });
      if (!res.ok || !res.body) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error ?? `Request failed (${res.status}).`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finished = false;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          if (!line.trim()) continue;
          const ev = JSON.parse(line);
          if (ev.type === "stage") setStage(ev.index);
          if (ev.type === "done") {
            finished = true;
            setStage(6);
            setLoaded({ report: parseReport(ev.markdown), savedAt: ev.savedAt, origin: "live" });
            setMode("live");
          }
          if (ev.type === "error") throw new Error(ev.message);
        }
      }
      if (!finished) throw new Error("The research run ended without a report.");
    } catch (e) {
      if ((e as Error).name === "AbortError") return;
      setError((e as Error).message);
      setMode("error");
    } finally {
      abortRef.current = null;
    }
  }

  function cancel() {
    abortRef.current?.abort();
    setMode("idle");
    setStage(0);
  }

  async function loadSaved(t = ticker.trim().toUpperCase() || "MU") {
    setError(null);
    try {
      const res = await fetch(`/api/report?ticker=${encodeURIComponent(t)}`);
      const body = await res.json();
      if (!res.ok) throw new Error(body.error ?? "Could not load saved report.");
      setLoaded({ report: parseReport(body.markdown), savedAt: body.savedAt, origin: "saved" });
      setMode("saved");
    } catch (e) {
      setError((e as Error).message);
      setMode("error");
    }
  }

  const running = mode === "running";

  return (
    <div className="min-h-screen w-full bg-bg">
      <header className="border-b border-line bg-panel/60">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center justify-between gap-3 px-6 py-3.5">
          <div className="flex flex-wrap items-center gap-x-3 gap-y-2">
            <div className="flex items-baseline gap-3">
              <span className="text-[17px] font-semibold tracking-tight text-fg">
                Market<span className="text-accent">Mind</span>
              </span>
              <span className="text-[13px] text-muted">Agentic Equity Research</span>
            </div>
            <nav className="ml-4 flex items-center gap-1 rounded-md border border-line bg-bg/60 p-1">
              {(["research", "architecture"] as const).map((v) => (
                <button
                  key={v}
                  onClick={() => setView(v)}
                  aria-current={view === v ? "page" : undefined}
                  className={`rounded px-3.5 py-1.5 text-[13px] font-medium capitalize outline-none transition-colors focus-visible:ring-2 focus-visible:ring-accent ${
                    view === v
                      ? "bg-accent/20 text-accent-soft ring-1 ring-inset ring-accent/50"
                      : "text-muted hover:bg-accent/10 hover:text-fg"
                  }`}
                >
                  {v}
                  {v === "research" && running && view !== "research" && (
                    <span className="ml-2 inline-block h-1.5 w-1.5 rounded-full bg-accent align-middle" />
                  )}
                </button>
              ))}
            </nav>
          </div>
          <span className="hidden text-[11px] uppercase tracking-wider text-faint sm:block">
            Research tooling · not financial advice
          </span>
        </div>
      </header>

      {view === "architecture" && <Architecture />}

      <main className={`mx-auto max-w-7xl space-y-6 px-6 py-8 ${view === "research" ? "" : "hidden"}`}>
        {/* Controls */}
        <section className="rounded-md border border-line bg-panel p-5 shadow-[inset_0_1px_0_0_rgba(255,255,255,0.04)]">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(e) => {
              e.preventDefault();
              if (!running) runLive();
            }}
          >
            <label className="flex flex-col gap-1.5">
              <span className="text-[11px] font-medium uppercase tracking-wider text-muted">Ticker</span>
              <input
                value={ticker}
                onChange={(e) => setTicker(e.target.value.toUpperCase())}
                disabled={running}
                maxLength={12}
                spellCheck={false}
                className="h-11 w-40 rounded-md border border-line bg-bg px-3.5 font-mono text-[16px] font-medium tracking-wide text-fg outline-none transition-colors placeholder:text-faint hover:border-faint focus:border-accent focus:ring-2 focus:ring-accent/30 disabled:opacity-60"
              />
            </label>
            <button
              type="submit"
              disabled={running || !ticker.trim()}
              className="h-11 rounded-md bg-accent px-6 text-[14px] font-semibold text-white shadow-[0_6px_18px_-6px_rgba(111,134,255,0.6)] outline-none transition-colors hover:bg-accent-hover focus-visible:ring-2 focus-visible:ring-accent-soft focus-visible:ring-offset-2 focus-visible:ring-offset-panel disabled:cursor-not-allowed disabled:opacity-50 disabled:shadow-none"
            >
              {running ? "Running…" : "Run Research"}
            </button>
            {running ? (
              <button
                type="button"
                onClick={cancel}
                className="h-11 rounded-md border border-line bg-panel-2 px-4 text-[13px] font-medium text-fg/85 outline-none transition-colors hover:border-accent/50 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
              >
                Cancel
              </button>
            ) : (
              <button
                type="button"
                onClick={() => loadSaved()}
                className="h-11 rounded-md border border-line bg-panel-2 px-4 text-[13px] font-medium text-fg/85 outline-none transition-colors hover:border-accent/50 hover:text-fg focus-visible:ring-2 focus-visible:ring-accent"
              >
                Load saved report
              </button>
            )}
            <p className="ml-auto max-w-sm text-right text-[12px] leading-snug text-muted">
              A live run takes about 2 minutes and calls OpenAI, Tavily and SEC EDGAR from the local backend.
            </p>
          </form>

          {(running || mode === "live" || (mode === "error" && stage > 0)) && (
            <Progress stage={stage} running={running} failed={mode === "error"} elapsed={elapsed} />
          )}
        </section>

        {error && (
          <div className="rounded-md border border-rose-500/40 bg-rose-500/5 p-4 text-[13px]">
            <p className="font-medium text-rose-300">Research run failed</p>
            <pre className="mt-1 whitespace-pre-wrap font-mono text-[12px] text-rose-200/80">{error}</pre>
            <button
              onClick={() => loadSaved("MU")}
              className="mt-3 rounded-sm border border-line px-3 py-1.5 text-[12px] text-fg hover:border-faint"
            >
              Load previously generated MU report
            </button>
          </div>
        )}

        {loaded && !running && <Report data={loaded} />}

        {!loaded && !running && !error && (
          <p className="py-16 text-center text-[13px] text-faint">
            Enter a ticker and run research, or load the previously generated report.
          </p>
        )}
      </main>
    </div>
  );
}

function Progress({ stage, running, failed, elapsed }: { stage: number; running: boolean; failed: boolean; elapsed: number }) {
  return (
    <div className="mt-5 border-t border-line pt-5">
      <ol className="grid grid-cols-2 gap-3 sm:grid-cols-5">
        {STAGES.map((name, i) => {
          const n = i + 1;
          const state = n < stage || stage === 6 ? "done" : n === stage ? (failed ? "failed" : "active") : "pending";
          return (
            <li
              key={name}
              className={`flex items-center gap-2.5 rounded-sm border px-3 py-2.5 text-[13px] ${
                state === "active"
                  ? "border-accent/60 bg-accent/5 text-fg"
                  : state === "done"
                    ? "border-line text-fg/90"
                    : state === "failed"
                      ? "border-rose-500/50 text-rose-300"
                      : "border-line/60 text-faint"
              }`}
            >
              <span className="font-mono text-[11px] text-faint">{n}</span>
              <span className="flex-1">{name}</span>
              {state === "done" && <span className="text-emerald-400">✓</span>}
              {state === "active" && <span className="h-2 w-2 animate-pulse rounded-full bg-accent" />}
              {state === "failed" && <span>✕</span>}
            </li>
          );
        })}
      </ol>
      <p className="mt-3 font-mono text-[11px] text-faint">
        {running ? `Elapsed ${elapsed}s${stage === 0 ? " · starting pipeline…" : ""}` : stage === 6 ? `Completed in ${elapsed}s` : ""}
      </p>
    </div>
  );
}

const SIGNAL_STYLE: Record<string, string> = {
  BUY: "border-emerald-500/50 text-emerald-300 bg-emerald-500/[0.06]",
  HOLD: "border-amber-400/50 text-amber-200 bg-amber-400/[0.06]",
  SELL: "border-rose-500/50 text-rose-300 bg-rose-500/[0.06]",
};

function Card({ title, children, className = "", quiet = false }: { title: string; children: ReactNode; className?: string; quiet?: boolean }) {
  return (
    <section className={`rounded-md border border-line ${quiet ? "bg-transparent" : "bg-panel"} p-5 ${className}`}>
      <h2 className="mb-3.5 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">{title}</h2>
      {children}
    </section>
  );
}

function valueTone(label: string, value: string): string {
  const negative = /(^|\s)-\d/.test(value);
  if (/net income|return/i.test(label)) return negative ? "text-rose-300" : "text-emerald-300";
  return negative ? "text-rose-300" : "text-fg";
}

function chipEvidence(table: Table): Table {
  // Render the Evidence column's ids as citation chips.
  const col = table.headers.findIndex((h) => h.toLowerCase() === "evidence");
  if (col < 0) return table;
  return {
    headers: table.headers,
    rows: table.rows.map((r) =>
      r.map((cell, i) => {
        if (i !== col) return cell;
        const m = /^([A-Z]+-\d{2}(?:,\s*[A-Z]+-\d{2})*)(.*)$/.exec(cell);
        return m ? `[${m[1]}]${m[2]}` : cell;
      }),
    ),
  };
}

function Report({ data }: { data: Loaded }) {
  const r = data.report;
  const s = r.sections;
  const signalBody = (s["Signal"] ?? "").split("\n").filter((l) => !/^_.*_$/.test(l.trim())).join("\n");

  return (
    <div className="space-y-6">
      {data.origin === "saved" ? (
        <div className="rounded-md border border-amber-400/40 bg-amber-400/[0.05] px-4 py-3 text-[13px] text-amber-100">
          <span className="font-semibold">Previously generated report</span> — loaded from{" "}
          <span className="font-mono">outputs/{r.ticker}_report.md</span> (saved {fmtDate(data.savedAt)}). This is not a fresh live run.
        </div>
      ) : (
        <div className="rounded-md border border-accent/40 bg-accent/[0.05] px-4 py-3 text-[13px] text-fg/90">
          <span className="font-semibold text-accent-soft">Live run</span> — generated just now by the five-agent pipeline ({fmtDate(data.savedAt)}).
        </div>
      )}

      {/* Title + signal */}
      <section className="grid gap-6 rounded-md border border-line bg-panel p-6 md:grid-cols-[1fr_auto]">
        <div>
          <div className="flex items-center gap-3">
            <h1 className="text-[28px] font-semibold tracking-tight text-fg">{r.company}</h1>
            <span className="rounded-sm border border-line px-2 py-0.5 font-mono text-[13px] text-muted">{r.ticker}</span>
          </div>
          {r.generated && <p className="mt-1 font-mono text-[11px] text-faint">Report generated {r.generated}</p>}
          <div className="mt-4 max-w-3xl">
            <Markdown text={s["Company Overview"] ?? ""} />
          </div>
        </div>
        <SignalBadge signal={r.signal} />
      </section>

      {/* Key metrics */}
      {r.keyFinancials && (
        <Card title="Key Financials">
          <div className="grid grid-cols-2 gap-px overflow-hidden rounded-sm border border-line bg-line sm:grid-cols-3 lg:grid-cols-6">
            {r.keyFinancials.rows.map(([label, value]) => (
              <div key={label} className="bg-panel px-3.5 py-3">
                <div className="text-[11px] leading-tight text-muted">{label}</div>
                <div className={`mt-1 font-mono text-[15px] tabular-nums ${valueTone(label, value)}`}>{value}</div>
              </div>
            ))}
          </div>
          <Markdown text={r.keyFinancialsNotes} className="mt-4" />
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <div className="space-y-6 lg:col-span-2">
          <Card title="Investment Thesis">
            <Markdown text={s["Investment Thesis"] ?? ""} className="text-[15px]" />
          </Card>
          <div className="grid gap-6 md:grid-cols-2">
            <Card title="Evidence Supporting the Thesis">
              <Markdown text={s["Evidence Supporting the Thesis"] ?? ""} />
            </Card>
            <Card title="Challenges / Bear Case">
              <Markdown text={s["Challenges / Bear Case"] ?? ""} />
            </Card>
          </div>
        </div>
        <div className="space-y-6">
          <Card title={`Signal reasoning · ${r.signal ?? "n/a"}`}>
            <Markdown text={signalBody} />
            <p className="mt-3 text-[11px] italic text-faint">
              A research signal based only on the supplied evidence; not personalised financial advice.
            </p>
          </Card>
          <Card title="What Would Change the View?">
            <Markdown text={s["What Would Change the View?"] ?? ""} />
          </Card>
          {s["Open Questions"] && (
            <Card title="Open Questions">
              <Markdown text={s["Open Questions"]} />
            </Card>
          )}
        </div>
      </div>

      {r.comps && (
        <Card title="Comparable Companies">
          <DataTable table={chipEvidence(r.comps)} />
          <Markdown text={r.compsNotes} className="mt-5" />
        </Card>
      )}

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title="SEC Risk Factors">
          <Markdown text={s["SEC Risk Factors"] ?? ""} />
        </Card>
        <Card title="Recent Company Developments">
          <Markdown text={s["Recent Company Developments"] ?? ""} />
        </Card>
        <Card title="Industry Context">
          <Markdown text={s["Industry Context"] ?? ""} />
        </Card>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card title={`Sources · ${r.sources.length}`} className="lg:col-span-2" quiet>
          <ul className="space-y-2">
            {r.sources.map((src) => (
              <li key={src.id} id={`src-${src.id}`} className="grid scroll-mt-6 grid-cols-[76px_1fr] gap-3 text-[12px] leading-snug target:bg-accent/10">
                <span className="font-mono text-accent-soft">{src.id}</span>
                <span className="min-w-0 text-muted">
                  <span className="text-fg/80">{src.title}</span>
                  {src.date && <span className="text-faint"> · {src.date}</span>}
                  {src.url && (
                    <a href={src.url} target="_blank" rel="noreferrer" className="block truncate text-faint hover:text-accent-soft">
                      {src.url}
                    </a>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </Card>
        <div className="space-y-6">
          {r.usage.length > 0 && (
            <Card title="Token Usage" quiet>
              <table className="w-full text-[12px]">
                <thead>
                  <tr className="text-left text-[10px] uppercase tracking-wider text-faint">
                    <th className="pb-2 font-medium">Agent</th>
                    <th className="pb-2 text-right font-medium">In</th>
                    <th className="pb-2 text-right font-medium">Out</th>
                    <th className="pb-2 text-right font-medium">Total</th>
                  </tr>
                </thead>
                <tbody className="font-mono tabular-nums">
                  {r.usage.map((u) => (
                    <tr key={u.agent} className={u.agent === "Combined" ? "border-t border-line text-fg" : "text-muted"}>
                      <td className="py-1 font-sans">{u.agent.replace(/Agent$/, "")}</td>
                      <td className="py-1 text-right">{u.input}</td>
                      <td className="py-1 text-right">{u.output}</td>
                      <td className="py-1 text-right">{u.total}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {r.tavilyRequests && <p className="mt-3 text-[11px] text-faint">Tavily requests: {r.tavilyRequests}</p>}
            </Card>
          )}
          <Card title="Data Limitations" quiet>
            <Markdown text={s["Data Limitations"] ?? ""} className="text-[12px] text-muted" />
          </Card>
        </div>
      </div>
    </div>
  );
}

function SignalBadge({ signal }: { signal: Signal }) {
  return (
    <div className={`flex min-w-44 flex-col items-center justify-center rounded-md border px-8 py-5 ${SIGNAL_STYLE[signal ?? ""] ?? "border-line text-muted"}`}>
      <span className="text-[10px] font-semibold uppercase tracking-[0.18em] opacity-80">Research signal</span>
      <span className="mt-1 text-[38px] font-semibold leading-none tracking-tight">{signal ?? "—"}</span>
    </div>
  );
}

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });
}

