"""
utils/ai_client.py

1단계: 전체 종목 데이터 병렬 수집 (Finnhub / yfinance)
2단계: Gemini 단일 배치 호출 (전체 종목 한 번에)
       → 실패 시 종목별 순차 fallback
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
# 데이터 수집 (병렬)
# ─────────────────────────────────────────────

def _fetch_finnhub(ticker: str, finnhub_key: str) -> tuple[list[str], float | None]:
    import requests
    headers = {"X-Finnhub-Token": finnhub_key}
    headlines = []
    change_pct = None

    try:
        r = requests.get(
            "https://finnhub.io/api/v1/quote",
            params={"symbol": ticker},
            headers=headers, timeout=5,
        )
        data = r.json()
        curr = data.get("c", 0)
        prev = data.get("pc", 0)
        if prev and prev > 0:
            change_pct = round((curr - prev) / prev * 100, 2)
    except Exception:
        pass

    try:
        today = date.today()
        from_date = (today - timedelta(days=3)).isoformat()
        r = requests.get(
            "https://finnhub.io/api/v1/company-news",
            params={"symbol": ticker, "from": from_date, "to": today.isoformat()},
            headers=headers, timeout=5,
        )
        for item in r.json()[:3]:
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


def _fetch_yfinance(ticker: str) -> tuple[list[str], float | None]:
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
    if finnhub_key:
        headlines, change_pct = _fetch_finnhub(ticker, finnhub_key)
        if headlines or change_pct is not None:
            return headlines, change_pct
    return _fetch_yfinance(ticker)


# ─────────────────────────────────────────────
# Gemini — 배치 호출 (전체 종목 한 번에)
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = "주식 분석 AI. JSON 배열만 응답. 코드블록이나 설명 텍스트 절대 없이."

def _build_batch_prompt(holdings: dict, data_map: dict) -> str:
    items = []
    for ticker, shares in holdings.items():
        headlines, change_pct = data_map.get(ticker, ([], None))
        change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
        news_str = " / ".join(headlines) if headlines else "없음"
        items.append(f"[{ticker}] {shares:.1f}주 변동:{change_str} 뉴스:{news_str}")

    return f"""다음 {len(holdings)}개 종목 분석:

{chr(10).join(items)}

JSON 배열로만 응답 (코드블록 없이):
[{{"ticker":"종목","signal":"up/down/neutral","reason":"핵심이유20자이내","bullets":["구체이유1","구체이유2","투자포인트"],"tags":["태그1","태그2"],"related":[{{"ticker":"관련","reason":"이유"}}]}}]

rules: 한국어, bullets 정확히 3개, related 1~2개(없으면[]), 반드시 {len(holdings)}개 전부 포함"""


def _gemini_batch(holdings: dict, data_map: dict, api_key: str) -> dict[str, dict]:
    """전체 종목 한 번에 분석. {ticker: result} 반환."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction=_SYSTEM_PROMPT,
    )
    response = model.generate_content(_build_batch_prompt(holdings, data_map))
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

    results_list = json.loads(raw)
    result_map = {}
    for item in results_list:
        ticker = item.get("ticker", "")
        if not ticker:
            continue
        # 가격변동 기반 signal 보정
        headlines, change_pct = data_map.get(ticker, ([], None))
        if change_pct is not None:
            if change_pct >= 0.5:
                item["signal"] = "up"
            elif change_pct <= -0.5:
                item["signal"] = "down"
            else:
                item["signal"] = "neutral"
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


def _gemini_single(ticker: str, shares: float, change_pct: float | None,
                   headlines: list[str], api_key: str) -> dict:
    """단일 종목 분석 (배치 실패 시 fallback)."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    model = genai.GenerativeModel(
        model_name="gemini-2.5-flash-lite",
        system_instruction="주식 분석 AI. JSON만 응답. 코드블록 없이.",
    )
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "N/A"
    news_str = "\n".join(f"· {h}" for h in headlines) if headlines else "· 없음"
    prompt = f"""종목:{ticker} ({shares:.1f}주) 변동:{change_str}
뉴스:
{news_str}

JSON:
{{"signal":"up/down/neutral","reason":"20자이내","bullets":["이유1","이유2","이유3"],"tags":["태그1"],"related":[]}}"""

    response = model.generate_content(prompt)
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    result = json.loads(raw)

    if change_pct is not None:
        result["signal"] = "up" if change_pct >= 0.5 else "down" if change_pct <= -0.5 else "neutral"

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
# 메인 분석
# ─────────────────────────────────────────────

def analyze_portfolio_signals(
    holdings: dict[str, float],
    api_key: str,
    finnhub_key: str | None = None,
    progress_callback=None,
    portfolio=None,
) -> list[dict]:

    holdings = {t: s for t, s in holdings.items() if s > 0}
    tickers  = list(holdings.keys())
    total    = len(tickers)
    from datetime import datetime
    today     = date.today().isoformat()
    now_time  = datetime.now().strftime("%H:%M")

    # 1단계: 병렬 데이터 수집
    if progress_callback:
        progress_callback(0, total, "데이터 수집 중", None)

    data_map = {}
    with ThreadPoolExecutor(max_workers=min(10, total)) as executor:
        futures = {executor.submit(fetch_ticker_data, t, finnhub_key): t for t in tickers}
        for future in as_completed(futures):
            t = futures[future]
            try:
                data_map[t] = future.result()
            except Exception:
                data_map[t] = ([], None)

    # 2단계: Gemini 배치 호출
    if progress_callback:
        progress_callback(1, total, "AI 분석 중", None)

    signal_map = {}
    try:
        signal_map = _gemini_batch(holdings, data_map, api_key)
    except Exception as e:
        # 배치 실패 시 종목별 순차 fallback
        if progress_callback:
            progress_callback(1, total, f"배치 실패, 순차 분석 중...", None)
        for i, ticker in enumerate(tickers):
            headlines, change_pct = data_map.get(ticker, ([], None))
            try:
                signal_map[ticker] = _gemini_single(
                    ticker, holdings[ticker], change_pct, headlines, api_key
                )
            except Exception as e2:
                signal_map[ticker] = {"_error": str(e2)}
            if progress_callback:
                progress_callback(i + 1, total, ticker, None)

    # 결과 조합
    results = []
    for ticker in tickers:
        headlines, change_pct = data_map.get(ticker, ([], None))
        sig = signal_map.get(ticker, {"_error": "분석 결과 없음"})
        item = {
            "ticker":        ticker,
            "shares":        holdings[ticker],
            "change_pct":    change_pct,
            "headlines":     headlines,
            "signal":        sig,
            "logo_url":      portfolio.get_logo(ticker) if portfolio else None,
            "analyzed_date": today,
            "analyzed_time": now_time,
        }
        results.append(item)
        if progress_callback:
            progress_callback(tickers.index(ticker) + 1, total, ticker, item)

    return results