"""
core/strategy.py

[백테스트 신뢰성 개선 내역]
1.  [FIX] Look-ahead bias: 백테스트에서 현재 시총 대신 발행주수×과거주가로 근사
2.  [FIX] CAGR → XIRR 교체 — 적립식 수익률 현실화
3.  [FIX] XIRR: fixed weekly_budget 대신 Invested 증분(실제 집행액) 사용
4.  [FIX] Invested: (i+1)*budget 고정값 → 실제 집행액 누적으로 교체 (과대계상 방지)
5.  [FIX] valid 종목만 투자 후 재정규화: 가격 없는 종목 예산이 valid 종목에 재분배
6.  [FIX] 벤치마크 투자금 = KH 실제 집행액(week_invested)으로 통일 (t=0 기준 정렬)
7.  [FIX] 워밍업 버퍼: 380일 → 420일로 확대 (휴장일 여유 30일 추가 확보)
8.  [FIX] bm_prices 슬라이스 후 ffill — 벤치마크 미래 가격 유입 차단
9.  [FIX] is_bull 판단: MA NaN(데이터 부족) → True(강세장) 안전 처리
10. [FIX] momentum_score rank NaN → 0 처리
11. [FIX] vol_inv_rank: 변동성 0/NaN → 최대 변동성으로 패널티 처리
12. [FIX] FX 매주 독립 확인, 누락 시 fallback
13. [FIX] target_weights: w_base * alpha_score (곱셈 방식) →
         가산 블렌딩 방식으로 교체하여 시총/균등 차이가 실제로 반영되도록 수정.
         (구 방식은 0~1 rank인 alpha_score가 시총 정보를 희석시켜 use_market_cap
          유무의 차이가 사라지는 버그가 있었음)
14. [유지] alloc_krw=0 / cp=0 / NaN 방어, FX fallback 1,450
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
    weekly_budget: int,
    col: str = "KH_Strategy",
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
# 팩터 계산
# ──────────────────────────────────────────────

def momentum_score(df: pd.DataFrame) -> pd.Series:
    """
    복수 룩백 가중 모멘텀 점수 (백분위 기반).
    [FIX] rank 결과 NaN → 0 처리하여 점수 오염 방지.
    """
    score   = pd.Series(0.0, index=df.columns)
    total_w = 0.0
    for days, w in MOMENTUM_WEIGHTS.items():
        if len(df) <= days:
            continue
        ret    = df.pct_change(days).iloc[-1].fillna(0)
        ranked = ret.rank(pct=True).fillna(0)   # NaN → 0
        score   += w * ranked
        total_w += w
    if total_w > 0:
        score /= total_w
    return score


def vol_inv_rank(df: pd.DataFrame, window: int = VOL_WINDOW) -> pd.Series:
    """
    변동성 역수 순위 (낮은 변동성 → 높은 점수).
    [FIX] 변동성 0/NaN → 최대 변동성으로 대체 (가장 낮은 역수 점수 부여).
    """
    vol     = df.pct_change().rolling(window).std().iloc[-1]
    vol     = vol.replace(0, np.nan)
    max_vol = vol.dropna().max()
    vol     = vol.fillna(max_vol if pd.notna(max_vol) and max_vol > 0 else 1.0)
    inv     = 1.0 / vol
    if inv.sum() == 0:
        return pd.Series(1.0 / len(df.columns), index=df.columns)
    return inv.rank(pct=True)


MCAP_GAMMA = 0.15   # 시총 팩터 반영 강도 (0 = 미반영, 최대 0.30 권장)


def target_weights(
    df: pd.DataFrame,
    qqq: pd.Series,
    use_market_cap: bool = False,
    tickers: list[str] | None = None,
    max_weight: float = MAX_WEIGHT,
    mcap_cache: pd.Series | None = None,
) -> tuple[pd.Series, bool]:
    """
    KH 전략 비중 산출.

    알고리즘 설계 철학
    ------------------
    팩터를 두 그룹으로 나눠 서로 다른 방식으로 결합합니다.

    [코어 알파 — 가중 기하평균(곱)]
        core = f_mom ^ m_w  ×  f_vol ^ v_w

        모멘텀과 변동성역수는 "둘 다 좋아야 높은 비중"이라는 논리로 곱합니다.
        하나라도 낮으면 곱이 작아져 강한 패널티가 부여됩니다.
        국면에 따라 지수(m_w / v_w)를 조절해 강세장·약세장 성격을 반영합니다.
          · Bull: m_w=0.7 v_w=0.3 → 모멘텀 주도
          · Bear: m_w=0.4 v_w=0.6 → 변동성방어 주도

    [시총 팩터 — 독립 가산(합)]
        w = core_norm × (1 - γ)  +  f_mcap_norm × γ

        시총은 "참고용 유동성 신호"로 소량(γ=15%) 더합니다.
        use_market_cap=False 이면 γ=0으로 완전히 제거됩니다.
        시총이 알파와 독립적으로 기여하므로 토글 효과가 직관적입니다.
        yfinance 실패 시에도 γ=0 fallback으로 안전하게 동작합니다.

    [단일 종목 캡]
        max_weight(기본 25%) 초과 비중은 잘라낸 뒤 재정규화합니다.
    """
    tickers = tickers or df.columns.tolist()

    # ── 시장 국면 판단 ────────────────────────────────────────────
    qqq_last = float(qqq.iloc[-1]) if len(qqq) > 0 and pd.notna(qqq.iloc[-1]) else None
    ma_val   = qqq.rolling(MA_WINDOW).mean().iloc[-1] if len(qqq) >= MA_WINDOW else np.nan

    if qqq_last is None or pd.isna(ma_val):
        is_bull = True   # 데이터 부족 → 강세장으로 안전 처리
    else:
        is_bull = qqq_last > float(ma_val)

    # ── 팩터 점수 (모두 0~1 rank로 동일 스케일) ──────────────────
    f_mom = momentum_score(df)   # 높을수록 최근 수익률 좋음
    f_vol = vol_inv_rank(df)     # 높을수록 변동성 낮음

    # ── 국면별 지수: 강세장은 모멘텀 강화, 약세장은 변동성방어 강화 ──
    m_w = 0.7 if is_bull else 0.4
    v_w = 0.3 if is_bull else 0.6

    # ── 코어 알파: 가중 기하평균(곱) ────────────────────────────
    # f_mom^m_w × f_vol^v_w → 둘 다 높아야 높은 점수
    # 0 방지: rank는 (0, 1] 범위이므로 eps 처리
    eps = 1e-8
    core = (f_mom.clip(lower=eps) ** m_w) * (f_vol.clip(lower=eps) ** v_w)
    if core.sum() == 0:
        core = pd.Series(1.0, index=df.columns)
    core_norm = core / core.sum()

    # ── 시총 팩터: rank 정규화 후 독립 가산 ──────────────────────
    gamma = MCAP_GAMMA if use_market_cap else 0.0
    if gamma > 0 and mcap_cache is not None:
        mcap_rank = mcap_cache.rank(pct=True).reindex(df.columns).fillna(0)
        mcap_norm = mcap_rank / mcap_rank.sum() if mcap_rank.sum() > 0 else mcap_rank
    else:
        gamma = 0.0
        mcap_norm = pd.Series(0.0, index=df.columns)

    # ── 최종 결합: 코어 (1-γ) + 시총 γ ─────────────────────────
    combined = (1.0 - gamma) * core_norm + gamma * mcap_norm
    if combined.sum() == 0:
        return pd.Series(1.0 / len(df.columns), index=df.columns), is_bull

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
    data    = fetch_prices(tickers, extra=["QQQ", "USDKRW=X"])

    prices_df = data["prices"].reindex(columns=tickers).ffill()
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

    curr_p     = prices_df.iloc[-1]
    mcap_ok    = True
    mcap_cache = None
    if use_market_cap:
        mcap_cache, mcap_ok = fetch_market_caps(tickers)

    w_target, is_bull = target_weights(
        prices_df, qqq_s,
        use_market_cap=use_market_cap,
        tickers=tickers,
        max_weight=max_weight,
        mcap_cache=mcap_cache,
    )

    top_tickers = w_target.nlargest(top_n).index.tolist()
    w_final     = w_target.loc[top_tickers]
    w_final     = w_final / w_final.sum()

    h_series  = pd.Series(holdings).reindex(tickers).fillna(0)
    total_usd = (curr_p * h_series).sum()

    buy_usd    = w_final * (budget_krw / fx_rate)
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
        "mcap_ok":         mcap_ok,
        "is_bull":         is_bull,
        "prices":          curr_p,
        "total_value_usd": total_usd,
    }


def rebalance_weights(
    holdings: dict[str, float],
    use_market_cap: bool = False,
    top_n: int | None = None,
    max_weight: float = MAX_WEIGHT,
) -> dict:
    tickers = list(holdings.keys())
    data    = fetch_prices(tickers, extra=["QQQ", "USDKRW=X"])

    prices_df = data["prices"].reindex(columns=tickers).ffill()
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

    curr_p     = prices_df.iloc[-1]
    mcap_ok    = True
    mcap_cache = None
    if use_market_cap:
        mcap_cache, mcap_ok = fetch_market_caps(tickers)

    w_target, is_bull = target_weights(
        prices_df, qqq_s,
        use_market_cap=use_market_cap,
        tickers=tickers,
        max_weight=max_weight,
        mcap_cache=mcap_cache,
    )

    if top_n is not None:
        top_t    = w_target.nlargest(top_n).index
        w_target = w_target.loc[top_t]
        w_target = w_target / w_target.sum()

    return {
        "weights":      w_target,
        "prices":       curr_p,
        "fx_rate":      fx_rate,
        "fx_estimated": fx_estimated,
        "mcap_ok":      mcap_ok,
        "is_bull":      is_bull,
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
    start: str | None = None,
    end: str | None = None,
    sim_start: str | None = None,
) -> pd.DataFrame:
    """
    적립식 주간 매수 백테스트.

    신뢰성 체크리스트
    -----------------
    [1] 미래 데이터 유입 차단
        - fetch는 close raw(ffill 없음) 반환
        - 루프 내 prices.iloc[:loc+1].ffill() 슬라이스 후 ffill
        - 팩터 계산(momentum, vol, MA)은 항상 curr_date 이전 데이터만 사용

    [2] 워밍업 버퍼 보장
        - sim_start 기준 420 달력일 앞에서 데이터 fetch
          (420일 ≈ 290 거래일 > 252거래일 워밍업 + 최대 30거래일 휴장 여유)
        - 실제 워밍업 거래일 수 검증 후 부족 시 명확한 에러

    [3] 실제 집행금액 = Invested (과대계상 방지)
        - valid 종목(가격 존재·양수)만 투자 대상
        - 스킵된 종목의 예산을 valid 종목에 재분배 후 재정규화
        - 실제 집행된 KRW를 누적해 Invested에 정확히 반영

    [4] KH 전략 ↔ 벤치마크 t=0 통일
        - KH가 실제 투자한 주에만 벤치마크도 동일 금액(week_invested) 투자

    [5] 벤치마크 가격 NaN 처리
        - bm_p_series도 슬라이스 후 ffill 적용
        - 가격 누락 주는 매수 스킵, 이전 평가금 유지(ffill)

    [6] FX 매주 독립 확인, 누락 시 fallback
    [7] 시총 근사: 현재 발행주수 × 해당 시점 주가 (look-ahead 최소화)
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

    # ── [7] 시총 근사용 발행주수 1회 조회 ────────────────────────
    shares_outstanding: pd.Series | None = None
    if use_market_cap:
        shares_outstanding = fetch_shares_outstanding(tickers)

    # ── 매수 일정: 시뮬 시작일부터 마지막 거래일까지 매주 월요일 ──
    rebal_days = pd.date_range(
        start=prices.index[start_idx],
        end=prices.index[-1],
        freq="W-MON",
    )

    shares_kh = pd.Series(0.0, index=tickers)
    bm_shares = {bm: 0.0 for bm in benchmark_tickers}

    total_invested_krw = 0.0   # [3] 누적 실제 집행액

    history     = []
    total_steps = len(rebal_days)

    for i, rebal_date in enumerate(rebal_days):
        if progress_cb:
            progress_cb(i + 1, total_steps)

        loc = _get_loc_safe(prices.index, rebal_date)
        if loc is None:
            continue
        curr_date = prices.index[loc]

        # [1] 슬라이스 후 ffill: 미래 가격 유입 차단
        df_s = prices.iloc[: loc + 1].ffill()
        cp   = df_s.iloc[-1]

        # [6] FX: 매주 독립 확인, 누락 시 fallback
        fx_loc = _get_loc_safe(fx_full.index, curr_date) if not fx_full.empty else None
        if fx_loc is not None:
            fx_val = fx_full.iloc[fx_loc]
            cfx    = float(fx_val) if pd.notna(fx_val) and fx_val > 0 else FX_FALLBACK
        else:
            cfx = FX_FALLBACK

        # [1] QQQ 슬라이스 후 ffill
        qqq_loc = _get_loc_safe(qqq.index, curr_date) if not qqq.empty else None
        qqq_s   = qqq.iloc[: qqq_loc + 1].ffill() if qqq_loc is not None else pd.Series(dtype=float)

        # [7] 시총 근사: 발행주수 × 해당 시점 주가
        if use_market_cap and shares_outstanding is not None:
            cp_valid    = cp.reindex(shares_outstanding.index).fillna(0)
            mcap_approx = shares_outstanding * cp_valid
            min_val     = mcap_approx[mcap_approx > 0].min()
            mcap_approx = mcap_approx.replace(0, np.nan).fillna(
                min_val if pd.notna(min_val) else 1.0
            )
            mcap_cache_bt = mcap_approx
        else:
            mcap_cache_bt = None

        # ── KH 전략 비중 계산 ─────────────────────────────────────
        w_t, _ = target_weights(
            df_s, qqq_s,
            use_market_cap=use_market_cap,
            mcap_cache=mcap_cache_bt,
        )
        if top_n is not None:
            top_t = w_t.nlargest(top_n).index
            w_t   = w_t.loc[top_t]
            w_t   = w_t / w_t.sum()

        # [3] valid 종목(가격 존재·양수)만 투자, 스킵 예산 재분배
        investable = [
            t for t in w_t.index
            if pd.notna(cp.get(t)) and float(cp.get(t, 0)) > 0
        ]
        week_invested = 0.0
        if investable:
            w_valid   = w_t.loc[investable]
            w_valid   = w_valid / w_valid.sum()   # 재정규화
            alloc_krw = w_valid * weekly_budget

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
            "KH_Strategy": portfolio_value,
            "Invested":    total_invested_krw,   # [3] 실제 집행액 누적
        }

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
            row[bm] = bm_shares[bm] * cp_bm * cfx if (pd.notna(cp_bm) and cp_bm > 0) else np.nan

        history.append(row)

    if not history:
        raise ValueError("백테스트 결과가 없습니다. 데이터를 확인하세요.")

    df = pd.DataFrame(history).set_index("Date")
    # 벤치마크 NaN(가격 누락 주)만 ffill, Invested·KH는 정확한 값이므로 그대로 유지
    bm_cols = [c for c in df.columns if c not in ("KH_Strategy", "Invested")]
    df[bm_cols] = df[bm_cols].ffill()
    return df
