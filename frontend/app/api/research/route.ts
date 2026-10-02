// POST /api/research {ticker} -> runs `python scripts/run_full_research.py TICKER` and
// streams newline-delimited JSON events:
//   {type:"stage", index}            stage index (1-5) has started
//   {type:"done", markdown, savedAt} report file written by the pipeline
//   {type:"error", message}          redacted failure message
// Only parsed progress and the saved report reach the browser, never raw stdout or env.
import { spawn } from "node:child_process";
import { readFile, stat } from "node:fs/promises";
import { REPO_ROOT, normalizeTicker, pythonExecutable, redact, reportPath } from "@/lib/server";

const TIMEOUT_MS = 10 * 60 * 1000;
let running = false; // one live run at a time (protects against double clicks)

export async function POST(request: Request) {
  const body = await request.json().catch(() => ({}));
  const ticker = normalizeTicker((body as { ticker?: unknown }).ticker);
  if (!ticker) return Response.json({ error: "Invalid ticker." }, { status: 400 });
  if (running) {
    return Response.json({ error: "A research run is already in progress." }, { status: 409 });
  }
  running = true;

  const encoder = new TextEncoder();
  let child: ReturnType<typeof spawn> | null = null;

  const stream = new ReadableStream({
    start(controller) {
      let closed = false;
      const send = (event: object) => {
        if (!closed) controller.enqueue(encoder.encode(JSON.stringify(event) + "\n"));
      };
      const finish = () => {
        if (closed) return;
        closed = true;
        running = false;
        clearTimeout(timer);
        controller.close();
      };

      child = spawn(pythonExecutable(), ["scripts/run_full_research.py", ticker], {
        cwd: REPO_ROOT,
        env: { ...process.env, PYTHONUNBUFFERED: "1" }, // Python loads .env itself
        stdio: ["ignore", "pipe", "pipe"],
      });

      let timedOut = false;
      const timer = setTimeout(() => {
        timedOut = true;
        send({ type: "error", message: "Research run timed out after 10 minutes." });
        child?.kill("SIGTERM");
      }, TIMEOUT_MS);

      let buffer = "";
      child.stdout?.on("data", (chunk: Buffer) => {
        buffer += chunk.toString();
        const lines = buffer.split("\n");
        buffer = lines.pop() ?? "";
        for (const line of lines) {
          const m = /^(\d)\/5 /.exec(line);
          if (m) send({ type: "stage", index: Number(m[1]) });
        }
      });

      let stderrTail = "";
      child.stderr?.on("data", (chunk: Buffer) => {
        stderrTail = (stderrTail + chunk.toString()).slice(-4000);
      });

      child.on("error", (err) => {
        send({ type: "error", message: redact(`Could not start Python: ${err.message}`) });
        finish();
      });

      child.on("close", async (code) => {
        if (code === 0) {
          try {
            const file = reportPath(ticker);
            const [markdown, info] = await Promise.all([readFile(file, "utf-8"), stat(file)]);
            send({ type: "done", markdown, savedAt: info.mtime.toISOString() });
          } catch {
            send({ type: "error", message: "Pipeline finished but the report file was not found." });
          }
        } else if (!timedOut) {
          // Final traceback line is the exception message (e.g. "ValueError: No financial data ...").
          const lastLine = stderrTail.trim().split("\n").filter((l) => l.trim()).pop() ?? "";
          send({
            type: "error",
            message: redact(`Pipeline exited with code ${code}.${lastLine ? `\n${lastLine.trim()}` : ""}`),
          });
        }
        finish();
      });
    },
    cancel() {
      // Browser navigated away / aborted: stop the Python process.
      child?.kill("SIGTERM");
      running = false;
    },
  });

  return new Response(stream, {
    headers: { "Content-Type": "application/x-ndjson; charset=utf-8", "Cache-Control": "no-store" },
  });
}
