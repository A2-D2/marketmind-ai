"""CLI: python scripts/run_filings_agent.py [TICKER]"""

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from marketmind.agents.filings_research import DEFAULT_MODEL, run_filings_research  # noqa: E402
from marketmind.data.filings import (  # noqa: E402
    EdgarIdentityError,
    get_latest_10k_evidence,
    require_edgar_identity,
)


def findings(title, items):
    print(f"\n{title}")
    for f in items:
        print(f"  - [{', '.join(f.evidence_ids)}] {f.filing_statement}")
        print(f"      Interpretation: {f.interpretation}")


async def main():
    ticker = sys.argv[1] if len(sys.argv) > 1 else "MU"
    if not os.getenv("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY not set. Copy .env.example to .env and add your key.")

    try:
        require_edgar_identity()
    except EdgarIdentityError as exc:
        sys.exit(str(exc))

    ev = get_latest_10k_evidence(ticker)
    print(f"Data: {ev.data_provider} @ {ev.retrieved_at}")
    for w in ev.warnings:
        print(f"WARNING: {w}")
    if not ev.excerpts:
        sys.exit(f"No filing evidence for {ticker}; skipping LLM call.")
    print(f"Evidence: {len(ev.excerpts)} excerpts, {ev.extracted_chars:,} chars (~{ev.approx_tokens:,} tokens)")

    out, usage = await run_filings_research(ev)

    s = out.source
    print(f"\n{out.company} ({out.ticker})")
    print(f"Source: {s.form_type} filed {s.filing_date}, accession {s.accession_number}")
    print(f"        {s.primary_document_url}")
    print(f"\nSummary: {out.filing_summary}")
    findings("Key risks", out.key_risks)
    findings("Material findings", out.material_findings)
    print("\nEvidence")
    for c in out.evidence:
        print(f'  - [{c.evidence_id}] "{c.quote}"')
    print("\nData limitations")
    for item in out.data_limitations:
        print(f"  - {item}")

    print(
        f"\nToken usage ({os.getenv('OPENAI_MODEL', DEFAULT_MODEL)}): "
        f"requests={usage.requests} input={usage.input_tokens} "
        f"output={usage.output_tokens} total={usage.total_tokens}"
    )


if __name__ == "__main__":
    asyncio.run(main())
