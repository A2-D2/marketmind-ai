"use client";

// Static, interactive explanation of the existing pipeline (no API calls).
// Stages: 1 Research · 2 Verify · 3 Synthesize. Keys 1/2/3 select a stage, 0/Esc shows all.
import { useEffect, useState, type ReactNode } from "react";

type StageId = "research" | "verify" | "synthesize";
type NodeId =
  | "ticker" | "orchestrator" | "financial" | "filings" | "market"
  | "validation" | "analyst" | "writer" | "ui";

const STAGES: { id: StageId; n: number; label: string; text: string }[] = [
  {
    id: "research",
    n: 1,
    label: "Research",
    text:
      "The orchestrator runs three specialist agents in a fixed sequence. Each agent reasons only over " +
      "bounded evidence fetched by its own retrieval layer: yfinance data, SEC 10-K risk factors, and Tavily web excerpts.",
  },
  {
    id: "verify",
    n: 2,
    label: "Verify",
    text:
      "Deterministic Python sits between the LLMs and the report. It computes the numbers, assigns source IDs, " +
      "checks every citation, verifies peers and resolves tickers, and allows exactly one corrective retry.",
  },
  {
    id: "synthesize",
    n: 3,
    label: "Synthesize",
    text:
      "The Analyst weighs only the verified outputs into thesis support, challenges, risks and a BUY / HOLD / SELL " +
      "research signal. The Writer turns that into a readable, cited report shown in the MarketMind UI.",
  },
];

const NODES: Record<NodeId, { title: string; stage: StageId | null; text: string }> = {
  ticker: { title: "Ticker", stage: null, text: "Any listed ticker. MU is the demo company." },
  orchestrator: {
    title: "Orchestrator",
    stage: null,
    text: "A sequential, deterministic Python pipeline with no autonomous router. A failed research stage is recorded and the run continues.",
  },
  financial: {
    title: "Financial Research Agent",
    stage: "research",
    text: "Interprets a yfinance snapshot (price history, TTM fundamentals, valuation ratios) and cites only the supplied values.",
  },
  filings: {
    title: "Filings / Risk Agent",
    stage: "research",
    text: "Reads bounded excerpts of the latest 10-K Item 1A via edgartools. Every finding cites an RF-xx excerpt, and quotes must be verbatim.",
  },
  market: {
    title: "Market & Comps Agent",
    stage: "research",
    text: "Runs three bounded Tavily searches (peers, company news, industry news). It proposes peer names only; tickers and metrics come from yfinance.",
  },
  validation: {
    title: "Deterministic Validation Layer",
    stage: "verify",
    text: "Plain Python with no LLM. It controls the numbers, sources and peers, and records why any retry happened.",
  },
  analyst: {
    title: "Analyst Agent",
    stage: "synthesize",
    text: "Synthesises only upstream outputs. Each claim is marked fact or interpretation and cites a source ID.",
  },
  writer: {
    title: "Writer Agent",
    stage: "synthesize",
    text: "Formats the analysis into report prose with inline citations. Tables, sources and URLs are rendered by code.",
  },
  ui: {
    title: "MarketMind UI",
    stage: "synthesize",
    text: "This Next.js frontend streams pipeline progress and renders the cited report.",
  },
};

const CONTROLS = [
  "Calculations",
  "Source / evidence IDs",
  "Citation validation",
  "Peer verification & ticker resolution",
  "One corrective retry",
  "Token tracking",
];

const isLit = (stage: StageId | null, s: StageId | null) => stage === null || s === stage;

interface BoxProps {
  id: NodeId;
  stage: StageId | null;
  node: NodeId | null;
  onSelect: (id: NodeId) => void;
  children?: ReactNode;
  className?: string;
}

function Box({ id, stage, node, onSelect, children, className = "" }: BoxProps) {
  const on = isLit(stage, NODES[id].stage);
  const selected = node === id;
  const emphasised = stage !== null && NODES[id].stage === stage;
  return (
    <button
      type="button"
      onClick={() => onSelect(id)}
      className={`w-full rounded-md border bg-panel px-3.5 py-3 text-left outline-none transition-[opacity,border-color,background-color] duration-200 focus-visible:ring-1 focus-visible:ring-accent ${
        on ? "opacity-100" : "opacity-30"
      } ${
        selected
          ? "border-accent bg-accent/[0.08]"
          : emphasised
            ? "border-accent/60 bg-accent/[0.04]"
            : "border-line hover:border-faint"
      } ${className}`}
    >
      <div className="text-[13px] font-semibold leading-tight text-fg">{NODES[id].title}</div>
      {children}
    </button>
  );
}

function Source({ children, s, stage }: { children: ReactNode; s: StageId; stage: StageId | null }) {
  return (
    <span
      className={`rounded-sm border px-1.5 py-0.5 font-mono text-[10.5px] transition-colors duration-200 ${
        stage === s ? "border-accent/50 text-accent-soft" : "border-line text-muted"
      }`}
    >
      {children}
    </span>
  );
}

function Arrow({ dim = false }: { dim?: boolean }) {
  return (
    <div className={`flex shrink-0 items-center justify-center px-1 text-faint transition-opacity duration-200 ${dim ? "opacity-30" : ""}`}>
      <svg width="22" height="10" viewBox="0 0 22 10" fill="none" aria-hidden>
        <path d="M0 5h19M15 1l4 4-4 4" stroke="currentColor" strokeWidth="1.3" />
      </svg>
    </div>
  );
}

export default function Architecture() {
  const [stage, setStage] = useState<StageId | null>(null);
  const [node, setNode] = useState<NodeId | null>(null);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.target instanceof HTMLInputElement) return;
      const pick = { "1": "research", "2": "verify", "3": "synthesize" }[e.key] as StageId | undefined;
      if (pick) selectStage(pick);
      if (e.key === "0" || e.key === "Escape") selectStage(null);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  function selectStage(s: StageId | null) {
    setStage(s);
    setNode(null);
  }

  function selectNode(id: NodeId) {
    setNode(id);
    const s = NODES[id].stage;
    if (s) setStage(s);
  }

  const lit = (s: StageId | null) => isLit(stage, s);
  const active = STAGES.find((s) => s.id === stage);

  const p = { stage, node, onSelect: selectNode };

  return (
    <main className="mx-auto max-w-7xl px-6 py-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-fg">How MarketMind works</h1>
          <p className="mt-1 text-[13px] text-muted">
            LLM agents reason; deterministic Python controls numbers, sources and validation.
          </p>
        </div>
        <div className="flex items-center gap-2">
          {STAGES.map((s) => (
            <button
              key={s.id}
              onClick={() => selectStage(stage === s.id ? null : s.id)}
              className={`flex items-center gap-2 rounded-sm border px-3.5 py-2 text-[13px] transition-colors duration-200 ${
                stage === s.id ? "border-accent bg-accent/10 text-fg" : "border-line text-muted hover:border-faint hover:text-fg"
              }`}
            >
              <span className={`font-mono text-[11px] ${stage === s.id ? "text-accent-soft" : "text-faint"}`}>{s.n}</span>
              {s.label}
            </button>
          ))}
          <button
            onClick={() => selectStage(null)}
            className={`rounded-sm border px-3 py-2 text-[13px] transition-colors duration-200 ${
              stage === null ? "border-line text-fg" : "border-line/60 text-faint hover:text-fg"
            }`}
          >
            All
          </button>
        </div>
      </div>

      {/* Diagram */}
      <div className="mt-6 overflow-x-auto rounded-md border border-line bg-bg/40 p-5">
        <div className="flex min-w-[1120px] items-stretch">
          {/* Ticker */}
          <div className="flex w-[84px] shrink-0 items-center">
            <Box {...p} id="ticker">
              <div className="mt-1.5 font-mono text-[15px] text-accent-soft">MU</div>
            </Box>
          </div>
          <Arrow dim={stage !== null} />

          {/* Orchestrator */}
          <div className="flex w-[112px] shrink-0 items-center">
            <Box {...p} id="orchestrator">
              <div className="mt-1.5 text-[11px] leading-snug text-muted">Sequential · fixed order</div>
            </Box>
          </div>
          <Arrow dim={stage !== null && stage !== "research"} />

          {/* Research agents */}
          <StageColumn label="1 · Research" on={lit("research")} highlighted={stage === "research"} className="w-[216px]">
            <Box {...p} id="financial">
              <div className="mt-2 flex flex-wrap gap-1.5"><Source stage={stage} s="research">yfinance</Source></div>
            </Box>
            <Box {...p} id="filings">
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Source stage={stage} s="research">SEC EDGAR</Source>
                <Source stage={stage} s="research">edgartools</Source>
              </div>
            </Box>
            <Box {...p} id="market">
              <div className="mt-2 flex flex-wrap gap-1.5">
                <Source stage={stage} s="research">Tavily</Source>
                <Source stage={stage} s="research">yfinance</Source>
              </div>
            </Box>
          </StageColumn>
          <Arrow dim={stage !== null && stage === "synthesize"} />

          {/* Validation layer */}
          <StageColumn label="2 · Verify" on={lit("verify")} highlighted={stage === "verify"} className="w-[212px]">
            <Box {...p} id="validation" className="h-full">
              <div className="mt-1 text-[11px] text-muted">Python · no LLM</div>
              <ul className="mt-3 space-y-1.5">
                {CONTROLS.map((c) => (
                  <li key={c} className="flex items-start gap-2 text-[12px] leading-snug text-fg/85">
                    <span className={`mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full transition-colors duration-200 ${stage === "verify" ? "bg-accent" : "bg-faint"}`} />
                    {c}
                  </li>
                ))}
              </ul>
              <div className="mt-3 border-t border-line pt-2.5 font-mono text-[10.5px] leading-relaxed text-faint">
                FIN-01 · RF-xx · WEB-xx · COMPS-01
              </div>
            </Box>
          </StageColumn>
          <Arrow dim={stage !== null && stage === "research"} />

          {/* Synthesis */}
          <StageColumn label="3 · Synthesize" on={lit("synthesize")} highlighted={stage === "synthesize"} className="flex-1" row>
            <div className="flex w-full items-center">
              <div className="min-w-0 flex-[1.35]">
                <Box {...p} id="analyst">
                  <ul className="mt-2 space-y-0.5 text-[11px] leading-snug text-muted">
                    <li>Thesis support</li>
                    <li>Challenges & risks</li>
                    <li className="text-fg/85">BUY / HOLD / SELL signal</li>
                  </ul>
                </Box>
              </div>
              <Arrow dim={!lit("synthesize")} />
              <div className="min-w-0 flex-1">
                <Box {...p} id="writer">
                  <div className="mt-2 text-[11px] leading-snug text-muted">Readable report with inline citations</div>
                </Box>
              </div>
              <Arrow dim={!lit("synthesize")} />
              <div className="min-w-0 flex-1">
                <Box {...p} id="ui">
                  <div className="mt-2 text-[11px] leading-snug text-muted">Progress + cited report</div>
                </Box>
              </div>
            </div>
          </StageColumn>
        </div>
      </div>

      {/* Explanation */}
      <div className="mt-5 grid gap-5 md:grid-cols-[1.4fr_1fr]">
        <section className="min-h-[112px] rounded-md border border-line bg-panel p-5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
            {active ? `Stage ${active.n} · ${active.label}` : "Overview"}
          </h2>
          <p className="mt-2.5 text-[15px] leading-relaxed text-fg/90">
            {active
              ? active.text
              : "A ticker flows through three research agents, a deterministic verification layer and two synthesis agents. Every claim in the final report traces back to a source ID."}
          </p>
        </section>
        <section className="min-h-[112px] rounded-md border border-line p-5">
          <h2 className="text-[11px] font-semibold uppercase tracking-[0.12em] text-muted">
            {node ? NODES[node].title : "Component"}
          </h2>
          <p className="mt-2.5 text-[14px] leading-relaxed text-fg/85">
            {node ? NODES[node].text : <span className="text-faint">Click any box in the diagram for a short description.</span>}
          </p>
        </section>
      </div>
      <p className="mt-3 text-right font-mono text-[10.5px] text-faint">Keys: 1 · 2 · 3 select a stage · 0 shows all</p>
    </main>
  );
}

function StageColumn({
  label, on, highlighted, className = "", row = false, children,
}: {
  label: string; on: boolean; highlighted: boolean; className?: string; row?: boolean; children: ReactNode;
}) {
  return (
    <div
      className={`flex shrink-0 flex-col rounded-md border border-dashed p-2.5 pt-2 transition-colors duration-200 ${
        highlighted ? "border-accent/50 bg-accent/[0.03]" : "border-line/70"
      } ${className}`}
    >
      <div
        className={`mb-2 font-mono text-[10.5px] uppercase tracking-[0.14em] transition-colors duration-200 ${
          highlighted ? "text-accent-soft" : on ? "text-muted" : "text-faint/60"
        }`}
      >
        {label}
      </div>
      <div className={`flex flex-1 ${row ? "items-center" : "flex-col justify-center gap-2.5"}`}>{children}</div>
    </div>
  );
}
