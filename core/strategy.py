"""
core/strategy.py
----------------
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import yfinance as yf
import warnings

from core.data import extract_close

warnings.filterwarnings("ignore")

MAX_WEIGHT       = 0.25   # 종목당 최대 비중
MOMENTUM_WEIGHTS = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
VOL_WINDOW       = 60     # 변동성 계산 윈도우(영업일)
MA_WINDOW        = 200    # 추세 판단 이동평균

# 팩터 가중치 (합 = 1.0)
FACTOR_ALPHA_BULL = {"base": 0.2, "momentum": 0.5, "vol": 0.3}  # 강세장
FACTOR_ALPHA_BEAR = {"base": 0.5, "momentum": 0.2, "vol": 0.3}  # 약세장


# ──────────────────────────────────────────────
#  데이터 수집
# ──────────────────────────────────────────────

def fetch_prices(
    tickers: list[str],
    extra: list[str] | None = None,
    period: str = "3y",
) -> dict[str, pd.DataFrame | pd.Series]:
    """주가 + 보조 시계열(QQQ, FX) 일괄 다운로드."""
    extra = extra or []
    all_sym = list(dict.fromkeys(tickers + extra))

    raw   = yf.download(all_sym, period=period, interval="1d",
                        auto_adjust=True, progress=False)
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
    caps = {}
    for t in tickers:
        try:
            # 주식 정보 로드 (속도 저하 방지를 위해 필요한 것만 추출)
            ticker_obj = yf.Ticker(t)
            mcap = ticker_obj.info.get("marketCap")
            caps[t] = mcap if mcap and mcap > 0 else np.nan
        except Exception:
            caps[t] = np.nan
            
    s = pd.Series(caps, dtype=float)
    # 시총 데이터 없는 종목은 해당 그룹의 최소 시총으로 채워 보수적으로 접근
    s = s.fillna(s.min() if s.min() > 0 else 1.0) 
    return s


# ──────────────────────────────────────────────
#  팩터 계산
# ──────────────────────────────────────────────

def momentum_score(df: pd.DataFrame) -> pd.Series:
    """다중 기간 순위 가중 모멘텀 점수 (0~1 정규화)."""
    score = pd.Series(0.0, index=df.columns)
    total_w = 0.0
    for days, w in MOMENTUM_WEIGHTS.items():
        if len(df) <= days:
            continue
        ret = df.pct_change(days).iloc[-1].fillna(0)
        score += w * ret.rank(pct=True)
        total_w += w
    if total_w > 0:
        score /= total_w  # 사용된 기간만큼 재정규화
    return score


def vol_inv_rank(df: pd.DataFrame, window: int = VOL_WINDOW) -> pd.Series:
    """변동성 역수 순위 (0~1 정규화)."""
    vol = df.pct_change().rolling(window).std().iloc[-1]
    inv = (1 / vol.replace(0, np.nan)).fillna(0)
    if inv.sum() == 0:
        return pd.Series(1.0 / len(df.columns), index=df.columns)
    return inv.rank(pct=True)


def base_weights(
    tickers: list[str],
    df_columns: pd.Index,
    use_market_cap: bool = False,
) -> pd.Series:
    """기본 비중: 시가총액 가중 또는 균등 가중."""
    if use_market_cap and tickers:
        mcaps = fetch_market_caps(tickers)
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
) -> tuple[pd.Series, bool]:
    
    tickers = tickers or df.columns.tolist()
    # 시장 환경 판단 (이격도 방식 등을 섞으면 더 정확하지만 일단 이동평균 유지)
    is_bull = float(qqq.iloc[-1]) > float(qqq.rolling(MA_WINDOW).mean().iloc[-1])
    
    # 1. 시총 비중 (뼈대)
    w_base = base_weights(tickers, df.columns, use_market_cap)
    
    # 2. 전략 점수 (변별력 조절)
    # 제곱수를 1.5~2.0 정도로 낮춰서 너무 극단적인 몰빵 방지
    p_mom = 2.0 if is_bull else 1.2
    p_vol = 1.5
    
    w_mom = momentum_score(df) ** p_mom
    w_vol = vol_inv_rank(df) ** p_vol

    # 3. 전략 점수 결합 (Alpha Score)
    # 강세장일수록 모멘텀에, 약세장일수록 저변동성에 가중치
    m_weight = 0.7 if is_bull else 0.4
    v_weight = 0.3 if is_bull else 0.6
    alpha_score = (w_mom * m_weight) + (w_vol * v_weight)
    
    # 4. 결합 로직: 'Tilt' 방식 (가장 안정적)
    # 시총 비중(w_base)에 전략 점수를 곱하여 비중을 재분배합니다.
    # 하위권 필터링 없이도 점수가 낮으면 자연스럽게 비중이 줄어듭니다.
    combined = w_base * alpha_score
    
    # 5. 정규화 및 상한선 적용
    if combined.sum() == 0: # 예외 처리
        return w_base, is_bull

    w = combined / combined.sum()
    
    # 특정 종목 과집중 방지 (Max Weight)
    # clip 후 다시 sum으로 나누는 과정에서 자연스럽게 나머지 종목으로 분산됨
    w = w.clip(upper=max_weight)
    w = w / w.sum()
    
    return w, is_bull


# ──────────────────────────────────────────────
#  매수 추천
# ──────────────────────────────────────────────

def buy_recommendation(
    holdings: dict[str, float],
    budget_krw: float,
    use_market_cap: bool = False,
    top_n: int = 10,
    max_weight: float = MAX_WEIGHT,
) -> dict:
    """
    현재 보유 수량 + 투자 예산을 받아 매수 추천을 반환.

    Returns dict:
        tickers, weights, buy_krw, buy_usd, buy_shares,
        fx_rate, fx_estimated, is_bull, prices, total_value_usd
    """
    tickers = list(holdings.keys())
    data = fetch_prices(tickers, extra=["QQQ", "USDKRW=X"])

    prices_df = data["prices"].reindex(columns=tickers).ffill()
    qqq_s     = data.get("QQQ", pd.Series(dtype=float))
    fx_s      = data.get("USDKRW=X", pd.Series(dtype=float))

    if prices_df.empty or qqq_s.empty:
        raise ValueError("시장 데이터를 불러오지 못했습니다.")

    # FX: 조회 실패 시 추정값 사용 + 플래그 반환
    fx_estimated = False
    if fx_s.empty or fx_s.dropna().empty:
        fx_rate      = 1_350.0
        fx_estimated = True
    else:
        fx_rate = float(fx_s.dropna().iloc[-1])

    curr_p = prices_df.iloc[-1]

    w_target, is_bull = target_weights(
        prices_df, qqq_s,
        use_market_cap=use_market_cap,
        tickers=tickers,
        max_weight=max_weight,
    )

    # Top-N 선택
    top_tickers = w_target.nlargest(top_n).index.tolist()
    w_final = w_target.loc[top_tickers]
    w_final = w_final / w_final.sum()

    # 보유 가치 계산
    h_series     = pd.Series(holdings).reindex(tickers).fillna(0)
    curr_val_usd = (curr_p * h_series).reindex(top_tickers).fillna(0)
    total_usd    = (curr_p * h_series).sum()
    curr_w       = (curr_val_usd / total_usd) if total_usd > 0 else pd.Series(0.0, index=top_tickers)

    # [수정] 부족분 비율로 예산 배분 (절대금액 기반)
    shortage_usd  = ((w_final - curr_w) * (total_usd + budget_krw / fx_rate)).clip(lower=0)
    total_shortage = shortage_usd.sum()

    if total_shortage > 0:
        buy_usd = shortage_usd / total_shortage * (budget_krw / fx_rate)
    else:
        # 모든 종목이 목표 비중 초과 → 균등 배분
        buy_usd = pd.Series(budget_krw / fx_rate / len(top_tickers), index=top_tickers)

    buy_krw    = buy_usd * fx_rate
    buy_shares = buy_usd / curr_p.reindex(top_tickers).fillna(1)

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
#  백테스트
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
    use_market_cap: bool = True,  # 인자 추가 및 기본값 True
    progress_cb=None,
) -> pd.DataFrame:
    """
    주간 적립식 백테스트.

    [수정] 예산 배분 로직:
    - 기존: buy / buy.sum() * budget  (부족분 합계 대비 비율로 배분 → 과다배분 가능)
    - 수정: (총자산 + 예산) × 목표비중 - 현재평가액 = 실제 부족분(USD) 계산 후
            부족분 비율로 KRW 예산 배분

    progress_cb: callable(current, total) -- 진행상황 콜백 (선택)

    Returns:
        DataFrame with columns: KH_Strategy, <benchmark_name>, ..., Invested
    """
    benchmark_tickers = benchmark_tickers or list(BENCHMARKS.keys())
    extra = ["QQQ", "USDKRW=X"] + benchmark_tickers

    data      = fetch_prices(tickers, extra=extra, period=period)
    prices    = data["prices"]
    qqq       = data.get("QQQ",      pd.Series(dtype=float))
    fx        = data.get("USDKRW=X", pd.Series(dtype=float))

    bm_prices = {bm: data.get(bm, pd.Series(dtype=float)) for bm in benchmark_tickers}

    start_idx = 252
    if len(prices) <= start_idx:
        raise ValueError("데이터가 부족합니다 (최소 252 영업일 필요).")

    rebal_days = pd.date_range(
        start=prices.index[start_idx], end=prices.index[-1], freq="W-MON"
    )

    shares_kh = pd.Series(0.0, index=tickers)
    bm_shares = {bm: 0.0 for bm in benchmark_tickers}
    history   = []
    total_steps = len(rebal_days)

    for i, date in enumerate(rebal_days):
        if progress_cb:
            progress_cb(i + 1, total_steps)

        curr_date = prices.index[prices.index <= date][-1]
        cp  = prices.loc[curr_date]

        # FX: 해당일 없으면 최근값 사용
        if curr_date in fx.index:
            cfx = float(fx.loc[curr_date])
        else:
            cfx_s = fx.loc[:curr_date].dropna()
            cfx = float(cfx_s.iloc[-1]) if not cfx_s.empty else 1_350.0

        # ── KH 전략 리밸런싱 ──
        df_s  = prices.loc[:curr_date]
        qqq_s = qqq.loc[:curr_date]
        w_t, _ = target_weights(df_s, qqq_s, use_market_cap=use_market_cap)

        cur_val_krw = (shares_kh * cp * cfx).sum()
        new_total   = cur_val_krw + weekly_budget       # 이번 주 예산 포함 총자산 (KRW)

        # 목표금액(KRW) - 현재금액(KRW) = 실제 부족분
        target_krw  = w_t * new_total
        cur_krw     = shares_kh * cp * cfx
        shortage    = (target_krw - cur_krw).clip(lower=0)
        total_sh    = shortage.sum()

        if total_sh > 0:
            alloc_krw = shortage / total_sh * weekly_budget
        else:
            alloc_krw = w_t * weekly_budget             # 부족분 없으면 비중대로

        shares_kh += (alloc_krw / cfx) / cp

        row = {
            "Date":        curr_date,
            "KH_Strategy": (shares_kh * cp * cfx).sum(),
            "Invested":    (i + 1) * weekly_budget,
        }

        # ── 벤치마크 적립식 매수 ──
        for bm, bm_p_series in bm_prices.items():
            if curr_date in bm_p_series.index:
                cp_bm = float(bm_p_series.loc[curr_date])
                if cp_bm > 0:
                    bm_shares[bm] += (weekly_budget / cfx) / cp_bm
            row[bm] = bm_shares[bm] * float(
                bm_prices[bm].loc[curr_date]
                if curr_date in bm_prices[bm].index
                else bm_prices[bm].dropna().iloc[-1]
            ) * cfx

        history.append(row)

    df = pd.DataFrame(history).set_index("Date").ffill()
    return df