"""Deterministic API insight layer.

External opinions and LLM output do not alter the validated factor score.
They are converted into auditable event-risk flags and stored for prospective
validation before any future promotion into the allocation model.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from utils.ai_client import fetch_analyst_data, fetch_ticker_data


def _summarize(ticker: str, analyst: dict, articles: list[dict]) -> dict:
    reasons: list[str] = []
    risk_points = 0
    positive_points = 0

    earnings_days = analyst.get("earnings_days_left")
    eps_surprise = analyst.get("eps_surprise_pct")
    upside = analyst.get("target_upside_pct")
    recommendation = str(analyst.get("rec_key") or "").upper()
    sentiments = [
        float(a["sentiment"])
        for a in articles
        if a.get("sentiment") is not None
    ]
    avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None

    if earnings_days is not None and 0 <= earnings_days <= 3:
        risk_points += 2
        reasons.append(f"실적 발표 D-{earnings_days}")
    elif earnings_days is not None and 0 <= earnings_days <= 7:
        risk_points += 1
        reasons.append(f"실적 발표 D-{earnings_days}")
    if eps_surprise is not None and eps_surprise < -10:
        risk_points += 1
        reasons.append(f"직전 EPS {eps_surprise:+.1f}%")
    if upside is not None and upside < -5:
        risk_points += 1
        reasons.append(f"컨센서스 목표가 대비 {upside:+.1f}%")
    elif upside is not None and upside > 10:
        positive_points += 1
    if "BUY" in recommendation:
        positive_points += 1
    elif "SELL" in recommendation:
        risk_points += 1
        reasons.append("애널리스트 매도 우세")
    if avg_sentiment is not None and avg_sentiment < -0.2:
        risk_points += 2 if len(sentiments) >= 2 else 1
        reasons.append(f"뉴스 감성 {avg_sentiment:+.2f}")
    elif avg_sentiment is not None and avg_sentiment > 0.2:
        positive_points += 1

    level = "높음" if risk_points >= 3 else "주의" if risk_points >= 1 else "보통"
    confirmation = "긍정 확인" if positive_points >= 2 and risk_points == 0 else "중립"
    return {
        "ticker": ticker,
        "risk_level": level,
        "confirmation": confirmation,
        "reasons": reasons,
        "analyst": analyst,
        "articles": articles[:3],
        "average_sentiment": avg_sentiment,
    }


def collect_execution_insights(
    tickers: list[str],
    finnhub_key: str | None = None,
    marketaux_key: str | None = None,
) -> dict[str, dict]:
    """Collect event risk for selected names without changing their weights."""
    def fetch_one(ticker: str) -> tuple[dict, list[dict]]:
        analyst = fetch_analyst_data(
            [ticker], finnhub_key=finnhub_key
        ).get(ticker, {})
        articles, _, _ = fetch_ticker_data(
            ticker, finnhub_key, marketaux_key
        )
        return analyst, articles

    collected: dict[str, tuple[dict, list[dict]]] = {
        ticker: ({}, []) for ticker in tickers
    }
    with ThreadPoolExecutor(max_workers=min(8, max(1, len(tickers)))) as executor:
        futures = {
            executor.submit(fetch_one, ticker): ticker
            for ticker in tickers
        }
        for future in as_completed(futures):
            ticker = futures[future]
            try:
                collected[ticker] = future.result()
            except Exception:
                collected[ticker] = ({}, [])
    return {
        ticker: _summarize(
            ticker,
            collected[ticker][0],
            collected[ticker][1],
        )
        for ticker in tickers
    }
