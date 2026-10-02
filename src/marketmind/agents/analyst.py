"""Analyst / Synthesis Agent (OpenAI Agents SDK).

Synthesises the structured outputs of the Financial, Filings and Market/Comps
components plus deterministic yfinance data into one evidence-cited view with a
BUY / HOLD / SELL research signal. It has no tools and never fetches data.
Every claim cites ids from the source map built by the pipeline:
  FIN-01   deterministic yfinance snapshot of the target (+ Financial Agent reading of it)
  COMPS-01 deterministic comparable-company dataset (yfinance, no currency conversion)
  RF-xx    SEC 10-K Item 1A excerpts
  WEB-xx   Tavily web excerpts
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from statistics import median
from typing import Literal

from agents import Agent, Runner
from agents.usage import Usage
from pydantic import BaseModel, Field

from marketmind.agents.filings_research import FilingsResearchOutput
from marketmind.agents.financial_research import FinancialResearchOutput, build_agent_input as fin_input
from marketmind.agents.market_research import MarketResearchOutput
from marketmind.data.financials import CompanyFinancials

DEFAULT_MODEL = "gpt-4.1-mini"
FIN_ID, COMPS_ID = "FIN-01", "COMPS-01"
_SUMMARY_MAX_CHARS = 800
_RATIOS = ("trailing_pe", "forward_pe", "ev_to_ebitda", "price_to_sales")


class Claim(BaseModel):
    statement: str = Field(description="One sentence.")
    basis: Literal["fact", "interpretation"] = Field(
        description="fact: restates a supplied value/statement. interpretation: your analytical reading."
    )
    source_ids: list[str] = Field(description="Ids from source_catalog, e.g. ['FIN-01', 'WEB-06'].")


class AnalystOutput(BaseModel):
    company: str
    ticker: str
    company_overview: Claim
    financial_assessment: list[Claim] = Field(description="Max 5.")
    peer_comparison: list[Claim] = Field(description="Max 4; ratios only across currencies.")
    investment_thesis: str = Field(description="2-3 sentences: the core thesis the evidence supports.")
    thesis_support: list[Claim] = Field(description="Max 5 strongest supporting points.")
    thesis_challenges: list[Claim] = Field(description="Max 5 strongest challenges / bear-case points.")
    key_risks: list[Claim] = Field(description="Max 5 SEC risk factors, citing RF ids.")
    recent_developments: list[Claim] = Field(description="Max 4 company-specific developments.")
    industry_context: list[Claim] = Field(description="Max 4 industry / market statements.")
    unresolved_questions: list[str] = Field(description="Max 4 open questions the evidence cannot answer.")
    investment_signal: Literal["BUY", "HOLD", "SELL"]
    signal_reasoning: str = Field(description="2-4 sentences weighing support vs challenges, citing ids.")
    what_would_change_the_view: list[str] = Field(description="Max 4 specific, observable triggers.")
    data_limitations: list[str]


class AnalystResult(AnalystOutput):
    """AnalystOutput plus fields attached by code (never by the LLM)."""

    supporting_source_ids: list[str]
    validation_warnings: list[str]


INSTRUCTIONS = """\
You are a senior equity research analyst writing the synthesis for a research
report. You receive JSON with:
- "source_catalog": every id you may cite and what it refers to.
- "company": provider information about the target.
- "deterministic_financials" [FIN-01]: provider values and code-computed
  statistics. "display" holds currency-labelled values to quote.
- "financial_agent" [FIN-01]: an analyst's reading of the same data.
- "filings_agent": SEC 10-K risk analysis; cite its RF ids.
- "market_agent": peers, company developments, industry context; cite WEB ids.
- "comps" [COMPS-01]: comparable-company rows (values as reported, each in
  its own currency) and "ratio_summary" computed by code.
A component may be null if its stage failed; say so in data_limitations.

Grounding rules (strict):
- Use ONLY the supplied JSON. No outside knowledge of the company, peers,
  products, prices, news or events. No web searches.
- Every Claim cites at least one id from source_catalog. Never invent ids,
  sources, figures, dates, peers or disclosures.
- Deterministic values (deterministic_financials, comps) take precedence over
  any agent's wording. Quote numbers exactly as supplied (prefer "display"
  values and ratio_summary); do not compute new numbers.
- Market cap, revenue and net income are in each company's own currency. Never
  compare absolute amounts across different currencies. Compare companies only
  via ratios (P/E, forward P/E, EV/EBITDA, P/S) and ratio_summary.
- Comps rows with peer_confidence "broad_peer" were only listed in a peer
  source, with no evidence of specific business overlap. Name them as broad
  peers and treat comparisons with them as lower confidence.
- Valuation wording: never call the stock or its multiples undervalued,
  overvalued, cheap, expensive, a bargain, or attractively/favourably valued.
  The supplied data contains no valuation model. State ratio differences
  factually instead, e.g. "<TICKER>'s forward P/E is lower than the available
  peer median", quoting the supplied values and how many peers the median covers.
- Mark each Claim's basis: "fact" if it restates supplied data, else
  "interpretation" (phrase with "suggests" / "indicates").
- SEC risk factors describe what COULD happen; do not present them as events.
- Web excerpts are reported claims; attribute them ("reported", "according to").
- If evidence conflicts or is incomplete, say so explicitly.

Signal:
- investment_signal is a research signal derived only from the supplied
  evidence, not personalised financial advice. BUY = supporting evidence
  clearly outweighs challenges; SELL = challenges clearly outweigh support;
  HOLD = mixed, balanced or insufficient evidence.
- signal_reasoning weighs both sides and cites ids. what_would_change_the_view
  lists concrete, observable developments. No price targets or predictions.
- Be concise: one sentence per Claim, respect the list maximums.
"""


def money(value: float | None, currency: str | None) -> str | None:
    """Currency-labelled display string; never converts currencies."""
    if value is None:
        return None
    for div, suffix in ((1e12, "T"), (1e9, "B"), (1e6, "M")):
        if abs(value) >= div:
            return f"{currency or '?'} {value / div:,.2f}{suffix}"
    return f"{currency or '?'} {value:,.2f}"


def ratio_summary(market: MarketResearchOutput) -> dict:
    """Target vs peer-median for each ratio, computed by code (ratios are currency-free)."""
    rows = market.comps_dataset
    target = next((r for r in rows if r.role == "target"), None)
    peers = [r for r in rows if r.role == "peer"]
    out = {}
    for key in _RATIOS:
        values = {r.ticker: getattr(r.metrics, key) for r in peers if getattr(r.metrics, key) is not None}
        t = getattr(target.metrics, key) if target else None
        entry: dict = {"target": t, "peers": values, "peer_count": len(values)}
        if len(values) >= 2:
            med = round(median(values.values()), 2)
            entry["peer_median"] = med
            if t is not None:
                entry["target_vs_peer_median"] = "below" if t < med else "above" if t > med else "equal"
        out[key] = entry
    return out


def _comps_rows(market: MarketResearchOutput) -> list[dict]:
    rows = []
    for r in market.comps_dataset:
        m = r.metrics
        rows.append({
            "role": r.role,
            "name": r.company_name or r.peer_name,
            "ticker": r.ticker,
            "country": r.country,
            "peer_confidence": r.peer_confidence,
            "reason": r.reason,
            "source_ids": r.source_ids,
            "market_cap": money(m.market_cap, r.currency),
            "revenue_ttm": money(m.revenue_ttm, r.financial_currency),
            "net_income_ttm": money(m.net_income_ttm, r.financial_currency),
            **{k: (round(getattr(m, k), 2) if getattr(m, k) is not None else None) for k in _RATIOS},
            "missing_metrics": r.missing_metrics,
            "warnings": r.warnings,
        })
    return rows


def build_agent_input(
    fin: CompanyFinancials,
    source_catalog: dict[str, str],
    financial: FinancialResearchOutput | None,
    filings: FilingsResearchOutput | None,
    market: MarketResearchOutput | None,
    stage_errors: dict[str, str],
) -> str:
    det = json.loads(fin_input(fin))
    det["provider_data"].pop("business_summary", None)
    det["display"] = {
        "market_cap": money(fin.market_cap, fin.currency),
        "revenue_ttm": money(fin.revenue, fin.financial_currency),
        "net_income_ttm": money(fin.net_income, fin.financial_currency),
    }
    filings_data = None
    if filings:
        filings_data = filings.model_dump(exclude={"source"})
        s = filings.source
        filings_data["filing"] = {"form": s.form_type, "filing_date": s.filing_date,
                                  "period_of_report": s.period_of_report}
    market_data = None
    if market:
        market_data = market.model_dump(
            include={"comparable_companies", "recent_company_developments", "industry_context",
                     "important_market_trends", "rejected_peers", "data_limitations", "warnings"}
        )
    payload = {
        "source_catalog": source_catalog,
        "company": {
            "name": fin.company_name,
            "ticker": fin.ticker,
            "sector": fin.sector,
            "industry": fin.industry,
            "business_summary": (fin.business_summary or "")[:_SUMMARY_MAX_CHARS] or None,
        },
        "deterministic_financials": det,
        "financial_agent": financial.model_dump() if financial else None,
        "filings_agent": filings_data,
        "market_agent": market_data,
        "comps": {"rows": _comps_rows(market), "ratio_summary": ratio_summary(market)} if market else None,
        "stage_errors": stage_errors or None,
    }
    return json.dumps(payload, indent=1, ensure_ascii=False)


def create_analyst_agent(model: str | None = None) -> Agent:
    return Agent(
        name="AnalystAgent",
        instructions=INSTRUCTIONS,
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        output_type=AnalystOutput,
    )


def claims(out: AnalystOutput) -> list[Claim]:
    return [
        out.company_overview, *out.financial_assessment, *out.peer_comparison,
        *out.thesis_support, *out.thesis_challenges, *out.key_risks,
        *out.recent_developments, *out.industry_context,
    ]


ID_RE = re.compile(r"\b[A-Z]{2,6}-\d{2}\b")
_NUM_RE = re.compile(r"(?<![A-Za-z0-9-])\d[\d,]*(?:\.\d+)?")


def ungrounded_numbers(texts: list[str], reference: str) -> list[str]:
    """Numbers in `texts` that never appear in `reference` (commas ignored). Heuristic."""
    ref = reference.replace(",", "")
    found = set()
    for text in texts:
        for tok in _NUM_RE.findall(text):
            tok = tok.replace(",", "").rstrip(".")
            if len(tok) > 1 and tok not in ref:
                found.add(tok)
    return sorted(found)


# Valuation judgements the data cannot support (no valuation model is supplied).
VALUATION_RE = re.compile(
    r"under-?valu|over-?valu|\bcheap|expensive|bargain|"
    r"(attractive|favou?rabl)\w*\s+(valu|multiple|pric)|compares? favou?rabl",
    re.IGNORECASE,
)


def valuation_terms(texts: list[str]) -> list[str]:
    return sorted({m.group(0).lower() for t in texts for m in VALUATION_RE.finditer(t)})


def validate_output(out: AnalystOutput, known_ids: set[str]) -> list[str]:
    """Hard problems (empty = valid): unknown/missing source ids, valuation judgements."""
    problems = []
    cited = {i for c in claims(out) for i in c.source_ids}
    cited |= set(ID_RE.findall(out.signal_reasoning))
    unknown = sorted(cited - known_ids)
    if unknown:
        problems.append(f"unknown source ids: {', '.join(unknown)}")
    for c in claims(out):
        if not c.source_ids:
            problems.append(f"claim without source_ids: '{c.statement[:60]}'")
    terms = valuation_terms(_texts(out) + out.what_would_change_the_view + out.data_limitations)
    if terms:
        problems.append(f"valuation judgement terms: {', '.join(terms)}")
    return problems


def _texts(out: AnalystOutput) -> list[str]:
    return [c.statement for c in claims(out)] + [out.investment_thesis, out.signal_reasoning]


async def run_analyst(
    fin: CompanyFinancials,
    source_catalog: dict[str, str],
    financial: FinancialResearchOutput | None,
    filings: FilingsResearchOutput | None,
    market: MarketResearchOutput | None,
    stage_errors: dict[str, str] | None = None,
    model: str | None = None,
    on_retry: Callable[[str], None] | None = None,
) -> tuple[AnalystResult, Usage]:
    """Returns (synthesis with code-attached source ids and warnings, token usage over all attempts).

    Validates source ids; on failure retries once with corrective feedback. Numbers
    not found in the input are reported as validation warnings (heuristic, no retry).
    `on_retry(reason)` is called when the corrective retry is triggered.
    """
    agent = create_analyst_agent(model)
    prompt = build_agent_input(fin, source_catalog, financial, filings, market, stage_errors or {})
    result = await Runner.run(agent, prompt)
    usage = result.context_wrapper.usage
    out = result.final_output

    known = set(source_catalog)
    problems = validate_output(out, known)
    if problems:
        if on_retry:
            on_retry("; ".join(problems))
        retry_prompt = (
            f"{prompt}\n\nYour previous answer had grounding problems: {'; '.join(problems)}. "
            "Rewrite the full analysis citing only ids from source_catalog, and describe "
            "valuation differences factually without valuation judgement terms."
        )
        retry = await Runner.run(agent, retry_prompt)
        usage.add(retry.context_wrapper.usage)
        out = retry.final_output
        problems = validate_output(out, known)

    warnings = [f"Analyst validation: {p}" for p in problems]
    numbers = ungrounded_numbers(_texts(out), prompt)
    if numbers:
        warnings.append(f"Analyst numbers not found in its input: {', '.join(numbers)}")

    cited = {i for c in claims(out) for i in c.source_ids} | set(ID_RE.findall(out.signal_reasoning))
    data = out.model_dump() | {"ticker": fin.ticker, "company": fin.company_name or out.company}
    return AnalystResult(
        **data, supporting_source_ids=sorted(cited & known), validation_warnings=warnings
    ), usage
