// Server-only helpers for running / reading the existing Python pipeline.
// Nothing here is imported by client components, and no env values are ever
// returned to the browser.
import { existsSync } from "node:fs";
import path from "node:path";

// The Next app lives in <repo>/frontend; the Python project is its parent.
export const REPO_ROOT = process.env.MARKETMIND_ROOT ?? path.resolve(process.cwd(), "..");

export const OUTPUTS_DIR = path.join(REPO_ROOT, "outputs");

export function pythonExecutable(): string {
  const venv = path.join(REPO_ROOT, ".venv", "bin", "python");
  return existsSync(venv) ? venv : "python3";
}

// Letters/digits plus . and - (e.g. BRK.B, 000660.KS). No slashes, so no path traversal.
const TICKER_RE = /^[A-Z0-9][A-Z0-9.\-]{0,11}$/;

export function normalizeTicker(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  const t = raw.trim().toUpperCase();
  return TICKER_RE.test(t) ? t : null;
}

export function reportPath(ticker: string): string {
  return path.join(OUTPUTS_DIR, `${ticker}_report.md`);
}

// Defence in depth: strip anything that looks like a credential from error text.
export function redact(text: string): string {
  return text
    .replace(/sk-[A-Za-z0-9_\-]{8,}/g, "sk-***")
    .replace(/tvly-[A-Za-z0-9_\-]{8,}/g, "tvly-***")
    .replace(/(api[_-]?key|authorization|bearer)(\s*[:=]\s*|\s+)\S+/gi, "$1$2***");
}
