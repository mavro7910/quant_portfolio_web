"""
utils/ai_client.py

Gemini API 호출 헬퍼.
- session_state에서 API 키 조회
- yfinance 뉴스 헤드라인 수집
- 종목별 시그널 분석 요청 및 JSON 파싱
"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import Optional

import streamlit as st


# ─────────────────────────────────────────────
# API 키 관리
# ─────────────────────────────────────────────

def get_api_key() -> str | None:
    """session_state에서 Gemini API 키 반환. 없으면 None."""
    return st.session_state.get("gemini_api_key") or None


def set_api_key(key: str):
    """session_state에 API 키 저장."""
    st.session_state["gemini_api_key"] = key.strip()


def clear_api_key():
    st.session_state.pop("gemini_api_key", None)


def has_api_key() -> bool:
    k = get_api_key()
    return bool(k and len(k) > 10)


# ─────────────────────────────────────────────
# 키 검증
# ─────────────────────────────────────────────

def validate_api_key(api_key: str) -> tuple[bool, str | None]:
    """
    Gemini API 키 유효성 검증.
    성공: (True, None) / 실패: (False, 에러메시지)
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(model_name="gemini-2.5-flash")
        response = model.generate_content("hi")
        _ = response.text
        return True, None
    except Exception as e:
        return False, str(e)


# ─────────────────────────────────────────────
# 뉴스 수집
# ─────────────────────────────────────────────

def fetch_news_headlines(ticker: str, max_items: int = 8) -> list[str]:
    """
    yfinance로 ticker 뉴스 헤드라인 수집.
    실패 시 빈 리스트 반환.
    """
    try:
        import yfinance as yf
        news = yf.Ticker(ticker).news or []
        headlines = []
        for item in news[:max_items]:
            title = (
                item.get("title")
                or item.get("content", {}).get("title")
                or ""
            )
            if title:
                headlines.append(title)
        return headlines
    except Exception:
        return []


def fetch_price_change(ticker: str) -> float | None:
    """
    당일 또는 최근 1일 주가 변동률(%) 반환.
    실패 시 None.
    """
    try:
        import yfinance as yf
        df = yf.download(ticker, period="5d", auto_adjust=True, progress=False)
        if df.empty or len(df) < 2:
            return None
        closes = df["Close"].dropna()
        if len(closes) < 2:
            return None
        prev, curr = float(closes.iloc[-2]), float(closes.iloc[-1])
        if prev == 0:
            return None
        return round((curr - prev) / prev * 100, 2)
    except Exception:
        return None


# ─────────────────────────────────────────────
# Gemini 호출
# ─────────────────────────────────────────────

_SYSTEM_PROMPT = """당신은 주식 시장 분석 전문가입니다.
주어진 종목의 뉴스 헤드라인과 주가 변동을 분석하여 투자자에게 핵심 시그널을 제공합니다.
반드시 JSON만 응답하고, 마크다운 코드블록이나 다른 텍스트는 절대 포함하지 마세요."""


def _build_prompt(
    ticker: str,
    shares: float,
    change_pct: float | None,
    headlines: list[str],
) -> str:
    change_str = f"{change_pct:+.2f}%" if change_pct is not None else "데이터 없음"
    headlines_str = "\n".join(f"- {h}" for h in headlines) if headlines else "- 뉴스 없음"

    return f"""종목: {ticker} (보유 {shares:.2f}주)
오늘 주가 변동: {change_str}
최근 뉴스 헤드라인:
{headlines_str}

위 정보를 분석하여 아래 JSON 형식으로만 응답하세요:
{{
  "signal": "up" 또는 "down" 또는 "neutral",
  "reason": "한 줄 요약 (왜 움직였는지, ~으로 로 끝내기, 20자 이내)",
  "bullets": ["핵심 이유 1", "핵심 이유 2", "핵심 이유 3"],
  "tags": ["태그1", "태그2"],
  "related": [
    {{"ticker": "관련종목티커", "reason": "연관성 한줄 설명"}}
  ]
}}

주의:
- signal은 오늘 변동률 기준으로 판단 (변동 없거나 뉴스 없으면 neutral)
- bullets는 정확히 3개
- tags는 2~3개 (예: "AI 기능 출시", "매수 의견", "실적 개선")
- related는 보유 종목과 연관된 다른 기업 1~2개 (없으면 빈 배열)
- 모든 텍스트는 한국어로"""


def analyze_signal(
    ticker: str,
    shares: float,
    change_pct: float | None,
    headlines: list[str],
    api_key: str,
) -> dict | None:
    """
    Gemini API로 시그널 분석.
    성공 시 파싱된 dict, 실패 시 None.
    """
    try:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel(
            model_name="gemini-2.5-flash",
            system_instruction=_SYSTEM_PROMPT,
        )
        prompt = _build_prompt(ticker, shares, change_pct, headlines)
        response = model.generate_content(prompt)
        raw = response.text.strip()

        # JSON 코드블록 제거
        raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()

        try:
            result = json.loads(raw)
        except json.JSONDecodeError:
            return {"_error": f"JSON 파싱 실패 (응답 앞 200자): {raw[:200]}"}

        # 필수 키 검증 및 기본값 보장
        result.setdefault("signal", "neutral")
        result.setdefault("reason", "분석 정보 없음")
        result.setdefault("bullets", ["정보가 충분하지 않습니다."] * 3)
        result.setdefault("tags", [])
        result.setdefault("related", [])

        # bullets 정확히 3개 보장
        while len(result["bullets"]) < 3:
            result["bullets"].append("추가 정보 없음")
        result["bullets"] = result["bullets"][:3]

        return result

    except Exception as e:
        return {"_error": str(e)}


# ─────────────────────────────────────────────
# 종목 일괄 분석
# ─────────────────────────────────────────────

def _analyze_one(ticker: str, shares: float, api_key: str) -> dict:
    """단일 종목 분석 (병렬 처리용)."""
    change_pct = fetch_price_change(ticker)
    headlines  = fetch_news_headlines(ticker)
    signal     = analyze_signal(ticker, shares, change_pct, headlines, api_key)
    return {
        "ticker":        ticker,
        "shares":        shares,
        "change_pct":    change_pct,
        "headlines":     headlines,
        "signal":        signal,
        "analyzed_date": date.today().isoformat(),
    }


def analyze_portfolio_signals(
    holdings: dict[str, float],
    api_key: str,
    progress_callback=None,
) -> list[dict]:
    """
    보유 종목 전체 시그널 분석 (병렬 처리).
    progress_callback(current, total, ticker) 으로 진행 상황 전달.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    tickers = list(holdings.keys())
    total   = len(tickers)
    results = [None] * total
    done    = 0

    with ThreadPoolExecutor(max_workers=min(5, total)) as executor:
        future_map = {
            executor.submit(_analyze_one, t, holdings[t], api_key): i
            for i, t in enumerate(tickers)
        }
        for future in as_completed(future_map):
            idx = future_map[future]
            try:
                results[idx] = future.result()
            except Exception as e:
                results[idx] = {
                    "ticker":        tickers[idx],
                    "shares":        holdings[tickers[idx]],
                    "change_pct":    None,
                    "headlines":     [],
                    "signal":        {"_error": str(e)},
                    "analyzed_date": date.today().isoformat(),
                }
            done += 1
            if progress_callback:
                progress_callback(done, total, tickers[idx])

    if progress_callback:
        progress_callback(total, total, "완료")

    return results
