"""CLI: python scripts/run_market_agent.py [TICKER] [--json]"""

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from marketmind.agents.market_research import DEFAULT_MODEL, run_market_research  # noqa: E402
from marketmind.data.financials import get_company_financials  # noqa: E402
from marketmind.data.web_research import (  # noqa: E402
    TavilyKeyError,
    get_web_research_evidence,
    require_tavily_key,
)


def money(value, currency):
    if value is None:
        return "n/a"
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= div:
            return f"{currency or '?'} {value / div:,.2f}{suffix}"
    return f"{currency or '?'} {value:,.0f}"


def ratio(value):
    return "n/a" if value is None else f"{value:.1f}x"


def statements(title, items):
    print(f"\n{title}")
    for s in items:
        print(f"  - [{', '.join(s.source_ids)}] {s.statement}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MU")
    parser.add_argument("--json", action="store_true", help="also print full JSON output")
    args = parser.parse_args()

    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")
    try:
        require_tavily_key()
    except TavilyKeyError as exc:
        sys.exit(str(exc))

    target = get_company_financials(args.ticker, history_period="5d")
    if not target.company_name:
        sys.exit(f"No company data for {args.ticker}; skipping Tavily and LLM calls.")
    ev = get_web_research_evidence(args.ticker, financials=target)
    print(f"Data: {ev.data_provider} @ {ev.retrieved_at}")
    print(f"Evidence: {len(ev.sources)} sources, {ev.extracted_chars:,} chars (~{ev.approx_tokens:,} tokens)")
    if not ev.sources:
        sys.exit(f"No web evidence for {args.ticker}; skipping LLM call.")

    out, usage = await run_market_research(ev, target)

    print(f"\n{out.company} ({out.ticker})")
    print("\nSelected comparable companies")
    for p in out.comparable_companies:
        print(f"  - {p.name} [{', '.join(p.source_ids)}]: {p.reason}")

    print("\nComparable-company dataset (no currency conversion)")
    for r in out.comps_dataset:
        m = r.metrics
        print(f"  [{r.role}] {r.peer_name} -> {r.ticker} | {r.company_name or 'n/a'} | "
              f"{r.exchange or 'n/a'} | {r.country or 'n/a'} | {r.listing_basis or ''}")
        print(f"      market cap {money(m.market_cap, r.currency)} | "
              f"revenue TTM {money(m.revenue_ttm, r.financial_currency)} | "
              f"net income TTM {money(m.net_income_ttm, r.financial_currency)}")
        print(f"      P/E {ratio(m.trailing_pe)} | fwd P/E {ratio(m.forward_pe)} | "
              f"EV/EBITDA {ratio(m.ev_to_ebitda)} | P/S {ratio(m.price_to_sales)}"
              + (f" | sources {', '.join(r.source_ids)}" if r.source_ids else ""))
        if r.missing_metrics:
            print(f"      missing: {', '.join(r.missing_metrics)}")
        for w in r.warnings:
            print(f"      WARNING: {w}")

    print("\nRejected peers")
    for r in out.rejected_peers:
        ids = f" [{', '.join(r.source_ids)}]" if r.source_ids else ""
        print(f"  - ({r.stage}) {r.name}{ids}: {r.reason}")

    statements("Recent company developments", out.recent_company_developments)
    statements("Industry context", out.industry_context)
    statements("Important market trends", out.important_market_trends)

    print("\nSources cited")
    for s in out.sources:
        print(f"  [{s.source_id}] ({s.query_purpose}, {s.published_date or 'undated'}) {s.title}")
        print(f"      {s.url}")
    print("\nData limitations")
    for item in out.data_limitations:
        print(f"  - {item}")
    for w in out.warnings:
        print(f"WARNING: {w}")

    print(f"\nTavily requests: {ev.tavily_requests} (credits: {ev.tavily_credits or 'n/a'})")
    print(
        f"Token usage ({os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}): "
        f"requests={usage.requests} input={usage.input_tokens} "
        f"output={usage.output_tokens} total={usage.total_tokens}"
    )
    if args.json:
        print(json.dumps(out.model_dump(), indent=2))


if __name__ == "__main__":
    asyncio.run(main())
