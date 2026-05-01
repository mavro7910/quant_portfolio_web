"""
core/data.py
------------
"""
from __future__ import annotations

import pandas as pd
import yfinance as yf


def extract_close(raw: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance 1.2.0+ : 단일/멀티 티커 모두 MultiIndex (Price, Ticker) 반환.
    Close 레벨만 추출해 Flat DataFrame (index=날짜, columns=티커) 로 반환.
    구버전 Flat Index 도 호환 처리.
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        for price_col in ("Close", "Adj Close"):
            if price_col in raw.columns.get_level_values(0):
                df = raw[price_col]
                if isinstance(df, pd.Series):
                    df = df.to_frame()
                return df
        raise ValueError("Close 컬럼을 찾을 수 없습니다.")
    else:
        for col in ("Close", "Adj Close"):
            if col in raw.columns:
                return raw[[col]]
        return raw


def fetch_last_close(ticker: str, period: str = "5d") -> float | None:
    """단일 티커의 최신 종가를 반환. 실패 시 None."""
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        df = extract_close(raw)
        if df.empty:
            return None
        col = ticker if ticker in df.columns else df.columns[0]
        return float(df[col].dropna().iloc[-1])
    except Exception:
        return None


def fetch_prices_and_fx(
    tickers: list[str],
    period: str = "5d",
) -> tuple[pd.Series, float, bool]:
    """
    보유 종목 시세 + USD/KRW 환율 일괄 조회.

    Returns:
        prices   : {ticker: 최신 종가(USD)} Series
        fx_rate  : USD/KRW 환율
        fx_estimated : FX 조회 실패 여부 (True = 추정값 사용)
    """
    all_sym = list(dict.fromkeys(tickers + ["USDKRW=X"]))
    raw = yf.download(all_sym, period=period, auto_adjust=True, progress=False)
    close = extract_close(raw).ffill()

    # 환율
    fx_estimated = False
    if "USDKRW=X" in close.columns:
        fx_rate = float(close["USDKRW=X"].dropna().iloc[-1])
    else:
        fx_rate = 1_480.0  #기준 환율 (환율 정보 못 불러오면 사용할 값)
        fx_estimated = True

    # 종목 시세
    available = [t for t in tickers if t in close.columns]
    if not available:
        raise ValueError("유효한 티커가 없습니다. 티커를 확인하세요.")
    prices = close[available].iloc[-1]

    return prices, fx_rate, fx_estimated
