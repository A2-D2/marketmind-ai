"""Financial data retrieval via yfinance. No LLM logic lives here."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

import yfinance as yf


@dataclass
class PricePoint:
    date: str
    close: float
    volume: int | None = None


@dataclass
class CompanyFinancials:
    ticker: str
    data_provider: str = "yfinance"
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    company_name: str | None = None
    sector: str | None = None
    industry: str | None = None
    business_summary: str | None = None
    currency: str | None = None  # trading currency (price, market cap)
    financial_currency: str | None = None  # reporting currency (revenue, net income, EPS)
    current_price: float | None = None
    market_cap: float | None = None
    revenue: float | None = None  # trailing twelve months
    net_income: float | None = None  # trailing twelve months
    eps: float | None = None  # trailing EPS
    forward_eps: float | None = None
    valuation: dict[str, float | None] = field(default_factory=dict)
    price_history: list[PricePoint] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


_VALUATION_KEYS = {
    "trailing_pe": "trailingPE",
    "forward_pe": "forwardPE",
    "price_to_sales": "priceToSalesTrailing12Months",
    "price_to_book": "priceToBook",
    "peg_ratio": "pegRatio",
    "enterprise_to_revenue": "enterpriseToRevenue",
    "enterprise_to_ebitda": "enterpriseToEbitda",
}


def _num(value: Any) -> float | None:
    """Return a finite number or None (yfinance may give None, strings, NaN)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value != value or value in (float("inf"), float("-inf")):
        return None
    return value


def _first_of(info: dict, *keys: str) -> Any:
    for key in keys:
        if info.get(key) is not None:
            return info[key]
    return None


def get_company_financials(ticker: str, history_period: str = "2y") -> CompanyFinancials:
    """Fetch a structured financial snapshot for any ticker.

    Never raises for missing fields; gaps are None and listed in `warnings`.
    """
    symbol = ticker.strip().upper()
    result = CompanyFinancials(ticker=symbol)
    if not symbol:
        result.warnings.append("Empty ticker.")
        return result

    stock = yf.Ticker(symbol)

    try:
        info = stock.info or {}
    except Exception as exc:  # network errors, unknown symbols, rate limits
        info = {}
        result.warnings.append(f"Could not fetch company info: {exc}")

    result.company_name = _first_of(info, "longName", "shortName")
    result.sector = info.get("sector")
    result.industry = info.get("industry")
    result.business_summary = info.get("longBusinessSummary")
    result.currency = info.get("currency")
    result.financial_currency = info.get("financialCurrency")
    result.current_price = _num(
        _first_of(info, "currentPrice", "regularMarketPrice", "previousClose")
    )
    result.market_cap = _num(info.get("marketCap"))
    result.revenue = _num(info.get("totalRevenue"))
    result.net_income = _num(info.get("netIncomeToCommon"))
    result.eps = _num(info.get("trailingEps"))
    result.forward_eps = _num(info.get("forwardEps"))
    result.valuation = {name: _num(info.get(key)) for name, key in _VALUATION_KEYS.items()}

    try:
        hist = stock.history(period=history_period, auto_adjust=False)
        for idx, row in hist.iterrows():
            close = _num(row.get("Close"))
            if close is None:
                continue
            volume = _num(row.get("Volume"))
            result.price_history.append(
                PricePoint(
                    date=idx.strftime("%Y-%m-%d"),
                    close=round(close, 4),
                    volume=int(volume) if volume is not None else None,
                )
            )
    except Exception as exc:
        result.warnings.append(f"Could not fetch price history: {exc}")

    # Fall back to the latest close if no live price was reported.
    if result.current_price is None and result.price_history:
        result.current_price = result.price_history[-1].close
        result.warnings.append("current_price taken from latest historical close.")

    if not result.price_history:
        result.warnings.append("No price history returned (invalid ticker?).")
    missing = [
        n
        for n in ("company_name", "market_cap", "revenue", "net_income", "eps")
        if getattr(result, n) is None
    ]
    if missing:
        result.warnings.append(f"Missing fields: {', '.join(missing)}")

    return result
