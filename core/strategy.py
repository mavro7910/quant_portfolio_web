"""
core/strategy.py -- 개선판

[수정 사항]
1. [BUG FIX] Look-ahead bias: 백테스트에서 mcap 대신 발행주수×과거주가로 시총 근사
2. [BUG FIX] CAGR → XIRR(내부수익률)로 교체 -- 적립식 수익률 현실화
3. [유지] use_market_cap=True 시 시총을 루프 시작 전 1회만 조회
4. [유지] alloc_krw=0 종목 0나눗셈/NaN 방지
5. [유지] rebal_days 날짜 조회 빈 배열 IndexError 방어
6. [유지] cp=0/NaN 종목 매수 스킵
7. [유지] FX fallback 1,450
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from scipy.optimize import brentq
from core.data import extract_close

warnings.filterwarnings("ignore")

MAX_WEIGHT     = 0.25
MOMENTUM_WEIGHTS = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
VOL_WINDOW     = 60
MA_WINDOW      = 200
FX_FALLBACK    = 1_450.0

# ──────────────────────────────────────────────
# 데이터 수집
# ──────────────────────────────────────────────

def fetch_prices(
    tickers: list[str],
    extra: list[str] | None = None,
    period: str = "3y",
    start: str | None = None,   # ← 추가
    end: str | None = None,     # ← 추가
) -> dict[str, pd.DataFrame | pd.Series]:
    """
    start/end 를 지정하면 period 는 무시됩니다.
    백테스트처럼 재현성이 필요한 경우 start/end 고정 사용을 권장합니다.
    """
    extra   = extra or []
    all_sym = list(dict.fromkeys(tickers + extra))

    if start:
        raw = yf.download(
            all_sym, start=start, end=end,
            interval="1d", auto_adjust=True, progress=False,
        )
    else:
        raw = yf.download(
            all_sym, period=period,
            interval="1d", auto_adjust=True, progress=False,
        )

    close = extract_close(raw).ffill()

    result: dict[str, pd.DataFrame | pd.Series] = {}
    available = close.columns.tolist()

    valid_tickers = [t for t in tickers if t in available]
    if not valid_tickers:
        raise ValueError(f"유효한 티커가 없습니다. available: {available}")

    result["prices"] = close[valid_tickers].copy()
    for sym in extra:
        if sym in available:
            result[sym] = close[sym]

    return result


def fetch_market_caps(tickers: list[str]) -> pd.Series:
    """시가총액 조회 (매수추천 전용 -- 백테스트에서는 사용 금지)."""
    caps = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            mcap = info.get("marketCap")
            caps[t] = float(mcap) if mcap and mcap > 0 else np.nan
        except Exception:
            caps[t] = np.nan

    s = pd.Series(caps, dtype=float)
    min_val = s.dropna().min()
    s = s.fillna(min_val if pd.notna(min_val) and min_val > 0 else 1.0)
    return s


def fetch_shares_outstanding(tickers: list[str]) -> pd.Series:
    """
    발행주수 1회 조회.
    백테스트에서 '과거 주가 × 발행주수'로 시총을 근사할 때 사용.

    발행주수는 수년간 크게 변하지 않으므로 현재값을 그대로 써도
    순수 현재 시총을 쓰는 것보다 look-ahead bias가 훨씬 적음.
    (자사주 매입 등 변동은 있으나 순위 역전 수준은 드묾)
    """
    shares = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            s = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            shares[t] = float(s) if s and s > 0 else np.nan
        except Exception:
            shares[t] = np.nan

    sr = pd.Series(shares, dtype=float)
    # 조회 실패 종목은 중앙값으로 대체
    med = sr.dropna().median()
    sr = sr.fillna(med if pd.notna(med) and med > 0 else 1.0)
    return sr


def _get_loc_safe(index: pd.DatetimeIndex, date) -> int | None:
    mask = index <= date
    if not mask.any():
        return None
    return int(np.where(mask)[0][-1])


# ──────────────────────────────────────────────
# XIRR (적립식 내부수익률)
# ──────────────────────────────────────────────

def xirr(dates: list, cashflows: list[float]) -> float:
    """
    XIRR: 불규칙 현금흐름의 연수익률.

    cashflows 부호 규칙:
      - 투자(지출) → 음수
      - 회수(수령) → 양수

    수렴 실패 시 float("nan") 반환.
    """
    if len(dates) != len(cashflows):
        return float("nan")

    t0 = dates[0]
    days = np.array([(d - t0).days for d in dates], dtype=float)

    def npv(rate: float) -> float:
        # rate < -1 이면 분모가 0 또는 음수 → 발산 방지
        if rate <= -1.0:
            return float("inf")
        return float(np.sum(np.array(cashflows) / (1.0 + rate) ** (days / 365.25)))

    try:
        return brentq(npv, -0.9999, 1000.0, maxiter=1000)
    except (ValueError, RuntimeError):
        return float("nan")


def calc_xirr_from_backtest(
    df_bt: pd.DataFrame,
    weekly_budget: int,
    col: str = "KH_Strategy",
) -> float:
    """백테스트 DataFrame에서 특정 컬럼의 XIRR 계산."""
    dates = list(df_bt.index)
    cfs = [-float(weekly_budget)] * len(dates)
    # 마지막 시점에 전액 회수로 처리
    cfs[-1] += float(df_bt[col].iloc[-1])
    return xirr(dates, cfs)


# ──────────────────────────────────────────────
# 팩터 계산
# ──────────────────────────────────────────────

def momentum_score(df: pd.DataFrame) -> pd.Series:
    score = pd.Series(0.0, index=df.columns)
    total_w = 0.0
    for days, w in MOMENTUM_WEIGHTS.items():
        if len(df) <= days:
            continue
        ret = df.pct_change(days).iloc[-1].fillna(0)
        score += w * ret.rank(pct=True)
        total_w += w
    if total_w > 0:
        score /= total_w
    return score


def vol_inv_rank(df: pd.DataFrame, window: int = VOL_WINDOW) -> pd.Series:
    vol = df.pct_change().rolling(window).std().iloc[-1]
    inv = (1 / vol.replace(0, np.nan)).fillna(0)
    if inv.sum() == 0:
        return pd.Series(1.0 / len(df.columns), index=df.columns)
    return inv.rank(pct=True)


def base_weights(
    tickers: list[str],
    df_columns: pd.Index,
    use_market_cap: bool = False,
    mcap_cache: pd.Series | None = None,
) -> pd.Series:
    if use_market_cap and tickers:
        mcaps = mcap_cache if mcap_cache is not None else fetch_market_caps(tickers)
        w = (mcaps / mcaps.sum()).reindex(df_columns).fillna(0)
    else:
        w = pd.Series(1.0 / len(df_columns), index=df_columns)
    return w


def target_weights(
    df: pd.DataFrame,
    qqq: pd.Series,
    use_market_cap: bool = False,
    tickers: list[str] | None = None,
    max_weight: float = MAX_WEIGHT,
    mcap_cache: pd.Series | None = None,
) -> tuple[pd.Series, bool]:
    tickers = tickers or df.columns.tolist()

    is_bull = float(qqq.iloc[-1]) > float(qqq.rolling(MA_WINDOW).mean().iloc[-1])

    w_base = base_weights(tickers, df.columns, use_market_cap, mcap_cache)

    p_mom = 2.0 if is_bull else 1.2
    p_vol = 1.5
    w_mom = momentum_score(df) ** p_mom
    w_vol = vol_inv_rank(df) ** p_vol

    m_weight = 0.7 if is_bull else 0.4
    v_weight = 0.3 if is_bull else 0.6
    alpha_score = (w_mom * m_weight) + (w_vol * v_weight)

    combined = w_base * alpha_score
    if combined.sum() == 0:
        return w_base, is_bull

    w = combined / combined.sum()
    w = w.clip(upper=max_weight)
    w = w / w.sum()

    return w, is_bull


# ──────────────────────────────────────────────
# 매수 추천
# ──────────────────────────────────────────────

def buy_recommendation(
    holdings: dict[str, float],
    budget_krw: float,
    use_market_cap: bool = False,
    top_n: int = 10,
    max_weight: float = MAX_WEIGHT,
) -> dict:
    tickers = list(holdings.keys())
    data = fetch_prices(tickers, extra=["QQQ", "USDKRW=X"])

    prices_df = data["prices"].reindex(columns=tickers).ffill()
    qqq_s = data.get("QQQ", pd.Series(dtype=float))
    fx_s  = data.get("USDKRW=X", pd.Series(dtype=float))

    if prices_df.empty or qqq_s.empty:
        raise ValueError("시장 데이터를 불러오지 못했습니다.")

    fx_estimated = False
    if fx_s.empty or fx_s.dropna().empty:
        fx_rate = FX_FALLBACK
        fx_estimated = True
    else:
        fx_rate = float(fx_s.dropna().iloc[-1])

    curr_p = prices_df.iloc[-1]

    # 매수추천은 현재 시총 사용 (look-ahead 무관 -- 현재 시점 결정)
    mcap_cache = fetch_market_caps(tickers) if use_market_cap else None

    w_target, is_bull = target_weights(
        prices_df, qqq_s,
        use_market_cap=use_market_cap,
        tickers=tickers,
        max_weight=max_weight,
        mcap_cache=mcap_cache,
    )

    top_tickers = w_target.nlargest(top_n).index.tolist()
    w_final = w_target.loc[top_tickers]
    w_final = w_final / w_final.sum()

    h_series  = pd.Series(holdings).reindex(tickers).fillna(0)
    total_usd = (curr_p * h_series).sum()

    # 팩터 비중 그대로 예산 단순 배분
    buy_usd = w_final * (budget_krw / fx_rate)

    buy_krw    = buy_usd * fx_rate
    p_safe     = curr_p.reindex(top_tickers).replace(0, np.nan).fillna(1.0)
    buy_shares = buy_usd / p_safe

    return {
        "tickers":         top_tickers,
        "weights":         w_final,
        "buy_krw":         buy_krw,
        "buy_usd":         buy_usd,
        "buy_shares":      buy_shares,
        "fx_rate":         fx_rate,
        "fx_estimated":    fx_estimated,
        "is_bull":         is_bull,
        "prices":          curr_p,
        "total_value_usd": total_usd,
    }


# ──────────────────────────────────────────────
# 백테스트
# ──────────────────────────────────────────────

BENCHMARKS = {
    "QQQM": "QQQM (Nasdaq 100)",
    "XLK":  "XLK (Tech Sector)",
}


def run_backtest(
    tickers: list[str],
    weekly_budget: int = 100_000,
    benchmark_tickers: list[str] | None = None,
    period: str = "3y",
    use_market_cap: bool = True,
    progress_cb=None,
    top_n: int | None = None,
    start: str | None = None,   # ← 추가
    end: str | None = None,     # ← 추가
) -> pd.DataFrame:

    benchmark_tickers = benchmark_tickers or list(BENCHMARKS.keys())
    extra = ["QQQ", "USDKRW=X"] + benchmark_tickers

    # ← start/end 전달
    data = fetch_prices(tickers, extra=extra, period=period, start=start, end=end)
    prices    = data["prices"]
    qqq       = data.get("QQQ",      pd.Series(dtype=float))
    fx        = data.get("USDKRW=X", pd.Series(dtype=float))
    bm_prices = {bm: data.get(bm, pd.Series(dtype=float)) for bm in benchmark_tickers}

    start_idx = 252
    if len(prices) <= start_idx:
        raise ValueError("데이터가 부족합니다 (최소 252 영업일 필요).")

    # ── 시총 근사용 발행주수 1회 조회 ──────────────────────────────
    # use_market_cap=False → 균등가중 (look-ahead 완전 없음)
    # use_market_cap=True  → 발행주수 × 해당 시점 주가 (부분적 look-ahead만 잔존)
    shares_outstanding: pd.Series | None = None
    if use_market_cap:
        shares_outstanding = fetch_shares_outstanding(tickers)

    rebal_days = pd.date_range(
        start=prices.index[start_idx], end=prices.index[-1], freq="W-MON"
    )

    shares_kh = pd.Series(0.0, index=tickers)
    bm_shares = {bm: 0.0 for bm in benchmark_tickers}

    history     = []
    total_steps = len(rebal_days)

    for i, date in enumerate(rebal_days):
        if progress_cb:
            progress_cb(i + 1, total_steps)

        loc = _get_loc_safe(prices.index, date)
        if loc is None:
            continue
        curr_date = prices.index[loc]
        cp        = prices.iloc[loc]

        valid_mask = cp.notna() & (cp > 0)

        fx_loc = _get_loc_safe(fx.index, curr_date)
        if fx_loc is not None and not np.isnan(fx.iloc[fx_loc]):
            cfx = float(fx.iloc[fx_loc])
        else:
            cfx = FX_FALLBACK

        df_s  = prices.iloc[: loc + 1]
        qqq_s = qqq.loc[:curr_date]

        # ── 시총 근사: 발행주수 × 해당 시점 주가 ──────────────────
        if use_market_cap and shares_outstanding is not None:
            # 해당 시점 주가와 발행주수를 곱해 시총 근사
            cp_valid = cp.reindex(shares_outstanding.index).fillna(0)
            mcap_approx = (shares_outstanding * cp_valid)
            # 0 또는 NaN 방어
            min_val = mcap_approx[mcap_approx > 0].min()
            mcap_approx = mcap_approx.replace(0, np.nan).fillna(
                min_val if pd.notna(min_val) else 1.0
            )
            mcap_cache_bt = mcap_approx
        else:
            mcap_cache_bt = None

        w_t, _ = target_weights(
            df_s, qqq_s,
            use_market_cap=use_market_cap,
            mcap_cache=mcap_cache_bt,   # 해당 시점 근사 시총 전달
        )

        if top_n is not None:
            top_t = w_t.nlargest(top_n).index
            w_t   = w_t.loc[top_t]
            w_t   = w_t / w_t.sum()

        # 팩터 비중 그대로 주간 예산 단순 배분
        alloc_krw = w_t * weekly_budget

        for t in tickers:
            if valid_mask.get(t, False) and alloc_krw.get(t, 0) > 0:
                shares_kh[t] += (alloc_krw[t] / cfx) / float(cp[t])

        row = {
            "Date":        curr_date,
            "KH_Strategy": (shares_kh * cp.fillna(0) * cfx).sum(),
            "Invested":    (i + 1) * weekly_budget,
        }

        for bm, bm_p_series in bm_prices.items():
            bm_loc = _get_loc_safe(bm_p_series.index, curr_date)
            if bm_loc is None:
                continue
            cp_bm = float(bm_p_series.iloc[bm_loc])
            if cp_bm > 0:
                bm_shares[bm] += (weekly_budget / cfx) / cp_bm
            row[bm] = bm_shares[bm] * cp_bm * cfx

        history.append(row)

    if not history:
        raise ValueError("백테스트 결과가 없습니다. 데이터를 확인하세요.")

    df = pd.DataFrame(history).set_index("Date").ffill()
    return df