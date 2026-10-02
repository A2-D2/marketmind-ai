"""CLI: python scripts/run_full_research.py [TICKER] [--no-save]

Runs the full pipeline once: Financial -> SEC Filings -> Market/Comps -> Analyst -> Writer.
Saves the Markdown report to outputs/<TICKER>_report.md.
"""

import argparse
import asyncio
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from marketmind.agents.analyst import DEFAULT_MODEL  # noqa: E402
from marketmind.data.filings import EdgarIdentityError, require_edgar_identity  # noqa: E402
from marketmind.data.web_research import TavilyKeyError, require_tavily_key  # noqa: E402
from marketmind.pipeline import STAGES, run_full_research  # noqa: E402


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MU")
    parser.add_argument("--no-save", action="store_true", help="print only, do not write outputs/")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")
    try:
        require_edgar_identity()
        require_tavily_key()
    except (EdgarIdentityError, TavilyKeyError) as exc:
        sys.exit(str(exc))

    t0 = time.monotonic()
    last = [t0]

    def progress(i, name):
        now = time.monotonic()
        if i > 1:
            print(f"      done ({now - last[0]:.1f}s)", flush=True)
        last[0] = now
        print(f"{i}/{len(STAGES)} {name}...", flush=True)

    run = await run_full_research(args.ticker, progress)
    print(f"      done ({time.monotonic() - last[0]:.1f}s)\n", flush=True)

    print(run.report_markdown)

    print("=" * 72)
    print(f"Stages completed: {len(run.completed_stages)}/{len(STAGES)}")
    for stage, err in run.stage_errors.items():
        print(f"  FAILED {stage}: {err}")
    print(f"Signal: {run.analysis.investment_signal}")
    print(f"Tavily requests: {run.tavily_requests}")
    print(f"Token usage ({os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}):")
    for line in run.usage_lines()[:-1]:
        print(f"  {line}")
    for w in run.warnings:
        print(f"WARNING: {w}")
    print(f"Elapsed: {time.monotonic() - t0:.1f}s")

    if not args.no_save:
        out_dir = ROOT / "outputs"
        out_dir.mkdir(exist_ok=True)
        path = out_dir / f"{run.ticker}_report.md"
        path.write_text(run.report_markdown, encoding="utf-8")
        print(f"Report saved: {path.relative_to(ROOT)}")


if __name__ == "__main__":
    asyncio.run(main())
