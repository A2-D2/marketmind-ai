"""CLI: python scripts/run_financial_agent.py [TICKER]"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from marketmind.agents.financial_research import DEFAULT_MODEL, run_financial_research  # noqa: E402
from marketmind.data.financials import get_company_financials  # noqa: E402


def bullets(title, items):
    print(f"\n{title}")
    for item in items:
        print(f"  - {item}")


async def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "MU"
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")

    fin = get_company_financials(ticker)
    print(f"Data: {fin.data_provider} @ {fin.retrieved_at}")
    if not fin.price_history and fin.market_cap is None:
        sys.exit(f"No data for {ticker}; skipping LLM call.")

    out, usage = await run_financial_research(fin)

    print(f"\n{out.company} ({out.ticker})\n\nSummary: {out.financial_summary}")
    bullets("Key strengths", out.key_strengths)
    bullets("Key risks", out.key_risks)
    bullets("Notable trends", out.notable_trends)
    bullets("Data limitations", out.data_limitations)

    print(
        f"\nToken usage ({os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}): "
        f"requests={usage.requests} input={usage.input_tokens} "
        f"output={usage.output_tokens} total={usage.total_tokens}"
    )


if __name__ == "__main__":
    asyncio.run(main())
