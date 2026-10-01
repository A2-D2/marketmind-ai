"""Peer resolver smoke test (no LLM, no Tavily): python scripts/test_peer_resolver.py

Uses fixed source excerpts (copied verbatim from an earlier live Tavily run for
MU, plus one synthetic edge-case source) and hand-written peer candidates, so
it exercises evidence verification, yfinance resolution and validation only.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
os.environ.pop("OPENAI_API_KEY", None)  # make any OpenAI call impossible

from marketmind.data.peers import PeerCandidate, resolve_peers  # noqa: E402
from marketmind.data.web_research import WebSource  # noqa: E402

SOURCES = [
    WebSource(
        "WEB-01", "peers", "Micron Technology Inc Comparisons to its Competitors and Market Share",
        "https://csimarket.com/stocks/MU-Competitors", None,
        "Company Quick Ratio Working Capital Debt / Equity Asset Turnover --- --- Micron Technology "
        "Inc 1.02 2.91 0.17 0.89 Asml Holding Nv 0.53 1.26 0.19 0.62 Intel Corporation 0.44 1.86 "
        "0.40 0.28 Seagate Technology Holdings Plc 0.37 1.31 6.23 1.38 Western Digital Corporation "
        "0.40 1.27 0.44 0.90 Microchip Technology Incorporated 0.33 2.20 0.82 0.35",
    ),
    WebSource(
        "WEB-02", "peers", "Micron Competitors: MU Key Peers in 2026 Hudson Labs",
        "https://www.hudson-labs.com/research/micron-competitors-mu-key-peers-in-2026", None,
        "Ticker Company Name Subsector Market Cap --- --- INTC Intel Corp Semiconductors $216.88B "
        "AMD Advanced Micro Devices Inc Semiconductors $313.76B NVDA NVIDIA Corp Semiconductors "
        "$4.32T STX Seagate Technology Holdings PLC Computer Hardware $79.04B [...] WDC Western "
        "Digital Corp Computer Hardware $83.15B",
    ),
    WebSource(
        "WEB-03", "peers", "Micron Stock in 11 Minutes: Buy, Sell, or Hold?",
        "https://www.youtube.com/watch?v=dvvNJazHaSU", None,
        "Now Micron is really one of just three companies in the whole world that can manufacture "
        "at scale and its main competitors are Samsung and SKH Highix.",
    ),
    WebSource(  # synthetic fixture for edge cases (home-market listings, unlisted company)
        "TEST-01", "peers", "Synthetic test fixture", "https://example.invalid/fixture", None,
        "Memory makers include SK Hynix, Kioxia, Nanya Technology and Acme Imaginary Memory Corp; "
        "foundry partner Taiwan Semiconductor.",
    ),
]

CANDIDATES = [
    PeerCandidate("Samsung", ["WEB-03"]),
    PeerCandidate("SK Hynix", ["WEB-03"]),  # source misspells it -> must be rejected
    PeerCandidate("SK Hynix", ["TEST-01"]),
    PeerCandidate("Western Digital", ["WEB-01", "WEB-02"]),
    PeerCandidate("Seagate Technology", ["WEB-01", "WEB-02"]),
    PeerCandidate("Asml Holding", ["WEB-01"]),
    PeerCandidate("Intel", ["WEB-01", "WEB-02"]),
    PeerCandidate("Taiwan Semiconductor", ["TEST-01"]),
    PeerCandidate("Kioxia", ["WEB-02"]),  # not in cited excerpt -> reject
    PeerCandidate("Micron Technology", ["WEB-01"]),  # target company -> reject
    PeerCandidate("Acme Imaginary Memory Corp", ["TEST-01"]),  # unlisted -> reject
    PeerCandidate("Nanya Technology", ["WEB-99"]),  # unknown source id -> reject
]


def main():
    max_peers = int(sys.argv[1]) if len(sys.argv) > 1 else 20  # high, to exercise every case
    res = resolve_peers("MU", CANDIDATES, SOURCES, "Micron Technology, Inc.", max_peers=max_peers)

    print(f"Resolved peers ({len(res.peers)})")
    for p in res.peers:
        f = p.financials
        cap = f"{f.market_cap:,.0f}" if f and f.market_cap is not None else "n/a"
        print(f"  {p.peer_name:22} -> {p.ticker:10} {p.exchange or 'n/a':4} {p.currency or 'n/a':4} "
              f"{p.country or 'n/a':12} [{', '.join(p.source_ids)}]")
        print(f"      {p.company_name} | {p.listing_basis} | market cap {cap} {p.currency or ''}")
    print(f"\nRejected ({len(res.rejected)})")
    for r in res.rejected:
        print(f"  {r.peer_name:26} [{', '.join(r.source_ids)}] {r.reason}")
    for w in res.warnings:
        print(f"WARNING: {w}")

    llm = sorted(m for m in sys.modules if m.split(".")[0] in ("openai", "agents"))
    print(f"\nOpenAI/Agents SDK modules loaded: {llm or 'none'}; Tavily requests: 0")


if __name__ == "__main__":
    main()
