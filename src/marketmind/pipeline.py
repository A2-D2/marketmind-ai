"""Full research pipeline: deterministic, sequential orchestration.

Ticker -> Financial Agent -> Filings Agent -> Market/Comps Agent -> Analyst Agent -> Writer Agent

No router or autonomy: each stage runs once in a fixed order. A failed research
stage (2 or 3) is recorded and the run continues with that component missing;
financial data (stage 1) is required. Token usage is captured per agent.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone

from agents.usage import Usage

from marketmind.agents.analyst import COMPS_ID, FIN_ID, AnalystResult, run_analyst
from marketmind.agents.filings_research import FilingsResearchOutput, run_filings_research
from marketmind.agents.financial_research import FinancialResearchOutput, run_financial_research
from marketmind.agents.market_research import MarketResearchOutput, run_market_research
from marketmind.agents.writer import ReportDraft, SourceRef, render_report, run_writer
from marketmind.data.filings import FilingEvidence, get_latest_10k_evidence
from marketmind.data.financials import CompanyFinancials, get_company_financials
from marketmind.data.web_research import WebResearchEvidence, get_web_research_evidence

STAGES = [
    "Financial research",
    "SEC filings research",
    "Market/comps research",
    "Analyst synthesis",
    "Writing report",
]


@dataclass
class AgentUsage:
    agent: str
    requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0

    @classmethod
    def from_usage(cls, agent: str, u: Usage) -> AgentUsage:
        return cls(agent, u.requests, u.input_tokens, u.output_tokens, u.total_tokens)


@dataclass
class ResearchRun:
    ticker: str
    started_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    financials: CompanyFinancials | None = None
    financial: FinancialResearchOutput | None = None
    filing_evidence: FilingEvidence | None = None
    filings: FilingsResearchOutput | None = None
    web_evidence: WebResearchEvidence | None = None
    market: MarketResearchOutput | None = None
    analysis: AnalystResult | None = None
    draft: ReportDraft | None = None
    report_markdown: str | None = None
    sources: dict[str, SourceRef] = field(default_factory=dict)
    usage: list[AgentUsage] = field(default_factory=list)
    completed_stages: list[str] = field(default_factory=list)
    stage_errors: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    @property
    def tavily_requests(self) -> int:
        return self.web_evidence.tavily_requests if self.web_evidence else 0

    @property
    def combined_usage(self) -> AgentUsage:
        total = AgentUsage("Combined")
        for u in self.usage:
            total.requests += u.requests
            total.input_tokens += u.input_tokens
            total.output_tokens += u.output_tokens
            total.total_tokens += u.total_tokens
        return total

    def retry_hook(self, agent: str) -> Callable[[str], None]:
        """Records why an agent's one-time corrective retry was triggered."""
        return lambda reason: self.warnings.append(f"{agent} retry triggered: {reason}")

    def usage_lines(self) -> list[str]:
        lines = [
            f"{u.agent}: requests={u.requests}, input={u.input_tokens:,}, "
            f"output={u.output_tokens:,}, total={u.total_tokens:,} tokens"
            for u in [*self.usage, self.combined_usage]
        ]
        return lines + [f"Tavily requests: {self.tavily_requests}"]


def build_source_map(run: ResearchRun) -> dict[str, SourceRef]:
    """Every citable id -> provenance, copied from the retrieval layers (never from an LLM)."""
    fin = run.financials
    sources = {
        FIN_ID: SourceRef(FIN_ID, "yfinance", f"yfinance snapshot for {fin.ticker} ({fin.company_name})",
                          date=fin.retrieved_at),
    }
    if run.market:
        tickers = ", ".join(r.ticker for r in run.market.comps_dataset)
        sources[COMPS_ID] = SourceRef(COMPS_ID, "yfinance", f"Comparable-company dataset: {tickers}",
                                      date=fin.retrieved_at)
    if run.filing_evidence and run.filings:
        fe = run.filing_evidence
        for e in fe.excerpts:
            sources[e.evidence_id] = SourceRef(
                e.evidence_id, "sec_10k",
                f"{fe.form_type} Item 1A: {e.heading or e.category or 'Risk factor excerpt'}",
                url=fe.primary_document_url, date=fe.filing_date,
            )
    if run.web_evidence and run.market:
        for s in run.web_evidence.sources:
            sources[s.source_id] = SourceRef(s.source_id, "tavily", s.title, url=s.url, date=s.published_date)
    return sources


def _catalog(sources: dict[str, SourceRef]) -> dict[str, str]:
    return {sid: f"{s.kind}: {s.title}"[:140] for sid, s in sources.items()}


async def run_full_research(
    ticker: str, progress: Callable[[int, str], None] = lambda i, name: None
) -> ResearchRun:
    """Run all five stages once, sequentially. `progress(i, name)` is called before each stage."""
    run = ResearchRun(ticker=ticker.strip().upper())

    progress(1, STAGES[0])
    fin = get_company_financials(run.ticker)
    run.financials = fin
    if not fin.company_name and not fin.price_history:
        raise ValueError(f"No financial data for {run.ticker}: {'; '.join(fin.warnings)}")
    run.warnings += [f"yfinance: {w}" for w in fin.warnings]
    try:
        run.financial, u = await run_financial_research(
            fin, on_retry=run.retry_hook("FinancialResearchAgent")
        )
        run.usage.append(AgentUsage.from_usage("FinancialResearchAgent", u))
        run.completed_stages.append(STAGES[0])
    except Exception as exc:  # LLM/API failure: deterministic data is still used downstream
        run.stage_errors[STAGES[0]] = f"{type(exc).__name__}: {exc}"

    progress(2, STAGES[1])
    try:
        run.filing_evidence = get_latest_10k_evidence(run.ticker)
        run.warnings += [f"SEC: {w}" for w in run.filing_evidence.warnings]
        run.filings, u = await run_filings_research(
            run.filing_evidence, on_retry=run.retry_hook("FilingsResearchAgent")
        )
        run.usage.append(AgentUsage.from_usage("FilingsResearchAgent", u))
        run.completed_stages.append(STAGES[1])
    except Exception as exc:
        run.stage_errors[STAGES[1]] = f"{type(exc).__name__}: {exc}"

    progress(3, STAGES[2])
    try:
        run.web_evidence = get_web_research_evidence(run.ticker, financials=fin)
        run.market, u = await run_market_research(
            run.web_evidence, fin, on_retry=run.retry_hook("MarketResearchAgent")
        )
        run.usage.append(AgentUsage.from_usage("MarketResearchAgent", u))
        run.warnings += [f"Market: {w}" for w in run.market.warnings]
        run.completed_stages.append(STAGES[2])
    except Exception as exc:
        run.stage_errors[STAGES[2]] = f"{type(exc).__name__}: {exc}"

    run.sources = build_source_map(run)

    progress(4, STAGES[3])
    run.analysis, u = await run_analyst(
        fin, _catalog(run.sources), run.financial, run.filings, run.market, run.stage_errors,
        on_retry=run.retry_hook("AnalystAgent"),
    )
    run.usage.append(AgentUsage.from_usage("AnalystAgent", u))
    run.warnings += run.analysis.validation_warnings
    run.completed_stages.append(STAGES[3])

    progress(5, STAGES[4])
    run.draft, writer_warnings, u = await run_writer(
        run.analysis, run.sources, on_retry=run.retry_hook("WriterAgent")
    )
    run.usage.append(AgentUsage.from_usage("WriterAgent", u))
    run.warnings += writer_warnings
    run.completed_stages.append(STAGES[4])

    run.warnings += [f"Stage failed - {k}: {v}" for k, v in run.stage_errors.items()]
    run.report_markdown = render_report(
        run.draft, run.analysis, fin, run.filings, run.market, run.sources,
        run.warnings, run.usage_lines(), run.started_at,
    )
    return run
