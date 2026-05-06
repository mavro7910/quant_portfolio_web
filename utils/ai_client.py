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
# 애널리스트 데이터 수집
# ─────────────────────────────────────────────

def fetch_analyst_data(tickers: list[str]) -> dict[str, dict]:
    """
    종목별 애널리스트 데이터 수집.
    info + analyst_price_targets + earnings_dates + calendar 다중 소스 활용.
    """
    import yfinance as yf
    import pandas as pd

    result = {}
    for t in tickers:
        try:
            tk   = yf.Ticker(t)
            data = {}

            # ── ① info (투자의견 + 목표주가) ──────────────────────
            try:
                info = tk.info or {}
                data["rec_key"]   = (info.get("recommendationKey") or "").upper() or None
                data["rec_mean"]  = info.get("recommendationMean")
                data["n_analysts"] = info.get("numberOfAnalystOpinions")
                data["current_price"] = (
                    info.get("currentPrice")
                    or info.get("regularMarketPrice")
                    or info.get("previousClose")
                )
                data["target_mean"] = info.get("targetMeanPrice")
                data["target_high"] = info.get("targetHighPrice")
                data["target_low"]  = info.get("targetLowPrice")
            except Exception:
                pass

            # ── ② analyst_price_targets (yfinance 1.0+) ──────────
            # info에 목표주가가 없으면 이쪽에서 보완
            if not data.get("target_mean"):
                try:
                    apt = tk.analyst_price_targets
                    if apt is not None and not apt.empty:
                        # DataFrame: index=날짜, columns=각 애널리스트
                        # 또는 Series 형태
                        if isinstance(apt, pd.DataFrame):
                            # 컬럼명 확인
                            cols = [c.lower() for c in apt.columns]
                            if "mean" in cols:
                                data["target_mean"] = float(apt.iloc[-1][apt.columns[cols.index("mean")]])
                            if "high" in cols:
                                data["target_high"] = float(apt.iloc[-1][apt.columns[cols.index("high")]])
                            if "low" in cols:
                                data["target_low"] = float(apt.iloc[-1][apt.columns[cols.index("low")]])
                        elif isinstance(apt, pd.Series):
                            data["target_mean"] = float(apt.get("mean", apt.get("targetMeanPrice", None)) or 0) or None
                except Exception:
                    pass

            # ── ③ 상승여력 계산 ───────────────────────────────────
            curr  = data.get("current_price")
            tmean = data.get("target_mean")
            if curr and tmean and float(curr) > 0:
                data["target_upside_pct"] = round((float(tmean) / float(curr) - 1) * 100, 1)

            # ── ④ 어닝 발표일 (calendar) ──────────────────────────
            try:
                cal = tk.calendar
                ed  = None
                if cal is not None:
                    if isinstance(cal, dict):
                        ed = cal.get("Earnings Date")
                        if isinstance(ed, list) and ed:
                            ed = ed[0]
                    elif isinstance(cal, pd.DataFrame) and not cal.empty:
                        # DataFrame: columns에 날짜, index에 항목명
                        if "Earnings Date" in cal.index:
                            ed = cal.loc["Earnings Date"].iloc[0]
                        elif "Earnings Date" in cal.columns:
                            ed = cal["Earnings Date"].iloc[0]

                if ed is not None:
                    ed_ts = pd.Timestamp(ed)
                    ed_date = ed_ts.date()
                    from datetime import date as date_cls
                    today_d = date_cls.today()
                    days_left = (ed_date - today_d).days
                    if -30 <= days_left <= 90:
                        data["earnings_date"]      = ed_date.isoformat()
                        data["earnings_days_left"] = days_left
            except Exception:
                pass

            # ── ⑤ EPS 서프라이즈 ─────────────────────────────────
            # earnings_dates → earnings_history 순서로 시도
            try:
                ed_df = tk.earnings_dates
                if ed_df is not None and not ed_df.empty:
                    now_ts = pd.Timestamp.now(tz="UTC")
                    try:
                        past = ed_df[ed_df.index < now_ts]
                    except TypeError:
                        past = ed_df[ed_df.index < pd.Timestamp.now()]

                    surp_col = None
                    for c in past.columns:
                        if "surprise" in c.lower():
                            surp_col = c
                            break

                    if surp_col:
                        past_clean = past.dropna(subset=[surp_col])
                        if not past_clean.empty:
                            data["eps_surprise_pct"] = round(float(past_clean[surp_col].iloc[0]), 1)
            except Exception:
                pass

            # earnings_history fallback (yfinance 1.0+)
            if data.get("eps_surprise_pct") is None:
                try:
                    eh = tk.earnings_history
                    if eh is not None and not eh.empty:
                        # 컬럼: epsActual, epsEstimate, epsDifference, surprisePercent
                        surp_col = None
                        for c in eh.columns:
                            if "surprise" in c.lower() or "percent" in c.lower():
                                surp_col = c
                                break
                        if surp_col is None and "epsDifference" in eh.columns and "epsEstimate" in eh.columns:
                            # 수동 계산
                            row = eh.dropna(subset=["epsDifference", "epsEstimate"]).iloc[0]
                            est = float(row["epsEstimate"])
                            if est != 0:
                                data["eps_surprise_pct"] = round(float(row["epsDifference"]) / abs(est) * 100, 1)
                        elif surp_col:
                            clean = eh.dropna(subset=[surp_col])
                            if not clean.empty:
                                val = float(clean[surp_col].iloc[0])
                                # surprisePercent가 소수(0.08)면 % 변환
                                if abs(val) < 5:
                                    val = round(val * 100, 1)
                                data["eps_surprise_pct"] = round(val, 1)
                except Exception:
                    pass

            # 정리
            result[t] = {
                "rec_key":            data.get("rec_key"),
                "rec_mean":           round(data["rec_mean"], 1) if data.get("rec_mean") else None,
                "n_analysts":         int(data["n_analysts"]) if data.get("n_analysts") else None,
                "current_price":      round(float(data["current_price"]), 2) if data.get("current_price") else None,
                "target_mean":        round(float(data["target_mean"]), 2) if data.get("target_mean") else None,
                "target_high":        round(float(data["target_high"]), 2) if data.get("target_high") else None,
                "target_low":         round(float(data["target_low"]), 2) if data.get("target_low") else None,
                "target_upside_pct":  data.get("target_upside_pct"),
                "earnings_date":      data.get("earnings_date"),
                "earnings_days_left": data.get("earnings_days_left"),
                "eps_surprise_pct":   data.get("eps_surprise_pct"),
            }

        except Exception:
            result[t] = {}

    return result


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

_SYSTEM_PROMPT = """당신은 KH 퀀트 포트폴리오의 전담 분석 AI입니다.

[KH 전략 작동 원리]
매주 아래 순서로 종목별 매수 비중을 결정합니다.

① 시장 국면 판단
   QQQ 현재가 > 200일 이동평균 → 강세장(Bull)
   QQQ 현재가 < 200일 이동평균 → 약세장(Bear)

② 모멘텀 점수 계산 (4개 기간 가중 평균)
   21일(1개월) 수익률 순위 × 10%
   63일(3개월) 수익률 순위 × 20%
   126일(6개월) 수익률 순위 × 30%
   252일(12개월) 수익률 순위 × 40%
   → 최근보다 중장기 모멘텀에 더 높은 가중치
   → 수익률 자체가 아닌 포트폴리오 내 상대 순위를 사용

③ 변동성 역수 점수
   60일 일간 수익률 표준편차의 역수를 순위화
   → 덜 출렁이는 종목이 높은 점수

④ 국면별 팩터 배합
   Bull: 모멘텀 70% + 변동성역수 30%
   Bear: 모멘텀 40% + 변동성역수 60%
   → Bear 전환 시 변동성 높은 종목은 비중이 급격히 감소

⑤ 비중 결정
   단일 종목 최대 25% 캡
   전략비중 > 현재보유비중 → 이번 주 추가 매수 대상
   전략비중 < 현재보유비중 → 자연 희석 구간 (별도 매도 없음)

[분석 규칙]
- 위 전략 맥락 안에서 판단하세요
- 수치 나열 금지. 전략 내에서 이 수치가 의미하는 바를 해석하세요
- 뉴스가 없으면 퀀트·애널리스트 데이터만으로 판단, 뉴스 내용 추측·창작 절대 금지
- 사전감지신호가 있으면 반드시 bullets에 반영하세요
- 액션은 조건부로: "~확인 시 확대 / ~시 축소", "비중 유지" 단독 사용 금지
- JSON 배열만 응답, 코드블록·설명 텍스트 절대 없이"""


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


def _build_batch_prompt(
    holdings: dict,
    data_map: dict,
    quant_ctx: dict,
    analyst_ctx: dict,
) -> str:
    # 시장 국면
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
        ana = analyst_ctx.get(ticker, {})
        n   = ctx.get("n_tickers", len(holdings))

        change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"

        # 퀀트 블록
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

        # 애널리스트 블록
        ana_parts = []
        if ana.get("rec_key"):
            n_str = f" ({ana['n_analysts']}명)" if ana.get("n_analysts") else ""
            ana_parts.append(f"투자의견:{ana['rec_key']}{n_str}")
        if ana.get("target_mean") and ana.get("current_price"):
            up = ana.get("target_upside_pct")
            up_str = f" ({up:+.1f}%)" if up is not None else ""
            ana_parts.append(f"목표주가:${ana['target_mean']}{up_str}")
        if ana.get("earnings_days_left") is not None:
            d = ana["earnings_days_left"]
            label = f"D+{abs(d)} 발표완료" if d < 0 else f"D-{d} 발표예정"
            ana_parts.append(f"어닝:{label}")
        if ana.get("eps_surprise_pct") is not None:
            ana_parts.append(f"직전EPS서프라이즈:{ana['eps_surprise_pct']:+.1f}%")
        ana_str = " | ".join(ana_parts) if ana_parts else "N/A"

        news_str = _format_news_block(articles)

        items.append(
            f"[{ticker}] {shares:.1f}주 | 전일대비: {change_str}\n"
            f"  퀀트: {quant_str}\n"
            f"  애널리스트: {ana_str}\n"
            f"  뉴스:\n{news_str}"
        )

    tickers_list = list(holdings.keys())
    return (
        f"{market_line}"
        f"다음 {len(holdings)}개 종목을 분석하세요:\n\n"
        + "\n\n".join(items)
        + f"""

JSON 배열로만 응답 (코드블록 없이):
[{{"ticker":"종목","signal":"up/down/neutral","reason":"핵심판단40자이내","bullets":["퀀트해석","뉴스_애널리스트연결","조건부액션"],"tags":["태그1","태그2"],"related":[{{"ticker":"관련기업","reason":"연관이유"}}]}}]

rules:
- 한국어
- signal: 퀀트+애널리스트+뉴스 종합 판단. 상충 신호면 neutral
- reason: 40자 이내. 가장 중요한 판단 한 문장 (예: "강력매수 컨센서스나 목표가 이미 하회, 단기 과열 가능성")
- bullets 정확히 3개:
  ①퀀트해석: "A지표와 B지표가 상반되므로/일치하므로 ~를 의미한다" 형식. 수치 나열 금지
  ②뉴스_애널리스트: 뉴스와 애널리스트 데이터 중 퀀트와 상충하는 신호가 있으면 반드시 언급. 없으면 강화/약화 방향 서술
  ③조건부액션: "~가 확인되면 비중확대 / ~시 축소 고려" 형식으로 조건 명시. "비중 유지" 단독 사용 금지
- related: 연관 기업 1~2개, 포트폴리오 내외 무관(없으면[])
- 반드시 {len(holdings)}개 전부 포함: {', '.join(tickers_list)}"""
    )


# ─────────────────────────────────────────────
# Gemini 호출
# ─────────────────────────────────────────────

def _gemini_batch(
    holdings: dict,
    data_map: dict,
    quant_ctx: dict,
    analyst_ctx: dict,
    api_key: str,
) -> dict[str, dict]:
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_SYSTEM_PROMPT,
    )
    response = model.generate_content(
        _build_batch_prompt(holdings, data_map, quant_ctx, analyst_ctx)
    )
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
    analyst_ctx: dict,
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
    ana        = analyst_ctx.get(ticker, {})
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

    # 애널리스트 블록
    ana_parts = []
    if ana.get("rec_key"):
        ana_parts.append(f"투자의견:{ana['rec_key']}")
    if ana.get("target_upside_pct") is not None:
        ana_parts.append(f"목표주가상승여력:{ana['target_upside_pct']:+.1f}%")
    if ana.get("earnings_days_left") is not None:
        d = ana["earnings_days_left"]
        ana_parts.append(f"어닝{'D+'+str(abs(d)) if d < 0 else 'D-'+str(d)}")
    if ana.get("eps_surprise_pct") is not None:
        ana_parts.append(f"직전EPS서프라이즈:{ana['eps_surprise_pct']:+.1f}%")
    ana_str = " | ".join(ana_parts) if ana_parts else "N/A"

    prompt = (
        f"종목:{ticker} ({shares:.1f}주) | 시장:{market_str} | 전일대비:{change_str}\n"
        f"퀀트: {quant_str}\n"
        f"애널리스트: {ana_str}\n"
        f"뉴스:\n{news_str}\n\n"
        f"상충 신호가 있으면 반드시 언급하고, 액션은 조건부로 명시하세요.\n"
        f'JSON:{{"signal":"up/down/neutral","reason":"40자이내핵심판단","bullets":["퀀트해석(인과관계형식)","뉴스_애널리스트(상충신호포함)","조건부액션(조건명시)"],"tags":["태그1"],"related":[]}}'
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

    # ── 2단계: 퀀트 컨텍스트 + 애널리스트 데이터 병렬 계산 ────────
    if progress_callback:
        progress_callback(0, total, "퀀트 지표 계산 중", None)

    with ThreadPoolExecutor(max_workers=2) as ex:
        f_quant    = ex.submit(fetch_quant_context, tickers)
        f_analyst  = ex.submit(fetch_analyst_data,  tickers)
        quant_ctx  = f_quant.result()
        analyst_ctx = f_analyst.result()

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
        re_analyst  = {t: analyst_ctx.get(t, {}) for t in reanalyze_tickers}

        try:
            batch_result = _gemini_batch(re_holdings, re_data, re_quant, re_analyst, api_key)
            signal_map.update(batch_result)
        except Exception:
            if progress_callback:
                progress_callback(1, total, "배치 실패, 순차 분석 중...", None)
            for i, t in enumerate(reanalyze_tickers):
                articles, change_pct = re_data.get(t, ([], None))
                try:
                    signal_map[t] = _gemini_single(
                        t, holdings[t], articles, change_pct,
                        re_quant, re_analyst, api_key
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
            ana  = analyst_ctx.get(ticker, {})
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
                "analyst": {
                    "rec_key":            ana.get("rec_key"),
                    "rec_mean":           ana.get("rec_mean"),
                    "n_analysts":         ana.get("n_analysts"),
                    "current_price":      ana.get("current_price"),
                    "target_mean":        ana.get("target_mean"),
                    "target_high":        ana.get("target_high"),
                    "target_low":         ana.get("target_low"),
                    "target_upside_pct":  ana.get("target_upside_pct"),
                    "earnings_date":      ana.get("earnings_date"),
                    "earnings_days_left": ana.get("earnings_days_left"),
                    "eps_surprise_pct":   ana.get("eps_surprise_pct"),
                },
            }
            results.append(item)

        if progress_callback:
            progress_callback(tickers.index(ticker) + 1, total, ticker, results[-1])

    return results