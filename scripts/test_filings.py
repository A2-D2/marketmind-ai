"""CLI smoke test (no LLM): python scripts/test_filings.py [TICKER] [--json] [--show]"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

from marketmind.data.filings import (  # noqa: E402
    EdgarIdentityError,
    get_latest_10k_evidence,
    require_edgar_identity,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MU")
    parser.add_argument("--json", action="store_true", help="print full JSON")
    parser.add_argument("--show", action="store_true", help="print every excerpt")
    args = parser.parse_args()

    try:
        require_edgar_identity()
    except EdgarIdentityError as exc:
        sys.exit(str(exc))

    ev = get_latest_10k_evidence(args.ticker)

    if args.json:
        print(json.dumps(ev.to_dict(), indent=2))
        return

    print(f"{ev.company_name or 'n/a'} ({ev.ticker})  CIK {ev.cik or 'n/a'}")
    print(f"Form:          {ev.form_type or 'n/a'}")
    print(f"Filing date:   {ev.filing_date or 'n/a'} (period of report {ev.period_of_report or 'n/a'})")
    print(f"Accession:     {ev.accession_number or 'n/a'}")
    print(f"Filing index:  {ev.filing_index_url or 'n/a'}")
    print(f"Document:      {ev.primary_document_url or 'n/a'}")
    print(f"Sections:      {', '.join(ev.sections_extracted) or 'none'}")
    print(f"Section size:  {ev.section_total_chars:,} chars (full Item 1A)")
    print(f"Risk factors:  {ev.risk_factor_count} headings found, {len(ev.excerpts)} excerpts")
    print(f"LLM evidence:  {ev.extracted_chars:,} chars (~{ev.approx_tokens:,} tokens)")
    for e in ev.excerpts if args.show else ev.excerpts[:4]:
        print(f"\n[{e.evidence_id}] {e.heading or ''}\n  {e.text[:300 if not args.show else None]}")
    if not args.show and len(ev.excerpts) > 4:
        print(f"\n... {len(ev.excerpts) - 4} more excerpts (use --show)")
    for w in ev.warnings:
        print(f"WARNING: {w}")


if __name__ == "__main__":
    main()
