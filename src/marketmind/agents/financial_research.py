"""Financial Research Agent (OpenAI Agents SDK).

Analyses a CompanyFinancials snapshot supplied by the caller. It has no tools
and never fetches data itself.
"""

from __future__ import annotations

import json
import os
import re
from statistics import mean

from agents import Agent, Runner
from agents.usage import Usage
from pydantic import BaseModel, Field

from marketmind.data.financials import CompanyFinancials

DEFAULT_MODEL = "gpt-4.1-mini"


class FinancialResearchOutput(BaseModel):
    company: str
    ticker: str
    financial_summary: str = Field(description="2-3 sentences. Interpretation of the supplied data.")
    key_strengths: list[str] = Field(description="Max 4 short bullets.")
    key_risks: list[str] = Field(description="Max 4 short bullets.")
    notable_trends: list[str] = Field(description="Max 4 short bullets, from the price history.")
    data_limitations: list[str] = Field(description="Missing/ambiguous fields and caveats.")


INSTRUCTIONS = """\
You are a financial research analyst. You receive a JSON snapshot with two parts:
- "provider_data": raw values from the data provider (facts, do not alter).
- "derived_stats": deterministic statistics computed by our code from the
  provider data and price history (e.g. net_margin_pct, total_return_pct).

Grounding rules (strict):
- Every analytical claim must be directly grounded in a value in provider_data
  or derived_stats, and must cite that value. If you cannot cite one, omit it.
- Use NO outside knowledge: no statements about the company's products,
  strategy, industry dynamics (e.g. cyclicality), competitors, news or events.
- Do not compute anything yourself (no percentages, ratios, differences,
  averages, comparisons of magnitude). Use derived_stats values exactly as
  given; if a needed number is not supplied, omit the claim.
- Prefer quoting derived_stats.price_history.labeled_facts verbatim over
  restating numbers in your own words.
- Directional stats are explicit: last_close_vs_high_pct is how far the last
  close is below/above the period high; high_vs_last_close_pct is how far the
  high is above the last close. Quote the correct one; never reverse them.
- provider_data.current_price (provider's reported price) and
  derived_stats.price_history.last_historical_close (final close in the
  history) can differ. Whenever you cite either, name it by that label.
- Valuation ratios (P/E, P/S, P/B, PEG, EV/EBITDA, etc.) may be stated and
  described as high/low only in plain numeric terms. Do NOT use them to infer
  leverage, debt, undervaluation, overvaluation, expensiveness, risk of
  downside, or growth expectations. No such conclusion is allowed because no
  debt, peer or benchmark data is supplied. Forward EPS vs trailing EPS may be
  stated as provider figures without further interpretation.
- Do not invent, estimate or fill missing values. Report null/missing fields
  under data_limitations.
- The price history covers only the stated period (start_date to end_date).
  Refer to that period (e.g. "2-year high", "since 2024-09-30"). Never say
  "all-time high/low" or make claims about prices outside the period.
- Revenue, net income and EPS are trailing-twelve-month provider figures;
  forward EPS / forward P/E are provider estimates. Label them as such.
- Phrase interpretation with "suggests" / "indicates"; keep it separate from
  the raw figures. No price predictions, no buy/sell/hold advice.
- Be concise: summary of 2-3 sentences, at most 4 bullets per list, one line each.
"""


def _labeled_price_facts(start, end, first, last, hi, lo, total_ret, vs_high) -> list[str]:
    """Unambiguous statements the model can quote instead of reasoning about direction."""
    rel = "below" if vs_high < 0 else "above"
    return [
        f"Period covered: {start} to {end}.",
        f"first_historical_close on {start} was {first}; last_historical_close on {end} was {last}.",
        f"Total return over the period, first to last historical close, was {total_ret}%.",
        f"The period high close was {hi.close} on {hi.date}; the period low close was {lo.close} on {lo.date}.",
        f"last_historical_close is {abs(vs_high)}% {rel} the period high close.",
    ]


def _summarize_history(fin: CompanyFinancials) -> dict:
    """Compact the daily history into stats + monthly closes to save tokens."""
    hist = fin.price_history
    if not hist:
        return {}
    closes = [p.close for p in hist]
    monthly: dict[str, float] = {}
    for p in hist:  # last close of each month wins
        monthly[p.date[:7]] = p.close
    last = closes[-1]
    hi = max(hist, key=lambda p: p.close)
    lo = min(hist, key=lambda p: p.close)
    return {
        "start_date": hist[0].date,
        "end_date": hist[-1].date,
        "trading_days": len(hist),
        "first_historical_close": closes[0],
        "last_historical_close": last,
        "total_return_pct": round((last / closes[0] - 1) * 100, 1),
        "high": {"date": hi.date, "close": hi.close},
        "low": {"date": lo.date, "close": lo.close},
        "last_close_vs_high_pct": round((last / hi.close - 1) * 100, 1),
        "high_vs_last_close_pct": round((hi.close / last - 1) * 100, 1),
        "avg_close": round(mean(closes), 2),
        "monthly_closes": monthly,
        "labeled_facts": _labeled_price_facts(
            hist[0].date, hist[-1].date, closes[0], last, hi, lo,
            round((last / closes[0] - 1) * 100, 1),
            round((last / hi.close - 1) * 100, 1),
        ),
    }


def _fundamental_stats(fin: CompanyFinancials) -> dict:
    stats: dict = {}
    if fin.revenue and fin.net_income is not None:
        stats["net_margin_pct"] = round(fin.net_income / fin.revenue * 100, 1)
    return stats


def build_agent_input(fin: CompanyFinancials) -> str:
    data = fin.to_dict()
    data.pop("price_history")
    derived = {**_fundamental_stats(fin), "price_history": _summarize_history(fin)}
    payload = {"provider_data": data, "derived_stats": derived}
    return json.dumps(payload, indent=1)


def create_financial_research_agent(model: str | None = None) -> Agent:
    return Agent(
        name="FinancialResearchAgent",
        instructions=INSTRUCTIONS,
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        output_type=FinancialResearchOutput,
    )


# Small, explicit list of clearly prohibited conclusions. Not exhaustive by design.
_BANNED_PATTERNS = [
    r"under-?valu", r"over-?valu", r"expensive", r"\bcheap", r"reasonable",
    r"all-time", r"leverage", r"cyclical", r"high valuation",
]
_BANNED_RE = re.compile("|".join(_BANNED_PATTERNS), re.IGNORECASE)


def validate_output(out: FinancialResearchOutput) -> list[str]:
    """Return the prohibited phrases found in the analysis text (empty = valid)."""
    text = " ".join(
        [out.financial_summary, *out.key_strengths, *out.key_risks,
         *out.notable_trends, *out.data_limitations]
    )
    return sorted({m.group(0).lower() for m in _BANNED_RE.finditer(text)})


async def run_financial_research(
    fin: CompanyFinancials, model: str | None = None
) -> tuple[FinancialResearchOutput, Usage]:
    """Returns (analysis, token usage summed over all attempts).

    Validates the output; on failure retries once with corrective feedback. If the
    retry still fails, the violations are recorded in data_limitations.
    Usage is the hook for later per-agent cost tracking.
    """
    agent = create_financial_research_agent(model)
    prompt = build_agent_input(fin)
    result = await Runner.run(agent, prompt)
    usage = result.context_wrapper.usage
    out = result.final_output

    violations = validate_output(out)
    if violations:
        retry_prompt = (
            f"{prompt}\n\nYour previous answer used prohibited terms: {', '.join(violations)}. "
            "Rewrite the full analysis without them and without the conclusions they imply "
            "(valuation judgements, leverage, cyclicality, all-time claims)."
        )
        retry = await Runner.run(agent, retry_prompt)
        usage.add(retry.context_wrapper.usage)
        out = retry.final_output
        violations = validate_output(out)
        if violations:
            out.data_limitations.append(
                f"Validation warning: output still contains prohibited terms ({', '.join(violations)})."
            )
    return out, usage
