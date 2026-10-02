"""Writer Agent (OpenAI Agents SDK) and Markdown report rendering.

The Writer turns the Analyst's structured output into clear report prose with
inline [ID] citations. It does no research. Numeric tables, the filing
reference, the signal value and the Sources list (titles, URLs, dates) are
rendered by code from upstream data, so the LLM cannot alter numbers or URLs.
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass

from agents import Agent, Runner
from agents.usage import Usage
from pydantic import BaseModel, Field

from marketmind.agents.analyst import (
    ID_RE,
    AnalystResult,
    money,
    ungrounded_numbers,
    valuation_terms,
)
from marketmind.agents.filings_research import FilingsResearchOutput
from marketmind.agents.financial_research import build_agent_input as fin_input
from marketmind.agents.market_research import MarketResearchOutput
from marketmind.data.financials import CompanyFinancials

DEFAULT_MODEL = "gpt-4.1-mini"


@dataclass
class SourceRef:
    """One citable source, built by the pipeline from upstream provenance."""

    source_id: str
    kind: str  # "yfinance" | "sec_10k" | "tavily"
    title: str
    url: str | None = None
    date: str | None = None


class ReportDraft(BaseModel):
    """Prose sections the LLM writes. Bullets end with [ID] citations."""

    company_overview: str = Field(description="2-3 sentences.")
    key_financials_commentary: str = Field(description="2-3 sentences on the financial assessment.")
    comparable_companies_commentary: str = Field(description="2-3 sentences on the peer comparison.")
    investment_thesis: str = Field(description="One short paragraph.")
    evidence_supporting: list[str]
    challenges: list[str]
    sec_risk_factors: list[str]
    recent_developments: list[str]
    industry_context: list[str]
    signal_reasoning: str
    what_would_change_the_view: list[str]
    unresolved_questions: list[str]
    data_limitations: list[str]


INSTRUCTIONS = """\
You are the editor of an equity research report. You receive JSON with:
- "analysis": the analyst's structured synthesis. Each claim has a statement,
  a basis ("fact" or "interpretation") and source_ids.
- "sources": the id -> title/type map of every citable source.

Your job is clear communication, NOT new research:
- Use only content in "analysis". Add no facts, numbers, names, dates,
  sources or opinions that it does not contain. Do not change any number.
- Cite with inline square brackets using the analysis' own source_ids, e.g.
  "... record quarterly revenue [WEB-06]." or "[RF-03, FIN-01]". Every factual
  sentence and every bullet in evidence_supporting, challenges,
  sec_risk_factors, recent_developments and industry_context ends with at least
  one citation. Never cite an id absent from "sources". Do not write URLs.
- Keep facts and interpretation distinct: phrase interpretation claims with
  "suggests" / "indicates"; attribute web claims ("reported by", "according to").
- SEC risk factors are possibilities, not events.
- Do not compare absolute amounts across different currencies.
- Never describe the stock or its multiples as undervalued, overvalued, cheap,
  expensive, a bargain, or attractively/favourably valued. State ratio
  differences factually, e.g. "forward P/E is lower than the available peer
  median". Peers marked as broad peers are lower confidence; say so.
- The signal itself is fixed by the analysis; explain it, do not change it.
  It is a research signal, not personalised financial advice.
- Be concise and plain: one sentence per bullet, no hype, no headings or
  Markdown inside fields.
"""


def build_agent_input(analysis: AnalystResult, sources: dict[str, SourceRef]) -> str:
    payload = {
        "analysis": analysis.model_dump(exclude={"validation_warnings"}),
        "sources": {sid: f"{s.kind}: {s.title}" for sid, s in sources.items()},
    }
    return json.dumps(payload, indent=1, ensure_ascii=False)


def create_writer_agent(model: str | None = None) -> Agent:
    return Agent(
        name="WriterAgent",
        instructions=INSTRUCTIONS,
        model=model or os.getenv("OPENAI_MODEL", DEFAULT_MODEL),
        output_type=ReportDraft,
    )


_CITED_SECTIONS = ("evidence_supporting", "challenges", "sec_risk_factors",
                   "recent_developments", "industry_context")


def _all_text(d: ReportDraft) -> list[str]:
    out = []
    for value in d.model_dump().values():
        out.extend(value if isinstance(value, list) else [value])
    return out


def validate_output(d: ReportDraft, known_ids: set[str]) -> list[str]:
    """Hard problems (empty = valid): unknown ids, uncited factual bullets, valuation judgements."""
    problems = []
    unknown = sorted({i for t in _all_text(d) for i in ID_RE.findall(t)} - known_ids)
    if unknown:
        problems.append(f"unknown citation ids: {', '.join(unknown)}")
    for section in _CITED_SECTIONS:
        for bullet in getattr(d, section):
            if not ID_RE.search(bullet):
                problems.append(f"uncited bullet in {section}: '{bullet[:60]}'")
    terms = valuation_terms(_all_text(d))
    if terms:
        problems.append(f"valuation judgement terms: {', '.join(terms)}")
    return problems


async def run_writer(
    analysis: AnalystResult,
    sources: dict[str, SourceRef],
    model: str | None = None,
    on_retry: Callable[[str], None] | None = None,
) -> tuple[ReportDraft, list[str], Usage]:
    """Returns (report prose, validation warnings, token usage over all attempts).

    Validates citations and wording; on failure retries once with corrective
    feedback. `on_retry(reason)` is called when that retry is triggered.
    """
    agent = create_writer_agent(model)
    prompt = build_agent_input(analysis, sources)
    result = await Runner.run(agent, prompt)
    usage = result.context_wrapper.usage
    draft = result.final_output

    known = set(sources)
    problems = validate_output(draft, known)
    if problems:
        if on_retry:
            on_retry("; ".join(problems))
        retry_prompt = (
            f"{prompt}\n\nYour previous answer had problems: {'; '.join(problems)}. "
            "Rewrite the full report citing only ids from 'sources' on every factual bullet, "
            "without valuation judgement terms."
        )
        retry = await Runner.run(agent, retry_prompt)
        usage.add(retry.context_wrapper.usage)
        draft = retry.final_output
        problems = validate_output(draft, known)

    warnings = [f"Writer validation: {p}" for p in problems]
    numbers = ungrounded_numbers(_all_text(draft), prompt)
    if numbers:
        warnings.append(f"Writer numbers not found in the analysis: {', '.join(numbers)}")
    return draft, warnings, usage


# ---------------------------------------------------------------- rendering


def _fmt(value, suffix: str = "") -> str:
    return "n/a" if value is None else f"{value:,.2f}{suffix}"


def _bullets(items: list[str]) -> str:
    return "\n".join(f"- {i}" for i in items) if items else "_None supplied._"


def _key_financials_table(fin: CompanyFinancials) -> str:
    det = json.loads(fin_input(fin))["derived_stats"]
    ph = det.get("price_history") or {}
    v = fin.valuation
    rows = [
        ("Current price (provider)", money(fin.current_price, fin.currency)),
        ("Market cap", money(fin.market_cap, fin.currency)),
        ("Revenue (TTM)", money(fin.revenue, fin.financial_currency)),
        ("Net income (TTM)", money(fin.net_income, fin.financial_currency)),
        ("Net margin (TTM)", _fmt(det.get("net_margin_pct"), "%") if "net_margin_pct" in det else "n/a"),
        ("Trailing EPS", _fmt(fin.eps)),
        ("Forward EPS (estimate)", _fmt(fin.forward_eps)),
        ("Trailing P/E", _fmt(v.get("trailing_pe"), "x")),
        ("Forward P/E", _fmt(v.get("forward_pe"), "x")),
        ("EV/EBITDA", _fmt(v.get("enterprise_to_ebitda"), "x")),
        ("Price/Sales", _fmt(v.get("price_to_sales"), "x")),
    ]
    if ph:
        rows.append((f"Price return {ph['start_date']} to {ph['end_date']}", f"{ph['total_return_pct']}%"))
    lines = ["| Metric | Value |", "|---|---|"] + [f"| {k} | {val or 'n/a'} |" for k, val in rows]
    return "\n".join(lines) + f"\n\n_Source: [FIN-01] {fin.data_provider}, retrieved {fin.retrieved_at}._"


def _comps_table(market: MarketResearchOutput) -> str:
    lines = [
        "| Company | Ticker | Country | Market cap | Revenue (TTM) | P/E | Fwd P/E | EV/EBITDA | P/S | Evidence |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    for r in market.comps_dataset:
        m = r.metrics
        name = f"**{r.company_name or r.peer_name}** (target)" if r.role == "target" else (r.company_name or r.peer_name)
        ev = ", ".join(r.source_ids) or "—"
        if r.peer_confidence == "broad_peer":
            ev += " (broad peer, lower confidence)"
        lines.append(
            f"| {name} | {r.ticker} | {r.country or 'n/a'} | {money(m.market_cap, r.currency) or 'n/a'} | "
            f"{money(m.revenue_ttm, r.financial_currency) or 'n/a'} | {_fmt(m.trailing_pe, 'x')} | "
            f"{_fmt(m.forward_pe, 'x')} | {_fmt(m.ev_to_ebitda, 'x')} | {_fmt(m.price_to_sales, 'x')} | {ev} |"
        )
    notes = ["_Source: [COMPS-01] yfinance. Values are in each company's own currency and are not converted; "
             "compare companies via ratios only._"]
    peers = [r for r in market.comps_dataset if r.role == "peer"]
    if peers:
        notes.append("\n**Why these peers**\n" + _bullets(
            [f"{r.company_name or r.peer_name} ({r.ticker}): {r.reason} [{', '.join(r.source_ids)}]" for r in peers]
        ))
    if market.rejected_peers:
        notes.append("\n**Considered but excluded**\n" + _bullets(
            [f"{r.name} ({r.stage}): {r.reason}" for r in market.rejected_peers]
        ))
    return "\n".join(lines) + "\n\n" + "\n".join(notes)


def render_report(
    draft: ReportDraft,
    analysis: AnalystResult,
    fin: CompanyFinancials,
    filings: FilingsResearchOutput | None,
    market: MarketResearchOutput | None,
    sources: dict[str, SourceRef],
    pipeline_warnings: list[str],
    usage_lines: list[str],
    generated_at: str,
) -> str:
    """Assemble the final Markdown report. Signal, tables and sources come from code."""
    cited = set(analysis.supporting_source_ids)
    cited |= {i for t in _all_text(draft) for i in ID_RE.findall(t)}
    cited |= {"FIN-01"} | ({"COMPS-01"} if market else set())
    source_lines = []
    for sid in sorted(cited & set(sources), key=lambda s: (s.split("-")[0], s)):
        s = sources[sid]
        extra = " — ".join(x for x in (s.date, s.url) if x)
        source_lines.append(f"- **[{sid}]** {s.title}" + (f" — {extra}" if extra else ""))

    filing_ref = ""
    if filings:
        s = filings.source
        filing_ref = (f"\n\n_Source filing: {s.form_type} filed {s.filing_date} (period {s.period_of_report}), "
                      f"accession {s.accession_number} — {s.primary_document_url}_")

    sig = analysis.investment_signal
    parts = [
        f"# MarketMind Research Report: {analysis.company} ({analysis.ticker})",
        f"_Generated {generated_at}. Research signal: **{sig}**. Research tooling only — "
        "not personalised financial advice._",
        "## Company Overview\n" + draft.company_overview,
        "## Key Financials\n" + _key_financials_table(fin) + "\n\n" + draft.key_financials_commentary,
        "## Comparable Companies\n"
        + (_comps_table(market) if market else "_Market/comps stage unavailable._")
        + "\n\n" + draft.comparable_companies_commentary,
        "## Investment Thesis\n" + draft.investment_thesis,
        "## Evidence Supporting the Thesis\n" + _bullets(draft.evidence_supporting),
        "## Challenges / Bear Case\n" + _bullets(draft.challenges),
        "## SEC Risk Factors\n" + _bullets(draft.sec_risk_factors) + filing_ref,
        "## Recent Company Developments\n" + _bullets(draft.recent_developments),
        "## Industry Context\n" + _bullets(draft.industry_context),
        f"## BUY / HOLD / SELL Signal: {sig}\n" + draft.signal_reasoning
        + "\n\n_A research signal based only on the evidence above; not a recommendation to buy or sell._",
        "## What Would Change the View?\n" + _bullets(draft.what_would_change_the_view),
        "## Open Questions\n" + _bullets(draft.unresolved_questions),
        "## Sources\n" + "\n".join(source_lines),
        "## Data Limitations\n" + _bullets(draft.data_limitations)
        + ("\n\n**Pipeline warnings**\n" + _bullets(pipeline_warnings) if pipeline_warnings else ""),
        "## Run Details\n" + _bullets(usage_lines),
    ]
    return "\n\n".join(parts) + "\n"
