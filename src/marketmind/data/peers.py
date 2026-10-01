"""Peer name -> ticker resolution via yfinance. No LLM logic lives here.

Peer *names* come from web evidence (proposed by an agent, each citing source
ids). Tickers are never trusted from the LLM: this module verifies each name
appears in a cited excerpt, resolves it with yfinance search, picks the primary
home-market common-stock listing (US listing only as fallback), and validates
it through the existing financial data layer. Currencies are never converted.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

import yfinance as yf

from marketmind.data.financials import CompanyFinancials, get_company_financials
from marketmind.data.web_research import WebSource

DEFAULT_MAX_PEERS = 5

US_EXCHANGES = {"NMS", "NGM", "NCM", "NAS", "NYQ", "NYS", "ASE", "PCX", "BTS"}
# Primary home-market exchanges (Yahoo codes) by yfinance `country`.
HOME_EXCHANGES = {
    "United States": US_EXCHANGES,
    "South Korea": {"KSC", "KOE"},
    "Japan": {"JPX"},
    "Taiwan": {"TAI", "TWO"},
    "China": {"SHH", "SHZ"},
    "Hong Kong": {"HKG"},
    "Netherlands": {"AMS"},
    "Germany": {"GER"},
    "France": {"PAR"},
    "United Kingdom": {"LSE"},
    "Switzerland": {"EBS"},
    "Canada": {"TOR"},
    "India": {"NSI"},
    "Australia": {"ASX"},
}
_PRODUCT_RE = re.compile(
    r"\b(\d+(\.\d+)?x|leverage[d]?|inverse|etp|etf|etn|tracker|daily|warrant|cdr)\b",
    re.IGNORECASE,
)
_NAME_STOPWORDS = {"inc", "corp", "corporation", "co", "ltd", "plc", "holdings", "the", "company", "group"}


@dataclass
class PeerCandidate:
    name: str  # company name as written in the evidence
    source_ids: list[str]  # WEB-xx ids that mention it


@dataclass
class ResolvedPeer:
    peer_name: str  # original name from the evidence
    source_ids: list[str]
    ticker: str
    exchange: str | None
    currency: str | None  # reporting currency of the listing; never converted
    company_name: str | None  # as reported by yfinance
    country: str | None
    listing_basis: str  # "home-market listing" | "US listing (no home-market listing found)"
    financials: CompanyFinancials | None = None


@dataclass
class RejectedPeer:
    peer_name: str
    source_ids: list[str]
    reason: str


@dataclass
class PeerResolution:
    target_ticker: str
    peers: list[ResolvedPeer] = field(default_factory=list)
    rejected: list[RejectedPeer] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip().lower()


def _compact(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (text or "").lower())


def _key_token(name: str) -> str:
    """First distinctive word of a company name, e.g. 'SK Hynix' -> 'hynix'."""
    words = re.findall(r"[a-z0-9]+", name.lower())
    return next((w for w in words if len(w) >= 3 and w not in _NAME_STOPWORDS), _compact(name))


def name_in_sources(name: str, source_ids: list[str], sources: dict[str, WebSource]) -> list[str]:
    """Cited source ids whose title/excerpt actually contain `name` (case/space-insensitive)."""
    needle = _norm(name)
    return [
        sid
        for sid in source_ids
        if sid in sources and needle in _norm(f"{sources[sid].title} {sources[sid].excerpt}")
    ]


def _equity_quotes(name: str) -> list[dict]:
    """yfinance search hits that are plain common-stock listings matching the name."""
    token = _key_token(name)
    out = []
    for q in yf.Search(name, max_results=10, news_count=0).quotes:
        label = f"{q.get('longname') or ''} {q.get('shortname') or ''}"
        if q.get("quoteType") != "EQUITY" or _PRODUCT_RE.search(label):
            continue  # ETFs, futures, leveraged/derivative products
        if token not in _compact(label):
            continue  # search returned an unrelated company
        out.append(q)
    return out


def _pick_listing(quotes: list[dict]) -> tuple[dict, str, str | None] | None:
    """Prefer the home-market listing for the company's country; US listing as fallback."""
    if not quotes:
        return None
    try:
        country = yf.Ticker(quotes[0]["symbol"]).info.get("country")
    except Exception:
        country = None
    home = HOME_EXCHANGES.get(country or "", set())
    for q in quotes:
        if q.get("exchange") in home:
            return q, "home-market listing", country
    for q in quotes:
        if q.get("exchange") in US_EXCHANGES:
            return q, "US listing (no home-market listing found)", country
    return None  # only OTC / secondary venues


def resolve_peers(
    target_ticker: str,
    candidates: list[PeerCandidate],
    sources: list[WebSource],
    target_company_name: str | None = None,
    max_peers: int = DEFAULT_MAX_PEERS,
) -> PeerResolution:
    """Verify, resolve and validate peer names. Never raises for individual peers."""
    target = target_ticker.strip().upper()
    result = PeerResolution(target_ticker=target)
    by_id = {s.source_id: s for s in sources}
    target_key = _key_token(target_company_name) if target_company_name else None
    seen_tickers = {target}

    def reject(c: PeerCandidate, reason: str) -> None:
        result.rejected.append(RejectedPeer(c.name, c.source_ids, reason))

    for c in candidates:
        if len(result.peers) >= max_peers:
            reject(c, f"not needed (already have {max_peers} peers)")
            continue
        unknown = [s for s in c.source_ids if s not in by_id]
        if unknown:
            reject(c, f"cites unknown source ids: {', '.join(unknown)}")
            continue
        verified = name_in_sources(c.name, c.source_ids, by_id)
        if not verified:
            reject(c, "name not found in any cited source excerpt")
            continue
        if target_key and target_key == _key_token(c.name):
            reject(c, "is the target company")
            continue

        try:
            picked = _pick_listing(_equity_quotes(c.name))
        except Exception as exc:  # network errors, rate limits
            reject(c, f"yfinance search failed: {exc}")
            continue
        if picked is None:
            reject(c, "no primary common-stock listing found (only OTC/secondary/derivative)")
            continue
        quote, basis, country = picked
        ticker = quote["symbol"].upper()
        if ticker in seen_tickers:
            reject(c, f"resolves to {ticker}, already included or the target")
            continue

        fin = get_company_financials(ticker, history_period="5d")
        if not fin.company_name or fin.market_cap is None:
            reject(c, f"resolved to {ticker} but financial data is incomplete (no name/market cap)")
            continue
        seen_tickers.add(ticker)
        result.peers.append(
            ResolvedPeer(
                peer_name=c.name,
                source_ids=verified,
                ticker=ticker,
                exchange=quote.get("exchange"),
                currency=fin.currency,
                company_name=fin.company_name,
                country=country,
                listing_basis=basis,
                financials=fin,
            )
        )

    if len(result.peers) < 3:
        result.warnings.append(f"Only {len(result.peers)} valid peers resolved (target is 3-5).")
    currencies = {p.currency for p in result.peers if p.currency}
    if len(currencies) > 1:
        result.warnings.append(
            f"Peers report in multiple currencies ({', '.join(sorted(currencies))}); "
            "values are not converted, so absolute figures are not directly comparable."
        )
    return result
