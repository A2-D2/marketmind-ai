// Minimal renderer for the subset of Markdown the report uses: paragraphs,
// "- " bullets, pipe tables, **bold**, whole-line _italic_, URLs and [ID] citations.
import { Fragment, type ReactNode } from "react";
import { splitTable, type Table } from "@/lib/report";

const INLINE_RE =
  /(\*\*[^*]+\*\*|\[(?:[A-Z]{2,8}-\d{2})(?:,\s*[A-Z]{2,8}-\d{2})*\]|https?:\/\/[^\s)]+)/g;

export function Citation({ ids }: { ids: string[] }) {
  return (
    <span className="whitespace-nowrap">
      {ids.map((id) => (
        <a
          key={id}
          href={`#src-${id}`}
          className="ml-1 inline-block rounded-sm border border-line px-1 font-mono text-[10.5px] leading-4 text-accent-soft hover:border-accent hover:text-accent"
        >
          {id}
        </a>
      ))}
    </span>
  );
}

export function Inline({ text }: { text: string }) {
  const parts = text.split(INLINE_RE);
  return (
    <>
      {parts.map((p, i) => {
        if (!p) return null;
        if (p.startsWith("**") && p.endsWith("**")) {
          return <strong key={i} className="font-semibold text-fg">{p.slice(2, -2)}</strong>;
        }
        if (/^\[[A-Z]{2,8}-\d{2}/.test(p)) {
          return <Citation key={i} ids={p.slice(1, -1).split(/,\s*/)} />;
        }
        if (/^https?:\/\//.test(p)) {
          const url = p.replace(/[.,;]+$/, "");
          return (
            <Fragment key={i}>
              <a href={url} target="_blank" rel="noreferrer" className="break-all text-accent-soft hover:text-accent hover:underline">
                {url}
              </a>
              {p.slice(url.length)}
            </Fragment>
          );
        }
        return <Fragment key={i}>{p}</Fragment>;
      })}
    </>
  );
}

export function DataTable({ table, compact = false }: { table: Table; compact?: boolean }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full border-collapse text-left text-[13px]">
        <thead>
          <tr className="border-b border-line">
            {table.headers.map((h) => (
              <th key={h} className="whitespace-nowrap px-3 py-2 text-[11px] font-medium uppercase tracking-wider text-muted">
                {h}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {table.rows.map((row, r) => (
            <tr key={r} className="border-b border-line/60 last:border-0 hover:bg-white/[0.02]">
              {row.map((cell, c) => (
                <td
                  key={c}
                  className={`px-3 ${compact ? "py-1.5" : "py-2.5"} align-top ${
                    c === 0 ? "text-fg" : "font-mono tabular-nums text-fg/90"
                  } ${c > 0 && c < row.length - 1 ? "whitespace-nowrap" : ""}`}
                >
                  <Inline text={cell} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function Markdown({ text, className = "" }: { text: string; className?: string }) {
  const blocks: ReactNode[] = [];
  let rest = text.trim();
  // Tables first (rare inside prose sections, but supported).
  const { table, rest: withoutTable } = splitTable(rest);
  if (table) {
    blocks.push(<DataTable key="table" table={table} />);
    rest = withoutTable;
  }

  let list: string[] = [];
  const flushList = () => {
    if (!list.length) return;
    blocks.push(
      <ul key={`ul-${blocks.length}`} className="space-y-2">
        {list.map((item, i) => (
          <li key={i} className="relative pl-4 before:absolute before:left-0 before:top-[0.6em] before:h-1 before:w-1 before:rounded-full before:bg-muted">
            <Inline text={item} />
          </li>
        ))}
      </ul>,
    );
    list = [];
  };

  for (const raw of rest.split("\n")) {
    const line = raw.trim();
    if (line.startsWith("- ")) {
      list.push(line.slice(2));
      continue;
    }
    flushList();
    if (!line) continue;
    if (/^_.*_$/.test(line)) {
      const inner = line.slice(1, -1);
      blocks.push(
        <p key={`p-${blocks.length}`} className="text-[12px] italic text-muted">
          {inner === "None supplied." ? "None supplied." : <Inline text={inner} />}
        </p>,
      );
      continue;
    }
    blocks.push(
      <p key={`p-${blocks.length}`}>
        <Inline text={line} />
      </p>,
    );
  }
  flushList();

  return <div className={`space-y-3 text-[14px] leading-relaxed text-fg/90 ${className}`}>{blocks}</div>;
}
