"""
utils/ai_client.py

데이터 수집: Finnhub (빠름) → fallback yfinance
분석: Gemini 종목별 순차, 완료 즉시 콜백
"""

from __future__ import annotations

import json
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, timedelta

import streamlit as st


# ─────────────────────────────────────────────
# API 키 관리 (session_state)
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


# ─────────────────────────────────────────────
# Finnhub 데이터 수집
# ─────────────────────────────────────────────

def _fetch_finnhub(ticker: str, finnhub_key: str) -> tuple[list[str], float | None]:
    """Finnhub으로 뉴스 + 가격변동 수집."""
    import requests
    from datetime import datetime

    headers = {"X-Finnhub-Token": finnhub_key}
    headlines = []
    change_pct = None

    # 가격
    try:
        r = requests.get(
            f"https://finnhub.io/api/v1/quote",
            params={"symbol": ticker},
            headers=headers,
            timeout=5,
        )
        data = r.json()
        curr = data.get("c", 0)
        prev = data.get("pc", 0)
        if prev and prev > 0:
            change_pct = round((curr - prev) / prev * 100, 2)
    except Exception:
        pass

    # 뉴스 (최근 3일)
    try:
        today = date.today()
        from_date = (today - timedelta(days=3)).isoformat()
        to_date = today.isoformat()
        r = requests.get(
            f"https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": from_date, "to": to_date},
            headers=headers,
            timeout=5,
        )
        news = r.json()
        for item in news[:3]:
            headline = item.get("headline", "")
            summary  = item.get("summary", "")
            if headline:
                text = headline
                if summary and len(summary) > 20:
                    text += f" — {summary[:80]}"
                headlines.append(text)
    except Exception:
        pass

    return headlines, change_pct


def _fetch_yfinance_fallback(ticker: str) -> tuple[list[str], float | None]:
    """yfinance fallback."""
    try:
        import yfinance as yf
        tk = yf.Ticker(ticker)

        news = tk.news or []
        headlines = []
        for item in news[:5]:
            title = (
                item.get("title")
                or item.get("content", {}).get("title")
                or item.get("content", {}).get("summary", "")
            )
            title = str(title).strip()
            if title and len(title) > 5:
                headlines.append(title)
            if len(headlines) >= 3:
                break

        change_pct = None
        hist = tk.history(period="5d")
        if len(hist) >= 2:
            prev = float(hist["Close"].iloc[-2])
            curr = float(hist["Close"].iloc[-1])
            if prev > 0:
                change_pct = round((curr - prev) / prev * 100, 2)

        return headlines, change_pct
    except Exception:
        return [], None


def fetch_ticker_data(ticker: str, finnhub_key: str | None) -> tuple[list[str], float | None]:
    """Finnhub 우선, 실패 시 yfinance fallback."""
    if finnhub_key:
        headlines, change_pct = _fetch_finnhub(ticker, finnhub_key)
        if headlines or change_pct is not None:
            return headlines, change_pct
    return _fetch_yfinance_fallback(ticker)


# ─────────────────────────────────────────────
# Gemini 단일 종목 분석
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = "주식 분석 AI. JSON만 응답. 코드블록 없이."

def _build_prompt(ticker: str, shares: float, change_pct: float | None, headlines: list[str]) -> str:
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "데이터 없음"
    news_str = "\n".join(f"· {h}" for h in headlines) if headlines else "· 수집된 뉴스 없음"
    return f"""종목: {ticker} (보유 {shares:.1f}주) / 오늘 변동: {change_str}
뉴스:
{news_str}

JSON으로만 응답:
{{"signal":"up/down/neutral","reason":"핵심이유20자이내","bullets":["뉴스기반구체이유1","뉴스기반구체이유2","투자포인트또는리스크"],"tags":["키워드1","키워드2"],"related":[{{"ticker":"연관티커","reason":"연관이유"}}]}}

rules: 한국어, bullets 정확히 3개(뉴스 구체적 언급), related 1~2개(없으면[])"""


def _gemini_analyze(ticker: str, shares: float, change_pct: float | None, headlines: list[str], api_key: str) -> dict:
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash-lite",
            system_instruction=_SYSTEM_PROMPT,
        )
        response = model.generate_content(_build_prompt(ticker, shares, change_pct, headlines))
        raw = response.text.strip()
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
        result = json.loads(raw)

        # 가격변동 기반 signal 보정
        if change_pct is not None:
            if change_pct >= 0.5:
                result["signal"] = "up"
            elif change_pct <= -0.5:
                result["signal"] = "down"
            else:
                result["signal"] = "neutral"

        result.setdefault("signal", "neutral")
        result.setdefault("reason", "분석 정보 없음")
        result.setdefault("bullets", ["정보 없음"] * 3)
        result.setdefault("tags", [])
        result.setdefault("related", [])
        while len(result["bullets"]) < 3:
            result["bullets"].append("추가 정보 없음")
        result["bullets"] = result["bullets"][:3]
        return result

    except json.JSONDecodeError as e:
        return {"_error": f"JSON 파싱 실패: {str(e)}"}
    except Exception as e:
        return {"_error": str(e)}


# ─────────────────────────────────────────────
# 메인 분석 함수
# ─────────────────────────────────────────────

def analyze_portfolio_signals(
    holdings: dict[str, float],
    api_key: str,
    finnhub_key: str | None = None,
    progress_callback=None,
) -> list[dict]:
    holdings = {t: s for t, s in holdings.items() if s > 0}
    tickers  = list(holdings.keys())
    total    = len(tickers)
    today    = date.today().isoformat()
    results  = []

    # 1단계: 전체 데이터 병렬 수집
    if progress_callback:
        progress_callback(0, total, "데이터 수집 중", None)

    data_map = {}
    with ThreadPoolExecutor(max_workers=min(10, total)) as executor:
        futures = {
            executor.submit(fetch_ticker_data, t, finnhub_key): t
            for t in tickers
        }
        for future in as_completed(futures):
            t = futures[future]
            try:
                data_map[t] = future.result()
            except Exception:
                data_map[t] = ([], None)

    # 2단계: Gemini 종목별 순차 분석
    for i, ticker in enumerate(tickers):
        if progress_callback:
            progress_callback(i, total, ticker, None)

        headlines, change_pct = data_map.get(ticker, ([], None))
        signal = _gemini_analyze(ticker, holdings[ticker], change_pct, headlines, api_key)

        item = {
            "ticker":        ticker,
            "shares":        holdings[ticker],
            "change_pct":    change_pct,
            "headlines":     headlines,
            "signal":        signal,
            "analyzed_date": today,
        }
        results.append(item)

        if progress_callback:
            progress_callback(i + 1, total, ticker, item)

    return results
