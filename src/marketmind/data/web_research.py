"""Web research retrieval via Tavily. No LLM logic lives here.

Runs a small, fixed set of focused Tavily searches for any ticker (peer
companies, recent company news, recent industry developments) and returns a
bounded evidence bundle: title, URL, published date and a capped excerpt per
result. Full pages and Tavily's LLM-generated "answer" are never requested, so
downstream LLM context stays small and every statement traces to a source URL.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from tavily import TavilyClient

from marketmind.data.financials import CompanyFinancials, get_company_financials

TAVILY_SETUP_MESSAGE = (
    "TAVILY_API_KEY not set. Add TAVILY_API_KEY=tvly-... to .env (see .env.example)."
)

DEFAULT_MAX_RESULTS = 5  # per query
_EXCERPT_MAX_CHARS = 500
_SEARCH_TIMEOUT = 20  # seconds per Tavily request


class TavilyKeyError(RuntimeError):
    """Raised before any Tavily request when TAVILY_API_KEY is missing."""


def require_tavily_key() -> str:
    """Return the Tavily API key from the environment (.env), or raise with setup help."""
    key = (os.getenv("TAVILY_API_KEY") or "").strip().strip('"').strip("'")
    if not key:
        raise TavilyKeyError(TAVILY_SETUP_MESSAGE)
    return key


@dataclass
class WebSource:
    source_id: str  # stable id the agent must cite, e.g. "WEB-03"
    query_purpose: str  # "peers" | "company_news" | "industry_news"
    title: str
    url: str
    published_date: str | None  # as reported by Tavily (news topic only); never guessed
    excerpt: str  # Tavily's result snippet, capped
    score: float | None = None  # Tavily relevance score
    truncated: bool = False


@dataclass
class SearchQuery:
    purpose: str
    query: str
    topic: str
    time_range: str | None
    result_count: int = 0
    error: str | None = None


@dataclass
class WebResearchEvidence:
    ticker: str
    data_provider: str = "Tavily Search API"
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    business_keyword: str | None = None  # derived from the yfinance business summary
    queries: list[SearchQuery] = field(default_factory=list)
    tavily_requests: int = 0
    tavily_credits: float | None = None  # if reported by the API
    sources: list[WebSource] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def extracted_chars(self) -> int:
        return sum(len(s.title) + len(s.excerpt) for s in self.sources)

    @property
    def approx_tokens(self) -> int:
        return round(self.extracted_chars / 4)  # rough English-text heuristic

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["extracted_chars"] = self.extracted_chars
        data["approx_tokens"] = self.approx_tokens
        return data


def _clean(text: str) -> str:
    text = re.sub(r"[#*_`>|]+", " ", text or "")  # strip markdown residue in snippets
    return re.sub(r"\s+", " ", text).strip()


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    end = cut.rfind(". ")  # prefer a sentence boundary
    if end > limit // 2:
        cut = cut[: end + 1]
    return cut.rstrip() + " ...", True


# "... sells memory and storage products in ..." -> "memory and storage products"
_OFFERING_RE = re.compile(
    r"\b(?:designs|develops|manufactures|sells|markets|provides|offers|operates as an?)\s+"
    r"(.+?)(?=\s+(?:in|for|to|across|through|worldwide|globally|internationally)\b|[,;.]|$)"
)
_GENERIC_WORDS = {"products", "product", "solutions", "services", "company", "a", "an", "the"}


def business_keyword(summary: str | None, industry: str | None) -> str | None:
    """Short business phrase from the yfinance summary's first offering clause.

    Deterministic; falls back to the industry when no clause is found.
    """
    m = _OFFERING_RE.search((summary or "")[:400])
    if m:
        words = [w for w in m.group(1).split() if w.lower() not in _GENERIC_WORDS][:5]
        if words:
            return " ".join(words)
    return industry


def _build_queries(
    symbol: str, name: str, industry: str | None, keyword: str | None
) -> list[SearchQuery]:
    queries = [
        SearchQuery(
            "peers",
            f"{name} ({symbol}) publicly traded competitors and peer companies stock tickers",
            topic="general",
            time_range="year",
        ),
        SearchQuery(
            "company_news",
            f"{name} {symbol} stock news",
            topic="news",
            time_range="month",
        ),
        SearchQuery(
            "industry_news",
            f"{keyword or name} market demand pricing outlook",
            topic="news",
            time_range="month",
        ),
    ]
    for q in queries:
        q.query = re.sub(r"\s+", " ", q.query).strip()  # drop gaps from missing fields
    return queries


def get_web_research_evidence(
    ticker: str,
    financials: CompanyFinancials | None = None,
    max_results: int = DEFAULT_MAX_RESULTS,
) -> WebResearchEvidence:
    """Run focused Tavily searches for any ticker and return bounded, source-tagged evidence.

    Company name / industry come from the yfinance layer (pass `financials` to
    reuse an existing snapshot). Raises TavilyKeyError if TAVILY_API_KEY is
    missing (checked before any request). Search failures never raise; they are
    recorded per query and in `warnings`.
    """
    symbol = ticker.strip().upper()
    result = WebResearchEvidence(ticker=symbol)
    if not symbol:
        result.warnings.append("Empty ticker.")
        return result

    client = TavilyClient(api_key=require_tavily_key())  # raises before any request

    fin = financials if financials is not None else get_company_financials(symbol, "5d")
    result.company_name = fin.company_name
    result.sector = fin.sector
    result.industry = fin.industry
    if not fin.company_name:
        result.warnings.append("Company name unavailable from yfinance; searching by ticker only.")
    if not fin.industry:
        result.warnings.append("Industry unavailable from yfinance; industry query is generic.")
    result.business_keyword = business_keyword(fin.business_summary, fin.industry)
    if not fin.business_summary:
        result.warnings.append("Business summary unavailable; peer query uses industry keyword.")

    seen_urls: set[str] = set()
    credits = 0.0
    for q in _build_queries(
        symbol, fin.company_name or symbol, fin.industry, result.business_keyword
    ):
        result.queries.append(q)
        result.tavily_requests += 1
        try:
            resp = client.search(
                q.query,
                search_depth="basic",
                topic=q.topic,
                time_range=q.time_range,
                max_results=max_results,
                include_answer=False,
                include_raw_content=False,
                include_images=False,
                include_usage=True,
                timeout=_SEARCH_TIMEOUT,
            )
        except Exception as exc:  # invalid key, rate limit, network, timeout
            q.error = f"{type(exc).__name__}: {exc}"
            result.warnings.append(f"Tavily search failed for '{q.purpose}': {q.error}")
            continue

        usage = resp.get("usage") or {}
        if isinstance(usage.get("credits"), (int, float)):
            credits += usage["credits"]

        for item in resp.get("results") or []:
            url = (item.get("url") or "").strip()
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            excerpt, cut = _truncate(_clean(item.get("content") or ""), _EXCERPT_MAX_CHARS)
            q.result_count += 1
            result.sources.append(
                WebSource(
                    source_id=f"WEB-{len(result.sources) + 1:02d}",
                    query_purpose=q.purpose,
                    title=_clean(item.get("title") or "") or url,
                    url=url,
                    published_date=item.get("published_date") or None,
                    excerpt=excerpt,
                    score=item.get("score"),
                    truncated=cut,
                )
            )

    result.tavily_credits = credits or None
    if not result.sources:
        result.warnings.append("No Tavily results returned.")
    elif any(s.published_date is None for s in result.sources):
        result.warnings.append("Some sources have no published date (Tavily general-topic results).")
    return result
