"""CLI smoke test (no LLM): python scripts/test_web_research.py [TICKER] [--json] [--show]"""

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
os.environ.pop("OPENAI_API_KEY", None)  # retrieval only: make any OpenAI call impossible

from marketmind.data.web_research import (  # noqa: E402
    TavilyKeyError,
    get_web_research_evidence,
    require_tavily_key,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MU")
    parser.add_argument("--json", action="store_true", help="print full JSON")
    parser.add_argument("--show", action="store_true", help="print every excerpt")
    args = parser.parse_args()

    try:
        require_tavily_key()
    except TavilyKeyError as exc:
        sys.exit(str(exc))

    ev = get_web_research_evidence(args.ticker)

    if args.json:
        print(json.dumps(ev.to_dict(), indent=2))
        return

    print(f"{ev.company_name or 'n/a'} ({ev.ticker})")
    print(f"Sector / Industry: {ev.sector or 'n/a'} / {ev.industry or 'n/a'}")
    print(f"Business keyword:  {ev.business_keyword or 'n/a'}")
    print(f"Tavily requests:   {ev.tavily_requests} (credits: {ev.tavily_credits or 'n/a'})")
    print(f"Results:           {len(ev.sources)} unique sources")
    print(f"LLM evidence:      {ev.extracted_chars:,} chars (~{ev.approx_tokens:,} tokens)")
    print("\nQueries")
    for q in ev.queries:
        status = f"ERROR {q.error}" if q.error else f"{q.result_count} results"
        print(f"  [{q.purpose}] topic={q.topic} range={q.time_range} -> {status}")
        print(f"      \"{q.query}\"")
    for purpose in ("peers", "company_news", "industry_news"):
        print(f"\nSources: {purpose}")
        for s in (s for s in ev.sources if s.query_purpose == purpose):
            print(f"  [{s.source_id}] {s.title}")
            print(f"      {s.url}")
            print(f"      published: {s.published_date or 'n/a'}  excerpt: {len(s.excerpt)} chars")
            if args.show:
                print(f"      {s.excerpt}")
    for w in ev.warnings:
        print(f"WARNING: {w}")

    llm_modules = sorted(m for m in sys.modules if m.split(".")[0] in ("openai", "agents"))
    print(f"\nOpenAI/Agents SDK modules loaded: {llm_modules or 'none'} -> no OpenAI API call possible")


if __name__ == "__main__":
    main()
