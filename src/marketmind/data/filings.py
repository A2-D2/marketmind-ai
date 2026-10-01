"""SEC filings retrieval via edgartools (SEC EDGAR). No LLM logic lives here.

Retrieves the latest 10-K for any ticker and extracts a bounded evidence bundle
from Item 1A (Risk Factors): the company's own risk factor summary plus each
risk heading with the start of its supporting text. The full filing is never
returned, so downstream LLM context stays small.
"""

from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

from edgar import Company, set_identity

EDGAR_SETUP_MESSAGE = (
    "EDGAR_IDENTITY not set. SEC EDGAR requires a declared User-Agent: add "
    'EDGAR_IDENTITY="Your Name your.email@example.com" to .env (see .env.example).'
)


class EdgarIdentityError(RuntimeError):
    """Raised before any SEC request when EDGAR_IDENTITY is missing."""


def require_edgar_identity() -> str:
    """Return the SEC identity from the environment (.env), or raise with setup help."""
    identity = (os.getenv("EDGAR_IDENTITY") or "").strip().strip('"').strip("'")
    if not identity:
        raise EdgarIdentityError(EDGAR_SETUP_MESSAGE)
    return identity

DEFAULT_MAX_CHARS = 24_000  # ~6k tokens of filing evidence for the LLM
_SUMMARY_MAX_CHARS = 6_000
_SNIPPET_MAX_CHARS = 400
_SNIPPET_MIN_CHARS = 120

_NOISE_RE = re.compile(r"^(table of contents|\d+(\s*\|.*)?|page \d+)$", re.IGNORECASE)
_CATEGORY_RE = re.compile(r"^(risks? (related|relating) to|general risk|other risk)", re.IGNORECASE)
_BULLET_CHARS = ("•", "·", "-", "–")
_BOLD_RE = re.compile(r"^\*\*(.+?)\*\*$")
_SUMMARY_TITLES = {"risk factor summary", "risk factors summary", "summary of risk factors"}


@dataclass
class RiskExcerpt:
    evidence_id: str  # stable id the agent must cite, e.g. "RF-07"
    section: str  # e.g. "Item 1A. Risk Factors"
    category: str | None  # filing's own sub-heading, if any
    heading: str | None  # risk factor heading (verbatim)
    text: str  # verbatim excerpt (may be truncated, marked with "...")
    truncated: bool = False


@dataclass
class FilingEvidence:
    ticker: str
    data_provider: str = "SEC EDGAR via edgartools"
    retrieved_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(timespec="seconds")
    )
    company_name: str | None = None
    cik: str | None = None
    form_type: str | None = None
    filing_date: str | None = None
    period_of_report: str | None = None
    accession_number: str | None = None
    filing_index_url: str | None = None
    primary_document_url: str | None = None
    sections_extracted: list[str] = field(default_factory=list)
    section_total_chars: int = 0  # size of the full section before limiting
    risk_factor_count: int = 0  # headings found in the section
    excerpts: list[RiskExcerpt] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def extracted_chars(self) -> int:
        return sum(len(e.text) + len(e.heading or "") for e in self.excerpts)

    @property
    def approx_tokens(self) -> int:
        return round(self.extracted_chars / 4)  # rough English-text heuristic

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["extracted_chars"] = self.extracted_chars
        data["approx_tokens"] = self.approx_tokens
        return data


def _clean_paragraphs(text: str) -> list[str]:
    paras = (p.strip() for p in text.split("\n\n"))
    return [p for p in paras if p and not _NOISE_RE.match(p)]


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\\", "")).strip()


def _bold_paragraphs(filing) -> set[str]:
    """Bold paragraphs in the filing markdown; 10-K risk headings are bold."""
    try:
        md = filing.markdown() or ""
    except Exception:
        return set()
    bold = set()
    for p in md.split("\n\n"):
        m = _BOLD_RE.match(p.strip())
        if m:
            bold.add(_normalize(m.group(1)))
    return bold


def _looks_like_heading(paras: list[str], i: int) -> bool:
    p = paras[i]
    if p.startswith(_BULLET_CHARS) or not (40 <= len(p) <= 400) or not p.endswith("."):
        return False
    nxt = paras[i + 1] if i + 1 < len(paras) else ""
    return len(nxt) > len(p) and not nxt.startswith(_BULLET_CHARS)


def _truncate(text: str, limit: int) -> tuple[str, bool]:
    if len(text) <= limit:
        return text, False
    cut = text[:limit]
    end = cut.rfind(". ")  # prefer a sentence boundary
    if end > limit // 2:
        cut = cut[: end + 1]
    return cut.rstrip() + " ...", True


def _extract_risk_excerpts(
    section_text: str, bold: set[str], max_chars: int, result: FilingEvidence
) -> list[RiskExcerpt]:
    paras = _clean_paragraphs(section_text)
    section = "Item 1A. Risk Factors"
    excerpts: list[RiskExcerpt] = []

    # 1) The filing's own "Risk Factor Summary", if present (verbatim, capped).
    summary_end = 0
    try:
        start = next(i for i, p in enumerate(paras) if p.lower().rstrip(":") in _SUMMARY_TITLES)
    except StopIteration:
        start = None
    if start is not None:
        # Summary = bullets grouped under category lines; it ends at the first
        # other paragraph or when a category repeats (start of the detailed text).
        lines, end = [], start + 1
        while end < len(paras):
            p = paras[end]
            if not (p.startswith(_BULLET_CHARS) or (_CATEGORY_RE.match(p) and p not in lines)):
                break
            lines.append(p)
            end += 1
        summary_end = end
        if lines:
            text, cut = _truncate("\n".join(lines), _SUMMARY_MAX_CHARS)
            excerpts.append(RiskExcerpt("RF-00", section, None, "Risk Factor Summary", text, cut))
    else:
        result.warnings.append("No 'Risk Factor Summary' found; using risk headings only.")

    # 2) Risk headings: bold in the filing (preferred) or heuristic fallback.
    body = paras[summary_end:]
    use_bold = sum(1 for p in body if _normalize(p) in bold) >= 3
    if not use_bold:
        result.warnings.append(
            "Heading formatting unavailable; risk headings detected heuristically (may be imperfect)."
        )

    found: list[tuple[str | None, str, str]] = []  # (category, heading, following text)
    category = None
    for i, p in enumerate(body):
        if _CATEGORY_RE.match(p) and len(p) < 150:
            category = p
            continue
        is_heading = (
            _normalize(p) in bold and not p.startswith(_BULLET_CHARS) and len(p) > 25
            if use_bold
            else _looks_like_heading(body, i)
        )
        if is_heading:
            nxt = body[i + 1] if i + 1 < len(body) else ""
            found.append((category, p, nxt))
    result.risk_factor_count = len(found)

    # 3) Share the remaining budget evenly so every risk gets some supporting text.
    used = sum(len(e.text) for e in excerpts)
    heading_chars = sum(len(h) for _, h, _ in found)
    remaining = max_chars - used - heading_chars
    snippet = min(_SNIPPET_MAX_CHARS, remaining // max(len(found), 1))
    if snippet < _SNIPPET_MIN_CHARS:
        snippet = _SNIPPET_MIN_CHARS
        keep = max(0, (max_chars - used) // (snippet + 150))
        if keep < len(found):
            result.warnings.append(
                f"Evidence budget reached: included {keep} of {len(found)} risk factors."
            )
            found = found[:keep]

    for n, (cat, heading, nxt) in enumerate(found, start=1):
        text, cut = _truncate(nxt, snippet)
        excerpts.append(RiskExcerpt(f"RF-{n:02d}", section, cat, heading, text, cut))

    if not found and not excerpts:
        # Last resort: the opening of the section, so the agent still has evidence.
        text, cut = _truncate("\n\n".join(paras), max_chars)
        excerpts.append(RiskExcerpt("RF-01", section, None, None, text, cut))
        result.warnings.append("No risk headings detected; supplied the opening of Item 1A only.")
    elif any(e.truncated for e in excerpts):
        result.warnings.append(
            f"Excerpts are truncated to stay within ~{max_chars:,} characters; "
            "full text is available at the SEC source URL."
        )
    return excerpts


def get_latest_10k_evidence(ticker: str, max_chars: int = DEFAULT_MAX_CHARS) -> FilingEvidence:
    """Fetch the latest 10-K for any ticker and extract bounded Risk Factors evidence.

    Raises EdgarIdentityError if EDGAR_IDENTITY is missing (setup error, checked
    before contacting SEC). Data failures never raise; they are reported in
    `warnings` and leave `excerpts` empty.
    """
    symbol = ticker.strip().upper()
    result = FilingEvidence(ticker=symbol)
    if not symbol:
        result.warnings.append("Empty ticker.")
        return result

    set_identity(require_edgar_identity())  # raises before any SEC request

    try:
        company = Company(symbol)
    except Exception as exc:  # CompanyNotFoundError, network errors, rate limits
        result.warnings.append(f"Company not found on SEC EDGAR for ticker '{symbol}': {exc}")
        return result
    result.company_name = company.name
    result.cik = str(company.cik)

    try:
        filing = company.get_filings(form="10-K").latest()
    except Exception as exc:
        result.warnings.append(f"Could not list 10-K filings: {exc}")
        return result
    if filing is None:
        result.warnings.append(
            "No 10-K found (company may file 20-F/40-F as a foreign issuer, or be newly listed)."
        )
        return result

    result.form_type = filing.form
    result.filing_date = str(filing.filing_date)
    result.period_of_report = str(filing.period_of_report) if filing.period_of_report else None
    result.accession_number = filing.accession_no
    result.filing_index_url = filing.homepage_url
    result.primary_document_url = filing.filing_url

    try:
        section_text = filing.obj().risk_factors or ""
    except Exception as exc:
        result.warnings.append(f"Could not parse 10-K sections: {exc}")
        return result
    if not section_text.strip():
        result.warnings.append("Item 1A (Risk Factors) not found or empty in this filing.")
        return result

    result.sections_extracted = ["Item 1A. Risk Factors"]
    result.section_total_chars = len(section_text)
    try:
        result.excerpts = _extract_risk_excerpts(
            section_text, _bold_paragraphs(filing), max_chars, result
        )
    except Exception as exc:
        result.warnings.append(f"Risk Factors extraction failed: {exc}")
    return result
