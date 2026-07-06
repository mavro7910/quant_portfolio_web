"""
core/strategy.py

[알고리즘 개선 이력]
── Academic Momentum v1 (현재) ─────────────────────────────────────
0.  [UNIVERSE] 보유종목과 자동 NYSE·Nasdaq 시총 Top 100 분리
1.  [MOMENTUM] Jegadeesh-Titman 12-1개월 모멘텀
2.  [PATH] Frog-in-the-Pan 수익경로 지속성
3.  [RISK] 낮은 잔차변동성으로 고유위험 통제
4.  [ALLOCATION] 월간 Top N 동일비중 + 부족 비중 신규 자금 배분
5.  [BACKTEST] 전일 신호/다음 거래일 체결 + 현금흐름 조정 수익률
── v3 ───────────────────────────────────────────────────────────────
1.  [REFACTOR] 팩터 정규화: rank(pct=True) → Z-score ±3σ winsorize
      · rank는 종목 간 격차를 균일 간격으로 압축 (1등/꼴등 차이 무시)
      · Z-score는 실제 수익률·변동성 격차를 반영 (AQR 실증 방식)
2.  [REFACTOR] 알파 결합: 가중 기하평균(곱) 제거 → Z-score 가중합으로 통일
      · Z-score 합산이 AQR 검증 방식이며 수학적으로 명확
      · 음수 Z-score 종목은 ReLU(clip≥0)로 자연 배제
3.  [REFACTOR] 시총 팩터 제거 (use_market_cap 파라미터 유지, 동작 없음)
      · γ=15% 근거 없음 + yfinance 불안정 → 순수 팩터 알파로 단순화
      · 향후 백테스트 검증 후 재도입 가능
── v2 ───────────────────────────────────────────────────────────────
4.  [FIX] Look-ahead bias: 발행주수×과거주가로 시총 근사
5.  [FIX] CAGR → XIRR (적립식 수익률 현실화)
6.  [FIX] Invested: 실제 집행액 누적 (과대계상 방지)
7.  [FIX] 워밍업 버퍼 420 달력일 확보
8.  [FIX] 벤치마크 미래 가격 유입 차단 (슬라이스 후 ffill)
9.  [FIX] FX 매주 독립 확인, 누락 시 fallback 1,450
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from scipy.optimize import brentq
from core.data import extract_close

warnings.filterwarnings("ignore")

MAX_WEIGHT       = 0.25
MOMENTUM_WEIGHTS = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
VOL_WINDOW       = 60
MA_WINDOW        = 200
FX_FALLBACK      = 1_450.0

# ──────────────────────────────────────────────
# 데이터 수집
# ──────────────────────────────────────────────

def fetch_prices(
    tickers: list[str],
    extra: list[str] | None = None,
    period: str = "3y",
    start: str | None = None,
    end: str | None = None,
) -> dict:
    """
    start/end를 지정하면 period는 무시됩니다.
    반환 close는 ffill 미적용 raw — 백테스트 루프에서 슬라이스 후 ffill할 것.
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

    close = extract_close(raw)   # ffill 없이 raw close

    result = {}
    available = close.columns.tolist()

    valid_tickers = [t for t in tickers if t in available]
    if not valid_tickers:
        raise ValueError(f"유효한 티커가 없습니다. available: {available}")

    result["prices"] = close[valid_tickers].copy()
    for sym in extra:
        if sym in available:
            result[sym] = close[sym]

    return result


def fetch_market_caps(tickers: list[str]) -> "tuple[pd.Series, bool]":
    """
    현재 시가총액 조회 (매수추천 전용 — 백테스트에서 사용 금지).

    전략:
    1차) yf.download로 최근 주가 + Ticker.fast_info.shares로 시총 근사
         → .info 루프 방식보다 rate limit·세션 오류에 강함
    2차) fast_info도 실패 시 .info['marketCap'] 개별 조회 (fallback)

    Returns
    -------
    (Series, ok: bool)
        ok=False → 과반 이상 조회 실패. 호출부에서 경고 표시 필요.
        ok=True  → 과반 이상 정상 조회됨.
    """
    # 1차: 최근 종가 일괄 수집
    try:
        raw = yf.download(
            tickers, period="5d",
            interval="1d", auto_adjust=True, progress=False,
        )
        close = extract_close(raw)
        last_prices = close.ffill().iloc[-1] if not close.empty else pd.Series(dtype=float)
    except Exception:
        last_prices = pd.Series(dtype=float)

    caps = {}
    for t in tickers:
        price = float(last_prices[t]) if t in last_prices.index and pd.notna(last_prices.get(t)) else None

        # fast_info 시도 (세션 1회, 가볍고 빠름)
        shares = None
        try:
            fi = yf.Ticker(t).fast_info
            shares = getattr(fi, "shares", None) or getattr(fi, "shares_outstanding", None)
            if shares and shares > 0 and price:
                caps[t] = float(shares) * price
                continue
        except Exception:
            pass

        # fallback: .info['marketCap']
        try:
            info = yf.Ticker(t).info
            mcap = info.get("marketCap")
            if mcap and mcap > 0:
                caps[t] = float(mcap)
                continue
            # .info도 실패 시 shares_outstanding × price로 근사
            sh = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            if sh and sh > 0 and price:
                caps[t] = float(sh) * price
                continue
        except Exception:
            pass

        caps[t] = np.nan

    s = pd.Series(caps, dtype=float)
    n_valid = int(s.notna().sum())
    ok = n_valid >= max(1, len(tickers) // 2)

    min_val = s.dropna().min()
    s = s.fillna(min_val if pd.notna(min_val) and min_val > 0 else 1.0)
    return s, ok


def fetch_shares_outstanding(tickers: list[str]) -> pd.Series:
    """
    발행주수 1회 조회.
    백테스트에서 '과거 주가 × 발행주수'로 시총을 근사할 때 사용.
    """
    shares = {}
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            s = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")
            shares[t] = float(s) if s and s > 0 else np.nan
        except Exception:
            shares[t] = np.nan

    sr  = pd.Series(shares, dtype=float)
    med = sr.dropna().median()
    sr  = sr.fillna(med if pd.notna(med) and med > 0 else 1.0)
    return sr


def _get_loc_safe(index: pd.DatetimeIndex, date) -> int | None:
    mask = index <= date
    if not mask.any():
        return None
    return int(np.where(mask)[0][-1])


def _get_loc_on_or_after(index: pd.DatetimeIndex, date) -> int | None:
    loc = int(index.searchsorted(pd.Timestamp(date), side="left"))
    return loc if loc < len(index) else None


# ──────────────────────────────────────────────
# XIRR
# ──────────────────────────────────────────────

def xirr(dates: list, cashflows: list[float]) -> float:
    if len(dates) != len(cashflows) or len(dates) < 2:
        return float("nan")

    t0   = dates[0]
    days = np.array([(d - t0).days for d in dates], dtype=float)

    def npv(rate: float) -> float:
        if rate <= -1.0:
            return float("inf")
        return float(np.sum(np.array(cashflows) / (1.0 + rate) ** (days / 365.25)))

    try:
        return brentq(npv, -0.9999, 1000.0, maxiter=1000)
    except (ValueError, RuntimeError):
        return float("nan")


def calc_xirr_from_backtest(
    df_bt: pd.DataFrame,
    col: str = "QPM_Alpha",
) -> float:
    """
    XIRR 계산.

    Invested 컬럼의 주간 증분을 실제 투자 현금흐름으로 사용.
    (투자 불가 주가 있을 경우 fixed weekly_budget 대신 실제 집행액 반영)
    마지막 날 평가금액을 회수 현금흐름으로 처리.
    """
    dates    = list(df_bt.index)
    invested = df_bt["Invested"].values

    # 주간 실제 투자액 = Invested 증분
    weekly_invested = np.diff(invested, prepend=0.0)

    cfs = [-float(w) for w in weekly_invested]
    cfs[-1] += float(df_bt[col].iloc[-1])   # 마지막 날 평가금 회수
    return xirr(dates, cfs)


# ──────────────────────────────────────────────
# 팩터 계산 (Z-score 기반, AQR 방식)
# ──────────────────────────────────────────────

ZSCORE_WINSORIZE = 3.0   # 극단 이상치 제한 (AQR 기준 ±3σ)

# 시총 반영 강도 프리셋
# 실험 근거: γ에 따른 Sharpe 차이 없음 → 투자 성향 선택의 문제
# MDD는 γ가 높을수록 소폭 개선 (대형주 낮은 변동성 효과)
# 집중도는 γ=30%에서 -2.6%p 완화 (소형주 모멘텀 집중 억제)
MCAP_PRESETS = {
    "factor":   0.00,   # 순수 팩터: 시총 무시, 모멘텀/변동성만
    "balanced": 0.15,   # 균형 (기본값): 팩터 85% + 시총 15%
    "mcap":     0.30,   # 시총 편향: 팩터 70% + 시총 30%
}


def _zscore(s: pd.Series, winsorize: float = ZSCORE_WINSORIZE) -> pd.Series:
    """
    시리즈를 Z-score 정규화 후 winsorize.
    표준편차 0(모든 값 동일)이면 영벡터 반환.
    """
    sig = float(s.std())
    if sig < 1e-8:
        return pd.Series(0.0, index=s.index)
    z = (s - s.mean()) / sig
    return z.clip(-winsorize, winsorize)


def _normalize_with_cap(raw: pd.Series, cap: float) -> pd.Series:
    """Normalize non-negative scores while enforcing a real position cap."""
    values = raw.clip(lower=0).fillna(0).astype(float)
    n = len(values)
    if n == 0:
        return values
    if cap <= 0 or cap * n < 1 - 1e-10:
        raise ValueError(f"비중 상한 {cap:.1%}으로 {n}개 종목을 구성할 수 없습니다.")
    if values.sum() <= 1e-12:
        values[:] = 1.0

    result = pd.Series(0.0, index=values.index)
    free = set(values.index)
    remaining = 1.0
    while free:
        free_idx = list(free)
        base = values.loc[free_idx]
        if base.sum() <= 1e-12:
            proposed = pd.Series(remaining / len(free_idx), index=free_idx)
        else:
            proposed = base / base.sum() * remaining
        capped = proposed[proposed > cap + 1e-12]
        if capped.empty:
            result.loc[free_idx] = proposed
            break
        for ticker in capped.index:
            result.loc[ticker] = cap
            remaining -= cap
            free.remove(ticker)
    return result / result.sum()


def _mcap_zscore(mcap: pd.Series, columns: pd.Index) -> pd.Series:
    """
    시총을 raw Z-score로 정규화.

    log 변환을 사용하지 않는 이유:
    AAPL $3.4T vs MU $0.1T (34배 격차)를 log 처리하면
    오히려 격차가 더 커지는 역효과가 발생 (실험 확인).
    raw Z-score가 실제 시총 분포를 더 직관적으로 반영.
    """
    mc = mcap.reindex(columns).fillna(0)
    if mc.sum() < 1e-8:
        return pd.Series(0.0, index=columns)
    return _zscore(mc)


def momentum_score(df: pd.DataFrame) -> pd.Series:
    """
    복수 룩백 가중 모멘텀 Z-score.

    각 기간의 수익률을 독립적으로 Z-score 정규화한 뒤 가중 합산합니다.
    Z-score를 쓰는 이유: rank는 종목 간 실제 수익률 격차를 균일 간격으로
    압축하지만, Z-score는 격차를 그대로 반영합니다 (AQR 실증 방식).

    NaN 처리: 기간 데이터 부족 시 해당 기간 건너뜀.
    """
    score   = pd.Series(0.0, index=df.columns)
    total_w = 0.0
    for days, w in MOMENTUM_WEIGHTS.items():
        if len(df) <= days:
            continue
        ret = df.pct_change(days).iloc[-1].fillna(0)
        score   += w * _zscore(ret)
        total_w += w
    if total_w > 0:
        score /= total_w
    return score


def vol_inv_zscore(df: pd.DataFrame, window: int = VOL_WINDOW) -> pd.Series:
    """
    변동성 역수 Z-score (낮은 변동성 → 높은 점수).

    60일 일간 수익률 표준편차의 역수를 Z-score 정규화합니다.
    NaN/0 변동성 → 최대 변동성으로 대체 (가장 낮은 역수 점수 부여).
    """
    vol = df.pct_change().rolling(window).std().iloc[-1]
    vol = vol.replace(0, np.nan)
    max_vol = vol.dropna().max()
    vol = vol.fillna(max_vol if pd.notna(max_vol) and max_vol > 0 else 1.0)
    return _zscore(1.0 / vol)


def strategy_scores(df: pd.DataFrame, qqq: pd.Series) -> tuple[pd.DataFrame, bool]:
    """Academic price-only momentum composite with auditable components.

    65%: 12-1 month cross-sectional momentum (skip the latest month)
    20%: directional return-path consistency (Frog-in-the-Pan)
    15%: low residual volatility versus QQQ
    """
    if len(df) < 253:
        raise ValueError("Academic Momentum 계산에는 최소 253거래일이 필요합니다.")
    required_rows = df.iloc[[-1, -22, -253]]
    eligible = required_rows.notna().all(axis=0)
    df = df.loc[:, eligible].ffill()
    if df.empty:
        raise ValueError("12-1개월 형성기간을 충족한 종목이 없습니다.")

    qqq_clean = qqq.dropna()
    ma = qqq_clean.rolling(MA_WINDOW).mean()
    is_bull = bool(
        len(qqq_clean) < MA_WINDOW
        or ma.empty
        or qqq_clean.iloc[-1] > ma.iloc[-1]
    )

    momentum_12_1 = df.iloc[-22] / df.iloc[-253] - 1
    momentum_rank = momentum_12_1.rank(pct=True, method="average")

    formation_returns = df.pct_change().iloc[-252:-21]
    valid_days = formation_returns.count().replace(0, np.nan)
    positive_fraction = formation_returns.gt(0).sum() / valid_days
    negative_fraction = formation_returns.lt(0).sum() / valid_days
    continuity = positive_fraction.where(momentum_12_1 >= 0, negative_fraction)
    continuity = continuity.fillna(0.5)
    continuity_rank = continuity.rank(pct=True, method="average")

    stock_returns = df.pct_change().iloc[-126:]
    market_returns = qqq_clean.pct_change().reindex(stock_returns.index).ffill()
    if market_returns.notna().sum() >= 60 and float(market_returns.var()) > 1e-12:
        centered_market = market_returns - market_returns.mean()
        centered_stocks = stock_returns.sub(stock_returns.mean())
        beta = centered_stocks.mul(centered_market, axis=0).mean() / market_returns.var()
        residual_returns = stock_returns.sub(
            market_returns.to_numpy()[:, None] * beta.to_numpy()[None, :]
        )
        residual_vol = residual_returns.std()
    else:
        residual_vol = stock_returns.std()
    low_residual_vol_rank = (-residual_vol).rank(pct=True, method="average").fillna(0.5)

    alpha = (
        0.65 * momentum_rank
        + 0.20 * continuity_rank
        + 0.15 * low_residual_vol_rank
    ).fillna(0)

    ret20 = (
        df.iloc[-1] / df.iloc[-21] - 1
        if len(df) > 21
        else pd.Series(0.0, index=df.columns)
    )
    ma50 = df.iloc[-50:].mean()
    vol20 = df.pct_change().iloc[-20:].std().replace(0, np.nan)
    distance = ((df.iloc[-1] / ma50 - 1) / (vol20 * np.sqrt(20))).replace(
        [np.inf, -np.inf], np.nan
    ).fillna(0)
    heat = (
        0.5 * ret20.rank(pct=True, method="average")
        + 0.5 * distance.rank(pct=True, method="average")
    )
    heat_state = pd.Series("정상", index=df.columns, dtype=object)
    heat_state.loc[heat >= 0.8] = "주의"
    heat_state.loc[heat >= 0.9] = "과열"

    details = pd.DataFrame({
        "momentum_12_1": momentum_12_1,
        "momentum_rank": momentum_rank,
        "continuity": continuity,
        "continuity_rank": continuity_rank,
        "residual_vol": residual_vol,
        "low_residual_vol_rank": low_residual_vol_rank,
        "alpha": alpha,
        "rank": alpha.rank(ascending=False, method="min").astype(int),
        "heat": heat,
        "heat_state": heat_state,
        "return_20d": ret20,
    }).sort_values("rank")
    return details, is_bull


def target_weights(
    df: pd.DataFrame,
    qqq: pd.Series,
    use_market_cap: bool = False,
    tickers: list[str] | None = None,
    max_weight: float = MAX_WEIGHT,
    mcap_cache: pd.Series | None = None,
    mcap_gamma: float | None = None,
) -> tuple[pd.Series, bool]:
    """Compatibility wrapper returning Academic Momentum score weights."""
    tickers = tickers or df.columns.tolist()
    details, is_bull = strategy_scores(df.reindex(columns=tickers), qqq)
    raw = details["alpha"].clip(lower=0)
    w = _normalize_with_cap(raw, max_weight)
    return w, is_bull


# ──────────────────────────────────────────────
# 매수 추천
# ──────────────────────────────────────────────

def buy_recommendation(
    holdings: dict[str, float],
    budget_krw: float,
    mcap_preset: str = "balanced",
    top_n: int = 10,
    max_weight: float = MAX_WEIGHT,
    universe_tickers: list[str] | None = None,
    locked_selection: list[str] | None = None,
) -> dict:
    """Build a weekly plan from an independent universe and current shortfalls."""
    if universe_tickers is None:
        from core.universe import get_universe
        universe_tickers = list(get_universe().tickers)
    universe_tickers = list(dict.fromkeys(t.upper() for t in universe_tickers))
    held_tickers = list(holdings.keys())
    fetch_tickers = list(dict.fromkeys(universe_tickers + held_tickers))
    data = fetch_prices(fetch_tickers, extra=["QQQ", "USDKRW=X"])

    all_prices = data["prices"].reindex(columns=fetch_tickers).ffill()
    valid_universe = [
        ticker for ticker in universe_tickers
        if ticker in all_prices.columns and all_prices[ticker].notna().sum() >= 253
    ]
    prices_df = all_prices[valid_universe]
    qqq_s     = data.get("QQQ",      pd.Series(dtype=float))
    fx_s      = data.get("USDKRW=X", pd.Series(dtype=float))

    if prices_df.empty or qqq_s.empty:
        raise ValueError("시장 데이터를 불러오지 못했습니다.")

    fx_estimated = False
    if fx_s.empty or fx_s.dropna().empty:
        fx_rate      = FX_FALLBACK
        fx_estimated = True
    else:
        fx_rate = float(fx_s.dropna().iloc[-1])

    curr_p = all_prices.iloc[-1]
    details, is_bull = strategy_scores(prices_df, qqq_s)
    ranked = details.index.tolist()
    selected = [
        t for t in (locked_selection or [])
        if t in details.index
    ][:top_n]
    selected.extend(t for t in ranked if t not in selected)
    top_tickers = selected[:min(top_n, len(selected))]
    if not top_tickers:
        raise ValueError("선정 가능한 유니버스 종목이 없습니다.")

    # Academic winner portfolios are equal-weighted.  It also avoids unstable
    # score-to-weight optimization from a 100-name cross-section.
    w_final = pd.Series(1.0 / len(top_tickers), index=top_tickers)

    h_series = pd.Series(holdings, dtype=float)
    held_prices = curr_p.reindex(h_series.index).fillna(0)
    current_values = h_series * held_prices
    total_usd = float(current_values.sum())
    budget_usd = budget_krw / fx_rate
    desired_values = w_final * (total_usd + budget_usd)
    selected_values = current_values.reindex(top_tickers).fillna(0)
    gaps = (desired_values - selected_values).clip(lower=0)
    allocation_basis = gaps if gaps.sum() > 1e-8 else w_final
    buy_usd = allocation_basis / allocation_basis.sum() * budget_usd
    buy_krw    = buy_usd * fx_rate
    p_safe     = curr_p.reindex(top_tickers).replace(0, np.nan).fillna(1.0)
    buy_shares = buy_usd / p_safe

    return {
        "tickers":         top_tickers,
        "weights":         w_final,
        "buy_krw":         buy_krw,
        "buy_usd":         buy_usd,
        "buy_shares":      buy_shares,
        "budget_krw":      float(budget_krw),
        "fx_rate":         fx_rate,
        "fx_estimated":    fx_estimated,
        "mcap_ok":         True,
        "mcap_preset":     "universe",
        "mcap_gamma":      0.0,
        "is_bull":         is_bull,
        "prices":          curr_p,
        "total_value_usd": total_usd,
        "current_weights": (
            current_values.reindex(top_tickers).fillna(0) / total_usd
            if total_usd > 0 else pd.Series(0.0, index=top_tickers)
        ),
        "shortfall_usd":    gaps,
        "scores":           details,
        "universe_size":    len(valid_universe),
        "selection_locked": bool(locked_selection),
    }


def rebalance_weights(
    holdings: dict[str, float],
    mcap_preset: str = "balanced",
    top_n: int | None = None,
    max_weight: float = MAX_WEIGHT,
    universe_tickers: list[str] | None = None,
    locked_selection: list[str] | None = None,
) -> dict:
    n = top_n or 10
    plan = buy_recommendation(
        holdings=holdings,
        budget_krw=0,
        top_n=n,
        max_weight=max_weight,
        universe_tickers=universe_tickers,
        locked_selection=locked_selection,
    )
    return {
        "weights": plan["weights"],
        "prices": plan["prices"],
        "fx_rate": plan["fx_rate"],
        "fx_estimated": plan["fx_estimated"],
        "mcap_ok": True,
        "mcap_preset": "universe",
        "mcap_gamma": 0.0,
        "is_bull": plan["is_bull"],
        "scores": plan["scores"],
        "universe_size": plan["universe_size"],
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
    mcap_preset: str = "factor",
    progress_cb=None,
    top_n: int | None = None,
    start: str | None = None,
    end: str | None = None,
    sim_start: str | None = None,
) -> pd.DataFrame:
    """
    적립식 주간 매수 백테스트.

    mcap_preset은 이전 호출부 호환용이며 Academic Momentum에서는 사용하지 않습니다.

    신뢰성 체크리스트
    -----------------
    [1] 미래 데이터 유입 차단
        - fetch는 close raw(ffill 없음) 반환
        - 신호는 prices.iloc[:loc], 체결가는 prices.iloc[loc]로 분리
        - 팩터 계산(momentum, vol, MA)은 항상 체결일 이전 데이터만 사용

    [2] 워밍업 버퍼 보장
        - sim_start 기준 420 달력일 앞에서 데이터 fetch
          (420일 ≈ 290 거래일 > 252거래일 워밍업 + 최대 30거래일 휴장 여유)
        - 실제 워밍업 거래일 수 검증 후 부족 시 명확한 에러

    [3] 실제 집행금액 = Invested (과대계상 방지)
        - valid 종목(가격 존재·양수)만 투자 대상
        - 스킵된 종목의 예산을 valid 종목에 재분배 후 재정규화
        - 실제 집행된 KRW를 누적해 Invested에 정확히 반영

    [4] QPM Alpha ↔ 벤치마크 t=0 통일
        - KH가 실제 투자한 주에만 벤치마크도 동일 금액(week_invested) 투자

    [5] 벤치마크 가격 NaN 처리
        - bm_p_series도 슬라이스 후 ffill 적용
        - 가격 누락 주는 매수 스킵, 이전 평가금 유지(ffill)

    [6] FX 매주 독립 확인, 누락 시 fallback
    """
    benchmark_tickers = benchmark_tickers or list(BENCHMARKS.keys())
    extra = ["QQQ", "USDKRW=X"] + benchmark_tickers

    # ── [2] 워밍업 버퍼: sim_start 기준 420 달력일 앞에서 fetch ──
    if sim_start:
        _sim_ts     = pd.Timestamp(sim_start)
        fetch_start = (_sim_ts - pd.DateOffset(days=420)).strftime("%Y-%m-%d")
    else:
        fetch_start = start  # None이면 period 사용

    data = fetch_prices(
        tickers, extra=extra,
        period=period,
        start=fetch_start,
        end=end,
    )

    # [1] raw close (ffill 미적용) — 루프 내 슬라이스 후 ffill
    prices    = data["prices"]
    qqq       = data.get("QQQ",      pd.Series(dtype=float))
    fx_full   = data.get("USDKRW=X", pd.Series(dtype=float))
    bm_prices = {bm: data.get(bm, pd.Series(dtype=float)) for bm in benchmark_tickers}

    # ── 시뮬 시작 인덱스 결정 ────────────────────────────────────
    if sim_start:
        _sim_ts        = pd.Timestamp(sim_start)
        sim_start_iloc = int(prices.index.searchsorted(_sim_ts, side="left"))
        start_idx      = sim_start_iloc
    else:
        start_idx = 252

    # [2] 워밍업 거래일 수 검증
    if start_idx < 252:
        raise ValueError(
            f"워밍업 데이터 부족: {start_idx}거래일 확보 (최소 252일 필요).\n"
            f"시뮬레이션 시작일({sim_start})을 최소 1년 더 앞으로 설정하거나, "
            "'2년' 이상의 기간을 선택하세요."
        )
    if len(prices) <= start_idx:
        raise ValueError(
            f"전체 데이터({len(prices)}일)가 시뮬 시작 인덱스({start_idx})보다 적습니다."
        )

    # ── 매수 일정: 시뮬 시작일부터 마지막 거래일까지 매주 월요일 ──
    rebal_days = pd.date_range(
        start=prices.index[start_idx],
        end=prices.index[-1],
        freq="W-MON",
    )

    shares_kh = pd.Series(0.0, index=tickers)
    bm_shares = {bm: 0.0 for bm in benchmark_tickers}

    total_invested_krw = 0.0   # [3] 누적 실제 집행액
    previous_value: float | None = None
    previous_bm_values: dict[str, float | None] = {
        bm: None for bm in benchmark_tickers
    }

    history     = []
    total_steps = len(rebal_days)
    locked_top: list[str] = []
    selection_month: tuple[int, int] | None = None

    for i, rebal_date in enumerate(rebal_days):
        if progress_cb:
            progress_cb(i + 1, total_steps)

        loc = _get_loc_on_or_after(prices.index, rebal_date)
        if loc is None:
            continue
        curr_date = prices.index[loc]

        if loc < 1:
            continue
        # [1] 전일 종가까지 신호 계산, 당일 종가로 체결
        df_s = prices.iloc[:loc].ffill()
        cp = prices.iloc[: loc + 1].ffill().iloc[-1]

        # [6] FX: 매주 독립 확인, 누락 시 fallback
        fx_loc = _get_loc_safe(fx_full.index, curr_date) if not fx_full.empty else None
        if fx_loc is not None:
            fx_val = fx_full.iloc[fx_loc]
            cfx    = float(fx_val) if pd.notna(fx_val) and fx_val > 0 else FX_FALLBACK
        else:
            cfx = FX_FALLBACK

        # [1] QQQ 슬라이스 후 ffill
        qqq_s = qqq.loc[qqq.index < curr_date].ffill() if not qqq.empty else pd.Series(dtype=float)

        # ── QPM Alpha 비중 계산 ─────────────────────────────────────
        w_t, _ = target_weights(df_s, qqq_s)
        month_key = (curr_date.year, curr_date.month)
        new_selection_month = month_key != selection_month
        if top_n is not None:
            if new_selection_month or not locked_top:
                locked_top = w_t.nlargest(top_n).index.tolist()
                selection_month = month_key
            w_t = pd.Series(1 / len(locked_top), index=locked_top)
        elif new_selection_month:
            selection_month = month_key

        # 월 첫 실행일에 실제 보유 비중도 목표로 되돌린다.
        # 작은 편차는 실전 UI의 기본 3% 허용밴드 안에서 유지한다.
        if new_selection_month and len(history) > 0:
            current_values = shares_kh * cp.reindex(tickers).fillna(0) * cfx
            nav_before = float(current_values.sum())
            if nav_before > 0:
                target_all = pd.Series(0.0, index=tickers)
                target_all.loc[w_t.index] = w_t
                current_weights = current_values / nav_before
                trade_mask = (
                    (target_all == 0) & (current_values > 0)
                ) | ((target_all - current_weights).abs() >= 0.03)
                desired_values = current_values.copy()
                desired_values.loc[trade_mask] = target_all.loc[trade_mask] * nav_before
                active = target_all.index[trade_mask & (target_all > 0)]
                fixed_total = float(desired_values.loc[~trade_mask].sum())
                active_budget = max(nav_before - fixed_total, 0)
                if len(active) and target_all.loc[active].sum() > 0:
                    desired_values.loc[active] = (
                        target_all.loc[active] / target_all.loc[active].sum()
                        * active_budget
                    )
                shares_kh = (
                    desired_values
                    / (cp.reindex(tickers).fillna(0) * cfx).replace(0, np.nan)
                ).fillna(0)

        # [3] valid 종목(가격 존재·양수)만 투자, 스킵 예산 재분배
        investable = [
            t for t in w_t.index
            if pd.notna(cp.get(t)) and float(cp.get(t, 0)) > 0
        ]
        week_invested = 0.0
        if investable:
            w_valid = w_t.loc[investable]
            w_valid = w_valid / w_valid.sum()
            current_values = (
                shares_kh.loc[investable] * cp.loc[investable] * cfx
            )
            current_total = float((shares_kh * cp.reindex(tickers).fillna(0)).sum() * cfx)
            desired_values = w_valid * (current_total + weekly_budget)
            shortfalls = (desired_values - current_values).clip(lower=0)
            allocation_basis = shortfalls if shortfalls.sum() > 1e-8 else w_valid
            alloc_krw = allocation_basis / allocation_basis.sum() * weekly_budget

            for t in investable:
                price_usd     = float(cp[t])
                buy_krw_t     = float(alloc_krw[t])
                shares_kh[t] += (buy_krw_t / cfx) / price_usd
                week_invested += buy_krw_t

            total_invested_krw += week_invested
        # investable이 비어 있으면 이 주는 투자 스킵 (Invested 미증가)

        # ── 포트폴리오 평가금액 ───────────────────────────────────
        portfolio_value = float((shares_kh * cp.fillna(0)).sum() * cfx)
        row = {
            "Date":        curr_date,
            "QPM_Alpha": portfolio_value,
            "Invested":    total_invested_krw,   # [3] 실제 집행액 누적
            "QPM_Return": (
                (portfolio_value - week_invested) / previous_value - 1
                if previous_value is not None and previous_value > 0
                else np.nan
            ),
        }
        previous_value = portfolio_value

        # [4][5] 벤치마크: KH가 투자한 주에만 동일 금액 투자, 슬라이스 후 ffill
        for bm, bm_p_raw in bm_prices.items():
            if bm_p_raw.empty:
                row[bm] = np.nan
                continue
            bm_loc = _get_loc_safe(bm_p_raw.index, curr_date)
            if bm_loc is None:
                row[bm] = np.nan
                continue
            # [5] 벤치마크도 슬라이스 후 ffill
            cp_bm_s = bm_p_raw.iloc[: bm_loc + 1].ffill()
            cp_bm   = float(cp_bm_s.iloc[-1]) if not cp_bm_s.empty else np.nan

            if pd.notna(cp_bm) and cp_bm > 0 and week_invested > 0:
                # [4] KH 실제 집행액과 동일 금액으로 매수
                bm_shares[bm] += (week_invested / cfx) / cp_bm
            bm_value = bm_shares[bm] * cp_bm * cfx if (pd.notna(cp_bm) and cp_bm > 0) else np.nan
            row[bm] = bm_value
            prev_bm = previous_bm_values[bm]
            row[f"{bm}_Return"] = (
                (bm_value - week_invested) / prev_bm - 1
                if prev_bm is not None and prev_bm > 0 and pd.notna(bm_value)
                else np.nan
            )
            previous_bm_values[bm] = bm_value if pd.notna(bm_value) else prev_bm

        history.append(row)

    if not history:
        raise ValueError("백테스트 결과가 없습니다. 데이터를 확인하세요.")

    df = pd.DataFrame(history).set_index("Date")
    # 벤치마크 NaN(가격 누락 주)만 ffill, Invested·KH는 정확한 값이므로 그대로 유지
    bm_cols = [
        c for c in df.columns
        if c not in ("QPM_Alpha", "Invested", "QPM_Return")
        and not c.endswith("_Return")
    ]
    df[bm_cols] = df[bm_cols].ffill()
    return df
