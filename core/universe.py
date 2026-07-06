"""Automatic US large-cap universe construction.

The live universe is discovered with Yahoo Finance's equity screener.  A
versioned fallback keeps the strategy usable when the upstream screener is
rate-limited.  Holdings and the strategy universe are deliberately separate.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import re

import yfinance as yf


UNIVERSE_SIZE = 100
UNIVERSE_BUFFER_SIZE = 120
_CACHE_TTL = timedelta(hours=12)

# Last-known-good snapshot.  It is only a network fallback, not historical
# constituent data.  ADRs are intentionally included.
FALLBACK_TOP100 = (
    "NVDA", "AAPL", "GOOGL", "MSFT", "AMZN", "TSM", "SPCX", "AVGO", "META", "TSLA",
    "MU", "BRK-B", "LLY", "JPM", "WMT", "AMD", "V", "ASML", "JNJ", "INTC",
    "XOM", "AMAT", "MA", "ABBV", "CSCO", "CAT", "LRCX", "COST", "BAC", "ORCL",
    "GE", "UNH", "KO", "HD", "PG", "MS", "CVX", "ARM", "HSBC", "NFLX",
    "MRK", "PLTR", "KLAC", "NVS", "AZN", "GS", "GEV", "RY", "PM", "PANW",
    "IBM", "RTX", "TXN", "WFC", "SNDK", "DELL", "LIN", "AXP", "C", "MUFG",
    "BABA", "NVO", "SHEL", "MRVL", "BHP", "TM", "APH", "AMGN", "ANET", "SAN",
    "MCD", "CRWD", "PEP", "TD", "TMO", "TMUS", "SAP", "WDC", "QCOM", "NEE",
    "STX", "ADI", "BA", "VZ", "APP", "DIS", "TTE", "TJX", "GLW", "SCHW",
    "DE", "UNP", "UBS", "WELL", "ABT", "GILD", "BUD", "SMFG", "SHOP", "ETN",
)


@dataclass(frozen=True)
class UniverseSnapshot:
    tickers: tuple[str, ...]
    as_of: str
    source: str
    stale: bool = False


_snapshot: UniverseSnapshot | None = None
_snapshot_at: datetime | None = None


def _issuer_key(name: str, ticker: str) -> str:
    value = name.lower()
    value = re.sub(r"\b(class|cl)\s+[abc]\b", "", value)
    value = re.sub(r"\b(new|ordinary shares?|common stock)\b", "", value)
    value = re.sub(r"[^a-z0-9]+", " ", value).strip()
    return value or ticker.lower()


def _valid_quote(item: dict) -> bool:
    ticker = str(item.get("symbol") or "").upper()
    if not ticker or "-P" in ticker or ticker == "BRK-A":
        return False
    quote_type = str(item.get("quoteType") or "EQUITY").upper()
    return quote_type in {"EQUITY", ""}


def _fetch_live() -> UniverseSnapshot:
    from yfinance import EquityQuery

    query = EquityQuery("and", [
        EquityQuery("eq", ["region", "us"]),
        EquityQuery("is-in", ["exchange", "NMS", "NYQ"]),
        EquityQuery("gte", ["intradaymarketcap", 1_000_000_000]),
    ])
    response = yf.screen(
        query,
        size=180,
        sortField="intradaymarketcap",
        sortAsc=False,
    )

    selected: list[str] = []
    issuers: set[str] = set()
    for item in response.get("quotes", []):
        if not _valid_quote(item):
            continue
        ticker = str(item["symbol"]).upper()
        issuer = _issuer_key(
            str(item.get("shortName") or item.get("longName") or ticker),
            ticker,
        )
        if issuer in issuers:
            continue
        issuers.add(issuer)
        selected.append(ticker)
        if len(selected) == UNIVERSE_SIZE:
            break

    if len(selected) < UNIVERSE_SIZE:
        raise ValueError(f"유니버스 종목 부족: {len(selected)}/{UNIVERSE_SIZE}")

    return UniverseSnapshot(
        tickers=tuple(selected),
        as_of=datetime.now(timezone.utc).date().isoformat(),
        source="Yahoo Finance US market-cap screener",
        stale=False,
    )


def get_universe(force_refresh: bool = False) -> UniverseSnapshot:
    """Return a cached top-100 NYSE/Nasdaq common-stock/ADR universe."""
    global _snapshot, _snapshot_at
    now = datetime.now(timezone.utc)
    if (
        not force_refresh
        and _snapshot is not None
        and _snapshot_at is not None
        and now - _snapshot_at < _CACHE_TTL
    ):
        return _snapshot

    try:
        _snapshot = _fetch_live()
    except Exception:
        _snapshot = UniverseSnapshot(
            tickers=FALLBACK_TOP100,
            as_of=now.date().isoformat(),
            source="bundled last-known-good snapshot",
            stale=True,
        )
    _snapshot_at = now
    return _snapshot


def clear_universe_cache() -> None:
    global _snapshot, _snapshot_at
    _snapshot = None
    _snapshot_at = None

