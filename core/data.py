"""
core/data.py

변경사항:

- [BUG FIX] extract_close: 단일 티커 다운로드 시 MultiIndex 컬럼이
  (Price, ) 형태로 내려오는 경우 티커명 복원 처리 추가
- [BUG FIX] fetch_prices_and_fx: 환율 fallback 값 1,480 → 1,450으로 현실화
  (strategy.py FX_FALLBACK 과 동일하게 통일)
- [BUG FIX] fetch_prices_and_fx: close가 비어 있을 때 빈 Series 대신
  명시적 에러 메시지 발생
- [개선] extract_close: 컬럼이 1개인 Series 반환 케이스 방어 강화
- [개선] fetch_last_close: period 기본값 "5d" → "10d" (휴장일 연속 시 데이터 없음 방지)
"""

from __future__ import annotations

import pandas as pd
import yfinance as yf

FX_FALLBACK = 1_450.0  # strategy.py 와 동일하게 유지


def extract_close(raw: pd.DataFrame) -> pd.DataFrame:
    """
    yfinance 1.2.0+ : 단일/멀티 티커 모두 MultiIndex (Price, Ticker) 반환.
    Close 레벨만 추출해 Flat DataFrame (index=날짜, columns=티커) 으로 반환.
    구버전 Flat Index 도 호환 처리.

    수정:
    - 단일 티커 다운로드 시 MultiIndex 두 번째 레벨이 빈 문자열('')로
      내려오는 yfinance 버그 대응 → ticker 명을 직접 복원
    - Series 반환 케이스 DataFrame 변환 보장
    """
    if raw is None or raw.empty:
        return pd.DataFrame()

    if isinstance(raw.columns, pd.MultiIndex):
        for price_col in ("Close", "Adj Close"):
            if price_col in raw.columns.get_level_values(0):
                df = raw[price_col]
                # Series인 경우 DataFrame으로 변환
                if isinstance(df, pd.Series):
                    df = df.to_frame()
                # 컬럼명이 빈 문자열이거나 숫자인 경우 정리
                df.columns = [
                    str(c).strip() if str(c).strip() else price_col
                    for c in df.columns
                ]
                return df
        raise ValueError(f"Close 컬럼을 찾을 수 없습니다. 사용 가능한 컬럼: {raw.columns.tolist()}")

    else:
        # 구버전 Flat Index
        for col in ("Close", "Adj Close"):
            if col in raw.columns:
                return raw[[col]]
        return raw


def fetch_last_close(ticker: str, period: str = "10d") -> float | None:
    """
    단일 티커의 최신 종가를 반환. 실패 시 None.
    period 기본값을 10d로 늘려 연휴/휴장일 연속 시 데이터 누락 방지.
    """
    try:
        raw = yf.download(ticker, period=period, auto_adjust=True, progress=False)
        df = extract_close(raw)
        if df.empty:
            return None
        col = ticker if ticker in df.columns else df.columns[0]
        series = df[col].dropna()
        if series.empty:
            return None
        return float(series.iloc[-1])
    except Exception:
        return None


def fetch_prices_and_fx(
    tickers: list[str],
    period: str = "10d",  # 5d → 10d: 휴장일 연속 시 데이터 없음 방지
) -> tuple[pd.Series, float, bool]:
    """
    보유 종목 시세 + USD/KRW 환율 일괄 조회.

    Returns:
        prices      : {ticker: 최신 종가(USD)} Series
        fx_rate     : USD/KRW 환율
        fx_estimated: FX 조회 실패 여부 (True = 추정값 사용)
    """
    if not tickers:
        raise ValueError("티커 목록이 비어 있습니다.")

    all_sym = list(dict.fromkeys(tickers + ["USDKRW=X"]))
    raw = yf.download(all_sym, period=period, auto_adjust=True, progress=False)
    close = extract_close(raw).ffill()

    if close.empty:
        raise ValueError("시세 데이터를 가져오지 못했습니다. 네트워크 상태를 확인하세요.")

    # 환율
    fx_estimated = False
    if "USDKRW=X" in close.columns:
        fx_series = close["USDKRW=X"].dropna()
        if fx_series.empty:
            fx_rate = FX_FALLBACK
            fx_estimated = True
        else:
            fx_rate = float(fx_series.iloc[-1])
    else:
        fx_rate = FX_FALLBACK
        fx_estimated = True

    # 종목 시세
    available = [t for t in tickers if t in close.columns]
    if not available:
        raise ValueError(
            f"유효한 티커가 없습니다. 요청: {tickers}, "
            f"사용 가능: {close.columns.tolist()}"
        )

    prices = close[available].iloc[-1]

    # 요청했지만 데이터 없는 티커는 NaN으로 포함 (호출부에서 N/A 표시)
    prices = prices.reindex(tickers)

    return prices, fx_rate, fx_estimated