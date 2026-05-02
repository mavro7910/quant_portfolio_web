## """
core/strategy.py

변경사항:

- [BUG FIX] use_market_cap=True 시 백테스트마다 API 호출 → 시작 시 1회만 호출로 수정
- [BUG FIX] alloc_krw=0 종목에서 0나눗셈/NaN 전파 방지
- [BUG FIX] rebal_days 날짜 조회 시 빈 배열 IndexError 방어 처리
- [BUG FIX] cp(현재가) = 0 또는 NaN 종목 매수 스킵 처리
- [개선] FX 추정값 fallback을 1,350 → 1,450으로 현실화
- [개선] fetch_market_caps 예외 처리 강화
  """

from **future** import annotations

import numpy as np
import pandas as pd
import yfinance as yf
import warnings
from core.data import extract_close

warnings.filterwarnings("ignore")

MAX_WEIGHT = 0.25          # 종목당 최대 비중
MOMENTUM_WEIGHTS = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
VOL_WINDOW = 60            # 변동성 계산 윈도우(영업일)
MA_WINDOW = 200            # 추세 판단 이동평균
FX_FALLBACK = 1_450.0      # 환율 조회 실패 시 fallback (2025~2026 현실적 수준)

# 팩터 가중치 (합 = 1.0)

FACTOR_ALPHA_BULL = {"base": 0.2, "momentum": 0.5, "vol": 0.3}  # 강세장
FACTOR_ALPHA_BEAR = {"base": 0.5, "momentum": 0.2, "vol": 0.3}  # 약세장

# ──────────────────────────────────────────────

# 데이터 수집

# ──────────────────────────────────────────────

def fetch_prices(
tickers: list[str],
extra: list[str] | None = None,
period: str = "3y",
) -> dict[str, pd.DataFrame | pd.Series]:
"""주가 + 보조 시계열(QQQ, FX) 일괄 다운로드."""
extra = extra or []
all_sym = list(dict.fromkeys(tickers + extra))

```
raw = yf.download(all_sym, period=period, interval="1d",
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
```

def fetch_market_caps(tickers: list[str]) -> pd.Series:
"""시가총액 1회 조회 -- 백테스트 루프 외부에서 호출할 것."""
caps = {}
for t in tickers:
try:
info = yf.Ticker(t).info
mcap = info.get("marketCap")
caps[t] = float(mcap) if mcap and mcap > 0 else np.nan
except Exception:
caps[t] = np.nan

```
s = pd.Series(caps, dtype=float)
min_val = s.dropna().min()
s = s.fillna(min_val if (not np.isnan(min_val) and min_val > 0) else 1.0)
return s
```

def _get_loc_safe(index: pd.DatetimeIndex, date) -> int | None:
"""date 이하의 가장 최근 인덱스 위치를 반환. 없으면 None."""
mask = index <= date
if not mask.any():
return None
return int(np.where(mask)[0][-1])

# ──────────────────────────────────────────────

# 팩터 계산

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
score /= total_w
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
mcap_cache: pd.Series | None = None,
) -> pd.Series:
"""
기본 비중: 시가총액 가중 또는 균등 가중.
mcap_cache 가 주어지면 API 재호출 없이 캐시 사용.
"""
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

```
is_bull = float(qqq.iloc[-1]) > float(qqq.rolling(MA_WINDOW).mean().iloc[-1])

# 1. 시총 비중 (뼈대) -- mcap_cache 전달로 API 재호출 방지
w_base = base_weights(tickers, df.columns, use_market_cap, mcap_cache)

# 2. 전략 점수
p_mom = 2.0 if is_bull else 1.2
p_vol = 1.5
w_mom = momentum_score(df) ** p_mom
w_vol = vol_inv_rank(df) ** p_vol

# 3. Alpha Score 결합
m_weight = 0.7 if is_bull else 0.4
v_weight = 0.3 if is_bull else 0.6
alpha_score = (w_mom * m_weight) + (w_vol * v_weight)

# 4. Tilt 방식 결합
combined = w_base * alpha_score

if combined.sum() == 0:
    return w_base, is_bull

w = combined / combined.sum()

# 5. 상한선 적용
w = w.clip(upper=max_weight)
w = w / w.sum()

return w, is_bull
```

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
"""
현재 보유 수량 + 투자 예산을 받아 매수 추천을 반환.

```
Returns dict:
    tickers, weights, buy_krw, buy_usd, buy_shares,
    fx_rate, fx_estimated, is_bull, prices, total_value_usd
"""
tickers = list(holdings.keys())
data = fetch_prices(tickers, extra=["QQQ", "USDKRW=X"])

prices_df = data["prices"].reindex(columns=tickers).ffill()
qqq_s = data.get("QQQ", pd.Series(dtype=float))
fx_s = data.get("USDKRW=X", pd.Series(dtype=float))

if prices_df.empty or qqq_s.empty:
    raise ValueError("시장 데이터를 불러오지 못했습니다.")

# FX
fx_estimated = False
if fx_s.empty or fx_s.dropna().empty:
    fx_rate = FX_FALLBACK
    fx_estimated = True
else:
    fx_rate = float(fx_s.dropna().iloc[-1])

curr_p = prices_df.iloc[-1]

# 시총 1회 조회
mcap_cache = fetch_market_caps(tickers) if use_market_cap else None

w_target, is_bull = target_weights(
    prices_df, qqq_s,
    use_market_cap=use_market_cap,
    tickers=tickers,
    max_weight=max_weight,
    mcap_cache=mcap_cache,
)

# Top-N 선택
top_tickers = w_target.nlargest(top_n).index.tolist()
w_final = w_target.loc[top_tickers]
w_final = w_final / w_final.sum()

# 보유 가치 계산
h_series = pd.Series(holdings).reindex(tickers).fillna(0)
curr_val_usd = (curr_p * h_series).reindex(top_tickers).fillna(0)
total_usd = (curr_p * h_series).sum()
curr_w = (curr_val_usd / total_usd) if total_usd > 0 else pd.Series(0.0, index=top_tickers)

shortage_usd = ((w_final - curr_w) * (total_usd + budget_krw / fx_rate)).clip(lower=0)
total_shortage = shortage_usd.sum()

if total_shortage > 0:
    buy_usd = shortage_usd / total_shortage * (budget_krw / fx_rate)
else:
    buy_usd = pd.Series(budget_krw / fx_rate / len(top_tickers), index=top_tickers)

buy_krw = buy_usd * fx_rate

# 0원 배분 종목 나눗셈 방지
p_reindexed = curr_p.reindex(top_tickers)
p_safe = p_reindexed.replace(0, np.nan).fillna(1.0)
buy_shares = buy_usd / p_safe

return {
    "tickers":       top_tickers,
    "weights":       w_final,
    "buy_krw":       buy_krw,
    "buy_usd":       buy_usd,
    "buy_shares":    buy_shares,
    "fx_rate":       fx_rate,
    "fx_estimated":  fx_estimated,
    "is_bull":       is_bull,
    "prices":        curr_p,
    "total_value_usd": total_usd,
}
```

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
) -> pd.DataFrame:
"""
주간 적립식 백테스트.

```
수정 사항:
- use_market_cap=True 시 시총을 루프 시작 전 1회만 조회 (속도 대폭 개선)
- cp=0 또는 NaN 종목 매수 스킵 (NaN 전파 방지)
- rebal_days 날짜 조회 시 빈 배열 IndexError 방어
- FX fallback 값 현실화

Returns:
    DataFrame with columns: KH_Strategy, <benchmark_tickers...>, Invested
"""
benchmark_tickers = benchmark_tickers or list(BENCHMARKS.keys())
extra = ["QQQ", "USDKRW=X"] + benchmark_tickers

data = fetch_prices(tickers, extra=extra, period=period)
prices = data["prices"]
qqq   = data.get("QQQ",       pd.Series(dtype=float))
fx    = data.get("USDKRW=X",  pd.Series(dtype=float))
bm_prices = {bm: data.get(bm, pd.Series(dtype=float)) for bm in benchmark_tickers}

start_idx = 252
if len(prices) <= start_idx:
    raise ValueError("데이터가 부족합니다 (최소 252 영업일 필요).")

# ── [핵심 수정] 시총을 루프 밖에서 1회만 조회 ──
mcap_cache: pd.Series | None = None
if use_market_cap:
    mcap_cache = fetch_market_caps(tickers)

rebal_days = pd.date_range(
    start=prices.index[start_idx], end=prices.index[-1], freq="W-MON"
)

shares_kh = pd.Series(0.0, index=tickers)
bm_shares = {bm: 0.0 for bm in benchmark_tickers}

history = []
total_steps = len(rebal_days)

for i, date in enumerate(rebal_days):
    if progress_cb:
        progress_cb(i + 1, total_steps)

    # ── 날짜 안전 조회 ──
    loc = _get_loc_safe(prices.index, date)
    if loc is None:
        continue
    curr_date = prices.index[loc]
    cp = prices.iloc[loc]

    # 가격 NaN 종목 마스크 (나눗셈 방지)
    valid_mask = cp.notna() & (cp > 0)

    # ── FX: 해당일 없으면 최근값 사용 ──
    fx_loc = _get_loc_safe(fx.index, curr_date)
    if fx_loc is not None and not np.isnan(fx.iloc[fx_loc]):
        cfx = float(fx.iloc[fx_loc])
    else:
        cfx = FX_FALLBACK

    # ── KH 전략 리밸런싱 ──
    df_s  = prices.iloc[: loc + 1]
    qqq_s = qqq.loc[:curr_date]

    w_t, _ = target_weights(
        df_s, qqq_s,
        use_market_cap=use_market_cap,
        mcap_cache=mcap_cache,      # 캐시 전달 → API 재호출 없음
    )

    cur_val_krw = (shares_kh * cp.fillna(0) * cfx).sum()
    new_total   = cur_val_krw + weekly_budget

    target_krw  = w_t * new_total
    cur_krw     = shares_kh * cp.fillna(0) * cfx
    shortage    = (target_krw - cur_krw).clip(lower=0)
    total_sh    = shortage.sum()

    if total_sh > 0:
        alloc_krw = shortage / total_sh * weekly_budget
    else:
        alloc_krw = w_t * weekly_budget

    # 유효 가격 종목만 매수 (0/NaN 나눗셈 방지)
    for t in tickers:
        if valid_mask.get(t, False) and alloc_krw.get(t, 0) > 0:
            shares_kh[t] += (alloc_krw[t] / cfx) / float(cp[t])

    row = {
        "Date":        curr_date,
        "KH_Strategy": (shares_kh * cp.fillna(0) * cfx).sum(),
        "Invested":    (i + 1) * weekly_budget,
    }

    # ── 벤치마크 적립식 매수 ──
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
```