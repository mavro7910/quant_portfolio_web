"""
utils/ai_client.py

개선 사항:
1. Marketaux 뉴스 수집 추가 (snippet + 감성점수)
2. Finnhub + Marketaux 병렬 동시 수집
3. 퀀트 컨텍스트 주입 (모멘텀 랭킹, 변동성, 52주, Bull/Bear)
4. 스마트 캐시: ±0.5% 미만 종목은 당일 캐시 재사용 → 부분 재분석
5. Gemini 배치 프롬프트 품질 개선
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import streamlit as st


# ─────────────────────────────────────────────
# API 키 관리
# ─────────────────────────────────────────────

def get_api_key() -> str | None:
    return st.session_state.get("gemini_api_key") or None

def set_api_key(key: str):
    st.session_state["gemini_api_key"] = key.strip()

def clear_api_key():
    st.session_state.pop("gemini_api_key", None)

def has_api_key() -> bool:
    k = get_api_key()
    return bool(k and len(k) > 10)

def get_finnhub_key() -> str | None:
    return st.session_state.get("finnhub_api_key") or None

def set_finnhub_key(key: str):
    st.session_state["finnhub_api_key"] = key.strip()

def clear_finnhub_key():
    st.session_state.pop("finnhub_api_key", None)

def has_finnhub_key() -> bool:
    k = get_finnhub_key()
    return bool(k and len(k) > 5)

def get_marketaux_key() -> str | None:
    return st.session_state.get("marketaux_api_key") or None

def set_marketaux_key(key: str):
    st.session_state["marketaux_api_key"] = key.strip()

def clear_marketaux_key():
    st.session_state.pop("marketaux_api_key", None)

def has_marketaux_key() -> bool:
    k = get_marketaux_key()
    return bool(k and len(k) > 5)


# ─────────────────────────────────────────────
# 키 검증
# ─────────────────────────────────────────────

def validate_api_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if not key.startswith("AIza"):
        return False, "Gemini 키는 'AIza'로 시작해야 합니다."
    if len(key) < 35:
        return False, "키가 너무 짧습니다."
    return True, None

def validate_finnhub_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if len(key) < 10:
        return False, "키가 너무 짧습니다."
    return True, None

def validate_marketaux_key(api_key: str) -> tuple[bool, str | None]:
    key = api_key.strip()
    if len(key) < 10:
        return False, "키가 너무 짧습니다."
    return True, None


# ─────────────────────────────────────────────
# 퀀트 컨텍스트 계산
# ─────────────────────────────────────────────

def fetch_quant_context(tickers: list[str]) -> dict[str, dict]:
    """
    종목별 퀀트 데이터 계산.
    반환: {ticker: {mom_rank, vol_rank, n_tickers, is_bull, weight_pct,
                    week52_high_pct, week52_low_pct}}
    """
    try:
        import numpy as np
        import pandas as pd
        from core.strategy import (
            fetch_prices, momentum_score, vol_inv_rank,
            target_weights, MA_WINDOW,
        )

        data      = fetch_prices(tickers, extra=["QQQ"], period="14mo")
        prices_df = data["prices"].reindex(columns=tickers).ffill()
        qqq       = data.get("QQQ", pd.Series(dtype=float))

        if prices_df.empty or len(prices_df) < 60:
            return {}

        curr_prices = prices_df.iloc[-1]

        # 시장 국면
        is_bull = False
        if len(qqq) >= MA_WINDOW:
            is_bull = float(qqq.iloc[-1]) > float(qqq.rolling(MA_WINDOW).mean().iloc[-1])

        # 모멘텀 순위
        mom      = momentum_score(prices_df)
        mom_rank = mom.rank(ascending=False, method="min").astype(int)

        # 변동성 순위 (낮을수록 안정 = 낮은 숫자)
        vol_raw      = prices_df.pct_change().rolling(60).std().iloc[-1]
        vol_rank_raw = vol_raw.rank(ascending=True, method="min").astype(int)

        # 전략 비중
        try:
            w_target, _ = target_weights(prices_df, qqq)
        except Exception:
            w_target = pd.Series(1.0 / len(tickers), index=tickers)

        # 52주 고저
        period_252 = prices_df.tail(252)
        week52_high = period_252.max()
        week52_low  = period_252.min()

        result = {}
        n = len(tickers)
        for t in tickers:
            try:
                curr = float(curr_prices.get(t, 0) or 0)
                high = float(week52_high.get(t, curr) or curr)
                low  = float(week52_low.get(t, curr) or curr)
                pct_from_high = round(curr / high * 100, 1) if high > 0 else None
                pct_from_low  = round(curr / low * 100 - 100, 1) if low > 0 else None

                result[t] = {
                    "mom_rank":        int(mom_rank.get(t, 0)),
                    "vol_rank":        int(vol_rank_raw.get(t, 0)),
                    "n_tickers":       n,
                    "is_bull":         is_bull,
                    "weight_pct":      round(float(w_target.get(t, 0)) * 100, 1),
                    "week52_high_pct": pct_from_high,
                    "week52_low_pct":  pct_from_low,
                }
            except Exception:
                result[t] = {}

        return result

    except Exception:
        return {}


# ─────────────────────────────────────────────
# 뉴스 수집
# ─────────────────────────────────────────────

def _fetch_finnhub(ticker: str, finnhub_key: str) -> tuple[list[dict], float | None]:
    """Finnhub 시세 + 뉴스. 뉴스는 dict 리스트 반환."""
    import requests
    headers  = {"X-Finnhub-Token": finnhub_key}
    articles = []
    change_pct = None

    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker}, headers=headers, timeout=5,
        )
        d    = r.json()
        curr = d.get("c", 0)
        prev = d.get("pc", 0)
        if prev and prev > 0:
            change_pct = round((curr - prev) / prev * 100, 2)
    except Exception:
        pass

    try:
        today     = date.today()
        from_date = (today - timedelta(days=3)).isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": from_date, "to": today.isoformat()},
            headers=headers, timeout=5,
        )
        for item in r.json()[:3]:
            headline = item.get("headline", "")
            summary  = item.get("summary", "")
            source   = item.get("source", "")
            if headline:
                articles.append({
                    "title":      headline,
                    "snippet":    summary[:200] if summary else "",
                    "highlights": [],
                    "source":     source,
                    "sentiment":  None,
                })
    except Exception:
        pass

    return articles, change_pct


def _fetch_marketaux(ticker: str, marketaux_key: str) -> list[dict]:
    """Marketaux 뉴스 + snippet + 감성점수."""
    import requests
    articles = []

    try:
        r = requests.get(
            "https://api.marketaux.com/v1/news/all",
            params={
                "symbols":         ticker,
                "filter_entities": "true",
                "language":        "en",
                "limit":           3,
                "published_after": (date.today() - timedelta(days=3)).isoformat(),
                "api_token":       marketaux_key,
            },
            timeout=8,
        )
        if r.status_code != 200:
            return []

        for art in r.json().get("data", [])[:3]:
            title   = art.get("title", "")
            desc    = art.get("description", "")
            snippet = art.get("snippet", "")
            source  = art.get("source", "")

            sentiment       = None
            highlight_texts = []
            for ent in art.get("entities", []):
                if ent.get("symbol", "").upper() == ticker.upper():
                    sentiment = ent.get("sentiment_score")
                    for h in ent.get("highlights", [])[:2]:
                        txt = h.get("highlight", "").strip()
                        if txt:
                            highlight_texts.append(txt)
                    break

            body = snippet[:300] if snippet else (desc[:200] if desc else "")

            if title:
                articles.append({
                    "title":      title,
                    "snippet":    body,
                    "highlights": highlight_texts,
                    "source":     source,
                    "sentiment":  round(sentiment, 2) if sentiment is not None else None,
                })
    except Exception:
        pass

    return articles


def _fetch_yfinance_fallback(ticker: str) -> tuple[list[dict], float | None]:
    """Finnhub/Marketaux 모두 실패 시 yfinance fallback."""
    try:
        import yfinance as yf
        tk       = yf.Ticker(ticker)
        articles = []
        for item in (tk.news or [])[:3]:
            title = (
                item.get("title")
                or item.get("content", {}).get("title")
                or item.get("content", {}).get("summary", "")
            )
            title = str(title).strip()
            if title and len(title) > 5:
                articles.append({
                    "title": title, "snippet": "",
                    "highlights": [], "source": "", "sentiment": None,
                })

        change_pct = None
        hist = tk.history(period="5d")
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            curr = float(hist["Close"].iloc[-1])
            if prev > 0:
                change_pct = round((curr - prev) / prev * 100, 2)

        return articles, change_pct
    except Exception:
        return [], None


def fetch_ticker_data(
    ticker: str,
    finnhub_key: str | None,
    marketaux_key: str | None,
) -> tuple[list[dict], float | None]:
    """Finnhub + Marketaux 병렬 수집 후 통합."""
    finnhub_articles: list[dict] = []
    marketaux_articles: list[dict] = []
    change_pct: float | None = None

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {}
        if finnhub_key:
            futures["finnhub"]    = ex.submit(_fetch_finnhub, ticker, finnhub_key)
        if marketaux_key:
            futures["marketaux"]  = ex.submit(_fetch_marketaux, ticker, marketaux_key)

        for name, fut in futures.items():
            try:
                if name == "finnhub":
                    finnhub_articles, change_pct = fut.result()
                else:
                    marketaux_articles = fut.result()
            except Exception:
                pass

    # 둘 다 없으면 yfinance fallback
    if not finnhub_articles and not marketaux_articles:
        return _fetch_yfinance_fallback(ticker)

    # 통합: Marketaux 우선, Finnhub 보완 (제목 기준 중복 제거)
    seen: set[str] = set()
    merged: list[dict] = []

    for art in marketaux_articles + finnhub_articles:
        key = art["title"][:40].lower()
        if key not in seen:
            seen.add(key)
            merged.append(art)

    return merged[:4], change_pct


# ─────────────────────────────────────────────
# 프롬프트 빌더
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = (
    "당신은 퀀트 포트폴리오 분석 AI입니다. "
    "퀀트 지표와 뉴스를 종합하여 각 종목의 전략적 상태를 분석합니다. "
    "JSON 배열만 응답하세요. 코드블록, 설명 텍스트 절대 없이."
)


def _format_news_block(articles: list[dict]) -> str:
    if not articles:
        return "없음"
    lines = []
    for art in articles[:3]:
        title      = art.get("title", "")
        snippet    = art.get("snippet", "")
        source     = art.get("source", "")
        senti      = art.get("sentiment")
        highlights = art.get("highlights", [])

        line = f"[{source}] {title}" if source else title
        if snippet:
            line += f"\n    내용: {snippet[:250]}"
        if highlights:
            line += f"\n    핵심: {' / '.join(highlights[:2])}"
        if senti is not None:
            label = "긍정" if senti > 0.2 else "부정" if senti < -0.2 else "중립"
            line += f"\n    감성: {label}({senti:+.2f})"
        lines.append(line)
    return "\n".join(lines)


def _build_batch_prompt(holdings: dict, data_map: dict, quant_ctx: dict) -> str:
    # 시장 국면 (첫 번째 종목에서 추출)
    is_bull = None
    for t in holdings:
        ctx = quant_ctx.get(t, {})
        if "is_bull" in ctx:
            is_bull = ctx["is_bull"]
            break

    market_line = ""
    if is_bull is not None:
        market_line = (
            f"시장 국면: {'🐂 강세장 (QQQ > 200MA)' if is_bull else '🐻 약세장 (QQQ < 200MA)'}\n\n"
        )

    items = []
    for ticker, shares in holdings.items():
        articles, change_pct = data_map.get(ticker, ([], None))
        ctx = quant_ctx.get(ticker, {})
        n   = ctx.get("n_tickers", len(holdings))

        change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"

        quant_parts = []
        if ctx.get("mom_rank"):
            quant_parts.append(f"모멘텀 {ctx['mom_rank']}위/{n}종목")
        if ctx.get("vol_rank"):
            quant_parts.append(f"변동성 {ctx['vol_rank']}위/{n}종목(낮을수록안정)")
        if ctx.get("weight_pct") is not None:
            quant_parts.append(f"전략비중 {ctx['weight_pct']}%")
        if ctx.get("week52_high_pct") is not None:
            quant_parts.append(f"52주고점대비 {ctx['week52_high_pct']}%")
        if ctx.get("week52_low_pct") is not None:
            quant_parts.append(f"52주저점대비 +{ctx['week52_low_pct']}%")

        quant_str = " | ".join(quant_parts) if quant_parts else "N/A"
        news_str  = _format_news_block(articles)

        items.append(
            f"[{ticker}] {shares:.1f}주 | 전일대비: {change_str}\n"
            f"  퀀트: {quant_str}\n"
            f"  뉴스:\n{news_str}"
        )

    tickers_list = list(holdings.keys())
    return (
        f"{market_line}"
        f"다음 {len(holdings)}개 종목을 분석하세요:\n\n"
        + "\n\n".join(items)
        + f"""

JSON 배열로만 응답 (코드블록 없이):
[{{"ticker":"종목","signal":"up/down/neutral","reason":"전략적핵심이유25자이내","bullets":["퀀트근거","뉴스근거","투자시사점"],"tags":["태그1","태그2"],"related":[{{"ticker":"관련종목","reason":"연관이유"}}]}}]

rules:
- 한국어
- signal은 퀀트+뉴스 종합 판단 (단순 등락률이 아님)
- bullets 정확히 3개: ①퀀트근거 ②뉴스근거 ③투자시사점
- related: 포트폴리오 내 연관 종목 1~2개(없으면[])
- 반드시 {len(holdings)}개 전부 포함: {', '.join(tickers_list)}"""
    )


# ─────────────────────────────────────────────
# Gemini 호출
# ─────────────────────────────────────────────

def _gemini_batch(
    holdings: dict,
    data_map: dict,
    quant_ctx: dict,
    api_key: str,
) -> dict[str, dict]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_SYSTEM_PROMPT,
    )
    response = model.generate_content(_build_batch_prompt(holdings, data_map, quant_ctx))
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    results_list = json.loads(raw)
    result_map   = {}
    for item in results_list:
        ticker = item.get("ticker", "")
        if not ticker:
            continue

        # ±2% 이상 극단 변동은 signal 보정
        _, change_pct = data_map.get(ticker, ([], None))
        if change_pct is not None and abs(change_pct) >= 2.0:
            item["signal"] = "up" if change_pct > 0 else "down"

        item.setdefault("signal", "neutral")
        item.setdefault("reason", "분석 정보 없음")
        item.setdefault("bullets", ["정보 없음"] * 3)
        item.setdefault("tags", [])
        item.setdefault("related", [])
        while len(item["bullets"]) < 3:
            item["bullets"].append("추가 정보 없음")
        item["bullets"] = item["bullets"][:3]
        result_map[ticker] = item

    return result_map


def _gemini_single(
    ticker: str,
    shares: float,
    articles: list[dict],
    change_pct: float | None,
    quant_ctx: dict,
    api_key: str,
) -> dict:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction="퀀트 포트폴리오 분석 AI. JSON만 응답. 코드블록 없이.",
    )
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
    news_str   = _format_news_block(articles)
    ctx        = quant_ctx.get(ticker, {})
    n          = ctx.get("n_tickers", 1)

    quant_parts = []
    if ctx.get("mom_rank"):
        quant_parts.append(f"모멘텀 {ctx['mom_rank']}위/{n}종목")
    if ctx.get("vol_rank"):
        quant_parts.append(f"변동성 {ctx['vol_rank']}위/{n}종목")
    if ctx.get("weight_pct") is not None:
        quant_parts.append(f"전략비중 {ctx['weight_pct']}%")
    if ctx.get("week52_high_pct") is not None:
        quant_parts.append(f"52주고점대비 {ctx['week52_high_pct']}%")
    quant_str  = " | ".join(quant_parts) if quant_parts else "N/A"
    market_str = "강세장" if ctx.get("is_bull") else "약세장"

    prompt = (
        f"종목:{ticker} ({shares:.1f}주) | 시장:{market_str} | 전일대비:{change_str}\n"
        f"퀀트: {quant_str}\n"
        f"뉴스:\n{news_str}\n\n"
        f'JSON:{{"signal":"up/down/neutral","reason":"25자이내","bullets":["퀀트근거","뉴스근거","투자시사점"],"tags":["태그1"],"related":[]}}'
    )

    response = model.generate_content(prompt)
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    result = json.loads(raw)

    if change_pct is not None and abs(change_pct) >= 2.0:
        result["signal"] = "up" if change_pct > 0 else "down"

    result.setdefault("signal", "neutral")
    result.setdefault("reason", "분석 정보 없음")
    result.setdefault("bullets", ["정보 없음"] * 3)
    result.setdefault("tags", [])
    result.setdefault("related", [])
    while len(result["bullets"]) < 3:
        result["bullets"].append("추가 정보 없음")
    result["bullets"] = result["bullets"][:3]
    return result


# ─────────────────────────────────────────────
# 스마트 캐시
# ─────────────────────────────────────────────

REANALYZE_THRESHOLD = 0.5  # ±0.5% 이상이면 재분석


def _needs_reanalysis(
    ticker: str,
    change_pct: float | None,
    cached_results: list[dict],
) -> bool:
    if change_pct is None:
        return True
    if abs(change_pct) >= REANALYZE_THRESHOLD:
        return True
    cached_tickers = {r["ticker"] for r in cached_results}
    return ticker not in cached_tickers


# ─────────────────────────────────────────────
# 메인 분석
# ─────────────────────────────────────────────

def analyze_portfolio_signals(
    holdings: dict[str, float],
    api_key: str,
    finnhub_key: str | None = None,
    marketaux_key: str | None = None,
    progress_callback=None,
    portfolio=None,
    cached_results: list[dict] | None = None,
) -> list[dict]:
    """
    포트폴리오 AI 시그널 분석.
    cached_results: 당일 기존 분석 결과 (스마트 캐시용)
    """
    holdings = {t: s for t, s in holdings.items() if s > 0}
    tickers  = list(holdings.keys())
    total    = len(tickers)

    from datetime import datetime
    today    = date.today().isoformat()
    now_time = datetime.now().strftime("%H:%M")

    # ── 1단계: 전체 종목 시세+뉴스 병렬 수집 ───────────────────
    if progress_callback:
        progress_callback(0, total, "데이터 수집 중", None)

    data_map: dict[str, tuple[list[dict], float | None]] = {}
    with ThreadPoolExecutor(max_workers=min(10, total)) as executor:
        futures = {
            executor.submit(fetch_ticker_data, t, finnhub_key, marketaux_key): t
            for t in tickers
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                data_map[t] = future.result()
            except Exception:
                data_map[t] = ([], None)

    # ── 2단계: 퀀트 컨텍스트 계산 ──────────────────────────────
    if progress_callback:
        progress_callback(0, total, "퀀트 지표 계산 중", None)

    quant_ctx = fetch_quant_context(tickers)

    # ── 3단계: 스마트 캐시 분리 ────────────────────────────────
    cached_map: dict[str, dict] = {}
    if cached_results:
        for r in cached_results:
            cached_map[r["ticker"]] = r

    reanalyze_tickers: list[str] = []
    keep_tickers: list[str]      = []

    for t in tickers:
        _, change_pct = data_map.get(t, ([], None))
        if _needs_reanalysis(t, change_pct, cached_results or []):
            reanalyze_tickers.append(t)
        else:
            keep_tickers.append(t)

    # ── 4단계: Gemini 배치 분석 (재분석 필요 종목만) ───────────
    signal_map: dict[str, dict] = {}

    for t in keep_tickers:
        if t in cached_map:
            signal_map[t] = cached_map[t].get("signal", {})

    if reanalyze_tickers:
        if progress_callback:
            progress_callback(1, total, "AI 분석 중", None)

        re_holdings = {t: holdings[t] for t in reanalyze_tickers}
        re_data     = {t: data_map[t]  for t in reanalyze_tickers}
        re_quant    = {t: quant_ctx.get(t, {}) for t in reanalyze_tickers}

        try:
            batch_result = _gemini_batch(re_holdings, re_data, re_quant, api_key)
            signal_map.update(batch_result)
        except Exception:
            if progress_callback:
                progress_callback(1, total, "배치 실패, 순차 분석 중...", None)
            for i, t in enumerate(reanalyze_tickers):
                articles, change_pct = re_data.get(t, ([], None))
                try:
                    signal_map[t] = _gemini_single(
                        t, holdings[t], articles, change_pct, re_quant, api_key
                    )
                except Exception as e2:
                    signal_map[t] = {"_error": str(e2)}
                if progress_callback:
                    progress_callback(i + 1, len(reanalyze_tickers), t, None)

    # ── 5단계: 결과 조합 ────────────────────────────────────────
    results = []
    for ticker in tickers:
        articles, change_pct = data_map.get(ticker, ([], None))
        headlines = [a["title"] for a in articles if a.get("title")]

        if ticker in keep_tickers and ticker in cached_map:
            old = cached_map[ticker].copy()
            old["change_pct"]   = change_pct
            old["reused_cache"] = True
            results.append(old)
        else:
            ctx  = quant_ctx.get(ticker, {})
            item = {
                "ticker":        ticker,
                "shares":        holdings[ticker],
                "change_pct":    change_pct,
                "headlines":     headlines,
                "articles":      articles,
                "signal":        signal_map.get(ticker, {"_error": "분석 결과 없음"}),
                "logo_url":      portfolio.get_logo(ticker) if portfolio else None,
                "analyzed_date": today,
                "analyzed_time": now_time,
                "reused_cache":  False,
                "quant": {
                    "mom_rank":        ctx.get("mom_rank"),
                    "vol_rank":        ctx.get("vol_rank"),
                    "n_tickers":       ctx.get("n_tickers"),
                    "weight_pct":      ctx.get("weight_pct"),
                    "week52_high_pct": ctx.get("week52_high_pct"),
                    "is_bull":         ctx.get("is_bull"),
                },
            }
            results.append(item)

        if progress_callback:
            progress_callback(tickers.index(ticker) + 1, total, ticker, results[-1])

    return results
