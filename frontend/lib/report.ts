// Parses the Markdown report written by the Python pipeline (agents/writer.py
// render_report) into display sections. Pure string handling; no research logic.

export type Signal = "BUY" | "HOLD" | "SELL" | null;

export interface Table {
  headers: string[];
  rows: string[][];
}

export interface SourceItem {
  id: string;
  title: string;
  date: string | null;
  url: string | null;
}

export interface UsageRow {
  agent: string;
  requests: string;
  input: string;
  output: string;
  total: string;
}

export interface ParsedReport {
  company: string;
  ticker: string;
  generated: string | null;
  signal: Signal;
  sections: Record<string, string>; // heading -> raw markdown body
  keyFinancials: Table | null;
  keyFinancialsNotes: string;
  comps: Table | null;
  compsNotes: string;
  sources: SourceItem[];
  usage: UsageRow[];
  tavilyRequests: string | null;
}

export function splitTable(body: string): { table: Table | null; rest: string } {
  const lines = body.split("\n");
  const start = lines.findIndex((l) => l.trim().startsWith("|"));
  if (start < 0) return { table: null, rest: body };
  let end = start;
  while (end < lines.length && lines[end].trim().startsWith("|")) end++;
  const cells = (l: string) => l.trim().replace(/^\||\|$/g, "").split("|").map((c) => c.trim());
  const tableLines = lines.slice(start, end).filter((l) => !/^\|?\s*-{3}/.test(l.trim()));
  const [headers, ...rows] = tableLines.map(cells);
  const rest = [...lines.slice(0, start), ...lines.slice(end)].join("\n").trim();
  return { table: { headers, rows }, rest };
}

function parseSources(body: string): SourceItem[] {
  const items: SourceItem[] = [];
  for (const line of body.split("\n")) {
    const m = /^- \*\*\[([A-Z]+-\d+)\]\*\*\s+(.*)$/.exec(line.trim());
    if (!m) continue;
    const parts = m[2].split(" — ");
    const url = parts.length > 1 && /^https?:\/\//.test(parts[parts.length - 1]) ? parts.pop()! : null;
    const title = parts.shift() ?? "";
    items.push({ id: m[1], title, date: parts.join(" — ") || null, url });
  }
  return items;
}

function parseUsage(body: string): { usage: UsageRow[]; tavily: string | null } {
  const usage: UsageRow[] = [];
  let tavily: string | null = null;
  for (const line of body.split("\n")) {
    const u = /^- (.+?): requests=([\d,]+), input=([\d,]+), output=([\d,]+), total=([\d,]+)/.exec(line);
    if (u) usage.push({ agent: u[1], requests: u[2], input: u[3], output: u[4], total: u[5] });
    const t = /^- Tavily requests: (\d+)/.exec(line);
    if (t) tavily = t[1];
  }
  return { usage, tavily };
}

export function parseReport(md: string): ParsedReport {
  const title = /^# .*?:\s*(.+?)\s*\(([^()]+)\)\s*$/m.exec(md);
  const generated = /^_Generated ([^.]+)\./m.exec(md);

  const sections: Record<string, string> = {};
  let signal: Signal = null;
  const chunks = md.split(/^## /m).slice(1);
  for (const chunk of chunks) {
    const nl = chunk.indexOf("\n");
    let heading = (nl < 0 ? chunk : chunk.slice(0, nl)).trim();
    const body = nl < 0 ? "" : chunk.slice(nl + 1).trim();
    const sig = /Signal:\s*(BUY|HOLD|SELL)/.exec(heading);
    if (sig) {
      signal = sig[1] as Signal;
      heading = "Signal";
    }
    sections[heading] = body;
  }

  const kf = splitTable(sections["Key Financials"] ?? "");
  const cp = splitTable(sections["Comparable Companies"] ?? "");
  const { usage, tavily } = parseUsage(sections["Run Details"] ?? "");

  return {
    company: title?.[1] ?? "Unknown company",
    ticker: title?.[2] ?? "",
    generated: generated?.[1] ?? null,
    signal,
    sections,
    keyFinancials: kf.table,
    keyFinancialsNotes: kf.rest,
    comps: cp.table,
    compsNotes: cp.rest,
    sources: parseSources(sections["Sources"] ?? ""),
    usage,
    tavilyRequests: tavily,
  };
}
