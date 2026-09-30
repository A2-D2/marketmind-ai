"""CLI smoke test: python scripts/test_financials.py [TICKER] [--json]"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from marketmind.data.financials import get_company_financials  # noqa: E402


def fmt(value, money=False):
    if value is None:
        return "n/a"
    if money and abs(value) >= 1e6:
        for unit, div in (("T", 1e12), ("B", 1e9), ("M", 1e6)):
            if abs(value) >= div:
                return f"${value / div:,.2f}{unit}"
    return f"{value:,.2f}"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("ticker", nargs="?", default="MU")
    parser.add_argument("--json", action="store_true", help="print full JSON")
    args = parser.parse_args()

    data = get_company_financials(args.ticker)

    if args.json:
        print(json.dumps(data.to_dict(), indent=2))
        return

    print(f"{data.company_name or 'n/a'} ({data.ticker})")
    print(f"Sector / Industry: {data.sector or 'n/a'} / {data.industry or 'n/a'}")
    print(f"Price:      {fmt(data.current_price)} {data.currency or ''}")
    print(f"Market cap: {fmt(data.market_cap, money=True)}")
    print(f"Revenue:    {fmt(data.revenue, money=True)} (TTM)")
    print(f"Net income: {fmt(data.net_income, money=True)} (TTM)")
    print(f"EPS:        {fmt(data.eps)} (trailing), {fmt(data.forward_eps)} (forward)")
    print("Valuation:  " + ", ".join(f"{k}={fmt(v)}" for k, v in data.valuation.items()))
    if data.price_history:
        first, last = data.price_history[0], data.price_history[-1]
        print(f"History:    {len(data.price_history)} days, {first.date} -> {last.date}")
        print(f"            first close {first.close}, last close {last.close}")
    for w in data.warnings:
        print(f"WARNING: {w}")


if __name__ == "__main__":
    main()
