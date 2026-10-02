# MarketMind

Agentic equity research platform (capstone). The differentiating feature will be
**Thesis Evolution**: how the evidence and investment thesis around a company
changes over time (supporting, challenging, and unresolved evidence).

Works with any ticker. MU, NVDA and ALAB are used only for development/testing.

> Research tooling only. No trading execution, no price prediction.

## Status

Step 1: financial data module (yfinance). No LLM, SEC, news, or UI yet.

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # not required yet
```

## Try it

```bash
python scripts/test_financials.py MU
python scripts/test_financials.py NVDA --json
python scripts/test_filings.py MU          # SEC 10-K risk factors, no LLM
python scripts/run_filings_agent.py MU      # Filings/Risk Research Agent (calls OpenAI)
python scripts/run_market_agent.py MU       # Market/Comps Agent (3 Tavily searches + OpenAI)
```

## Layout

```
src/marketmind/data/financials.py   # yfinance retrieval -> CompanyFinancials dataclass
scripts/test_financials.py          # CLI smoke test
src/marketmind/data/filings.py      # edgartools latest 10-K -> bounded Item 1A evidence (FilingEvidence)
src/marketmind/agents/filings_research.py  # Filings/Risk Research Agent (evidence-cited output)
src/marketmind/agents/market_research.py   # Market/Comps Agent: peer names + context -> verified, resolved comps dataset
```

## Design notes

- Data retrieval is kept separate from LLM analysis.
- Missing yfinance fields are `None` (never guessed) and noted in `warnings`.
- Output is a plain dataclass, convertible to a dict/JSON for later agents.
