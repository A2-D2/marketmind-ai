// GET /api/report?ticker=MU -> previously generated report from outputs/ (no API calls).
import { readFile, stat } from "node:fs/promises";
import { normalizeTicker, reportPath } from "@/lib/server";

export async function GET(request: Request) {
  const ticker = normalizeTicker(new URL(request.url).searchParams.get("ticker") ?? "MU");
  if (!ticker) return Response.json({ error: "Invalid ticker." }, { status: 400 });

  const file = reportPath(ticker);
  try {
    const [markdown, info] = await Promise.all([readFile(file, "utf-8"), stat(file)]);
    return Response.json({ ticker, markdown, savedAt: info.mtime.toISOString() });
  } catch {
    return Response.json(
      { error: `No saved report for ${ticker} (expected outputs/${ticker}_report.md).` },
      { status: 404 },
    );
  }
}
