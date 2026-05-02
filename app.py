"""
app.py — 개선판

[수정 사항]
1. 성과 요약: CAGR → XIRR (적립식 내부수익률)로 교체
2. 백테스트 탭에 서바이버십 바이어스 경고 문구 추가
3. 시총 가중 체크박스에 look-ahead 관련 안내 추가
4. 나머지 UI/로직은 기존 유지
"""

import json
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.portfolio import Portfolio
from core.data import fetch_prices_and_fx
from core.strategy import (
    buy_recommendation,
    run_backtest,
    calc_xirr_from_backtest,
    BENCHMARKS,
)

# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────

def safe_sum(obj) -> float:
    if isinstance(obj, pd.Series):
        return float(obj.sum())
    elif isinstance(obj, dict):
        return float(sum(obj.values()))
    try:
        return float(obj)
    except Exception:
        return 0.0


def safe_get(obj, key, default=0.0):
    try:
        if isinstance(obj, pd.Series):
            return float(obj.get(key, default))
        elif isinstance(obj, dict):
            return float(obj.get(key, default))
        return default
    except Exception:
        return default


def invalidate_cache(*keys):
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]


def fmt_xirr(v: float) -> str:
    if np.isnan(v):
        return "계산불가"
    return f"{v * 100:+.1f}%"


# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

st.set_page_config(
    page_title="Quant Portfolio Manager",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed",
)

# ─────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────

st.markdown("""
<style>
.stApp { background-color: #0f1117; color: #e0e0e0; }

.main-header {
    background: linear-gradient(135deg, #1a1f2e 0%, #16213e 100%);
    border: 1px solid #2a3a5c;
    border-radius: 12px;
    padding: 20px 28px;
    margin-bottom: 24px;
    display: flex;
    align-items: center;
    gap: 14px;
}
.main-header h1 {
    margin: 0;
    font-size: 1.6rem;
    font-weight: 700;
    color: #e8eaf6;
    letter-spacing: -0.5px;
}
.main-header p { margin: 4px 0 0 0; font-size: 0.85rem; color: #7986cb; }

.metric-card {
    background: #1a1f2e;
    border: 1px solid #2a3a5c;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
}
.metric-card .label { font-size: 0.78rem; color: #90caf9; margin-bottom: 6px; }
.metric-card .value { font-size: 1.4rem; font-weight: 700; color: #e8eaf6; }

.warn-banner {
    background: #2a1f0e;
    border: 1px solid #e67e22;
    border-radius: 8px;
    padding: 10px 16px;
    color: #f0a862;
    font-size: 0.85rem;
    margin: 8px 0;
}
.success-banner {
    background: #0e2a1a;
    border: 1px solid #27ae60;
    border-radius: 8px;
    padding: 10px 16px;
    color: #6ee89b;
    font-size: 0.85rem;
    margin: 8px 0;
}
.info-banner {
    background: #0e1a2a;
    border: 1px solid #1e88e5;
    border-radius: 8px;
    padding: 10px 16px;
    color: #90caf9;
    font-size: 0.82rem;
    margin: 8px 0;
    line-height: 1.6;
}

.section-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #90caf9;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 20px 0 8px 0;
}

.stTabs [data-baseweb="tab-list"] {
    background: #1a1f2e; border-radius: 10px; padding: 4px; gap: 4px;
}
.stTabs [data-baseweb="tab"] { border-radius: 8px; color: #90caf9; font-weight: 600; }
.stTabs [aria-selected="true"] { background: #283593 !important; color: #e8eaf6 !important; }

.stButton > button {
    background: linear-gradient(135deg, #283593, #1a237e);
    color: #ffffff !important;
    border: none; border-radius: 8px; font-weight: 600;
    padding: 8px 20px; transition: all 0.2s; width: 100%;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #3949ab, #283593);
    transform: translateY(-1px);
}

div[data-testid="column"] { display: flex !important; flex-direction: column !important; }
div[data-testid="column"]:has(.stButton)   { justify-content: flex-end !important; }
div[data-testid="column"]:has(.stCheckbox) { justify-content: center !important; }
div[data-testid="column"]:has(.stSelectbox){ justify-content: flex-end !important; }
div[data-testid="column"] > div {
    height: 100% !important; display: flex !important; flex-direction: column !important;
}
div[data-testid="column"] > div > div[data-testid="stVerticalBlock"] {
    height: 100% !important; display: flex !important;
    flex-direction: column !important; justify-content: inherit !important;
}
div[data-testid="column"]:has(.stButton) .stButton  { margin-bottom: 0 !important; }
div[data-testid="column"]:has(.stCheckbox) .stCheckbox { padding: 0 !important; margin: 0 !important; }

.stTextInput input, .stNumberInput input {
    background-color: #1e2535 !important; color: #e8eaf6 !important;
    border: 1px solid #3a4a6c !important; border-radius: 6px !important;
    caret-color: #90caf9 !important;
}
.stTextInput input::placeholder, .stNumberInput input::placeholder { color: #5c6f99 !important; }
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #5c7cfa !important;
    box-shadow: 0 0 0 2px rgba(92,124,250,0.2) !important;
}

.stSelectbox > div > div {
    background-color: #1e2535 !important; color: #e8eaf6 !important;
    border: 1px solid #3a4a6c !important; border-radius: 6px !important;
}
.stSelectbox svg { fill: #90caf9 !important; }

.stTextInput label, .stNumberInput label, .stSelectbox label,
.stCheckbox label, .stFileUploader label {
    color: #b0bec5 !important; font-size: 0.85rem !important;
}
.stCheckbox > label > div { color: #b0bec5 !important; }
.stCaption, div[data-testid="stCaptionContainer"] { color: #7986cb !important; }

[data-testid="stDataFrame"] th { background-color: #1a2340 !important; color: #90caf9 !important; }
[data-testid="stDataFrame"] td { color: #d0d8f0 !important; }
.stCode code { color: #90caf9 !important; background: #1a1f2e !important; }

.stDownloadButton > button {
    background: linear-gradient(135deg, #1b5e20, #2e7d32) !important;
    color: #ffffff !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
}

#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 세션 초기화
# ─────────────────────────────────────────────

if "portfolio" not in st.session_state:
    st.session_state.portfolio = Portfolio()

portfolio: Portfolio = st.session_state.portfolio

# ─────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────

st.markdown("""
<div class="main-header">
    <div style="font-size:2.2rem">📊</div>
    <div>
        <h1>Quant Portfolio Manager</h1>
        <p>팩터 가중 모멘텀 전략 · 백테스트 · 매수 추천</p>
    </div>
</div>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 탭
# ─────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 포트폴리오", "🧮 매수 추천", "📈 백테스트", "⚙️ 설정",
])

# ══════════════════════════════════════════════
# 탭 1 : 포트폴리오
# ══════════════════════════════════════════════

with tab1:
    st.markdown('<div class="section-label">보유 종목 관리</div>', unsafe_allow_html=True)

    col_t, col_s, col_btn1 = st.columns([2.5, 2.5, 1.5])
    with col_t:
        new_ticker = st.text_input("티커 입력", placeholder="AAPL", key="inp_ticker").upper().strip()
    with col_s:
        new_shares = st.number_input(
            "보유 수량", min_value=0.0, max_value=9_999_999.0,
            value=0.0, step=0.000001, format="%.6f", key="inp_shares",
        )
    with col_btn1:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        if st.button("➕ 추가/수정", key="btn_add"):
            if new_ticker:
                portfolio.set_holding(new_ticker, new_shares)
                portfolio.save()
                invalidate_cache("prices_data", "buy_result", "bt_result")
                st.success(f"{new_ticker} 저장 완료!")
                st.rerun()
            else:
                st.error("티커를 입력하세요.")

    tickers_list = portfolio.tickers()
    col_del_s, col_del_btn = st.columns([4, 1.5])
    with col_del_s:
        del_ticker = st.selectbox("삭제할 종목 선택", ["선택..."] + tickers_list, key="del_select")
    with col_del_btn:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        if st.button("🗑️ 삭제", key="btn_del"):
            if del_ticker != "선택...":
                portfolio.remove_holding(del_ticker)
                portfolio.save()
                invalidate_cache("prices_data", "buy_result", "bt_result")
                st.success(f"{del_ticker} 삭제 완료!")
                st.rerun()

    holdings = portfolio.holdings

    if not holdings:
        st.info("보유 종목이 없습니다. 위에서 티커와 수량을 입력해 추가하세요.")
    else:
        st.markdown('<div class="section-label">보유 종목 현황</div>', unsafe_allow_html=True)

        df_hold = pd.DataFrame(
            [(t, f"{s:.6f}", "–", "–") for t, s in holdings.items()],
            columns=["티커", "보유 수량", "현재가 (USD)", "평가금액 (KRW)"],
        )

        if st.button("🔄 시세 갱신", key="btn_refresh"):
            with st.spinner("시세 가져오는 중..."):
                try:
                    prices, fx, fx_est = fetch_prices_and_fx(portfolio.tickers())
                    st.session_state["prices_data"] = (prices, fx, fx_est)
                except Exception as e:
                    st.error(f"시세 조회 실패: {e}")

        if "prices_data" in st.session_state:
            prices, fx, fx_est = st.session_state["prices_data"]

            if fx_est:
                st.markdown(
                    '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 — 추정값 사용 중</div>',
                    unsafe_allow_html=True,
                )

            rows = []
            total_krw = 0.0
            for t, s in holdings.items():
                try:
                    p = float(prices[t])
                    price_str = f"${p:,.2f}"
                except (KeyError, TypeError, ValueError):
                    p = None
                    price_str = "N/A"

                if p is not None:
                    val = p * s * fx
                    total_krw += val
                    val_str = f"₩{val:,.0f}"
                else:
                    val_str = "N/A"
                rows.append((t, f"{s:.6f}", price_str, val_str))

            df_hold = pd.DataFrame(rows, columns=["티커", "보유 수량", "현재가 (USD)", "평가금액 (KRW)"])

            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f'<div class="metric-card"><div class="label">보유 종목 수</div>'
                f'<div class="value">{len(holdings)}개</div></div>',
                unsafe_allow_html=True,
            )
            c2.markdown(
                f'<div class="metric-card"><div class="label">총 평가금액</div>'
                f'<div class="value">₩{total_krw:,.0f}</div></div>',
                unsafe_allow_html=True,
            )
            c3.markdown(
                f'<div class="metric-card"><div class="label">USD/KRW</div>'
                f'<div class="value">{fx:,.2f}</div></div>',
                unsafe_allow_html=True,
            )
            st.write("")

        st.dataframe(df_hold, width="stretch", hide_index=True)

# ══════════════════════════════════════════════
# 탭 2 : 매수 추천
# ══════════════════════════════════════════════

with tab2:
    st.markdown('<div class="section-label">투자 설정</div>', unsafe_allow_html=True)

    col_b, col_m, col_run = st.columns([2.5, 2, 1.5])
    with col_b:
        budget = st.number_input(
            "투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
            value=portfolio.weekly_budget, step=10_000,
        )
    with col_m:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        use_mcap = st.checkbox(
            "시가총액 가중 사용", value=True,
            help="현재 시점 시총 기준으로 비중 조정. 매수추천에만 적용.",
        )
    with col_run:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_buy = st.button("▶ 매수 추천 실행", key="btn_buy")

    n_tickers = st.number_input(
        "추천 종목 수",
        min_value=1,
        max_value=len(portfolio.tickers()) if portfolio.tickers() else 20,
        value=min(10, len(portfolio.tickers())) if portfolio.tickers() else 10,
        step=1,
        help="포트폴리오 내 종목 중 상위 N개에만 이번 주 예산을 배분합니다.",
    )

    if run_buy:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            portfolio.weekly_budget = budget
            portfolio.save()
            with st.spinner("데이터 수집 중... (수십 초 소요될 수 있습니다)"):
                try:
                    res = buy_recommendation(
                        holdings=portfolio.holdings,
                        budget_krw=budget,
                        use_market_cap=use_mcap,
                        top_n=int(n_tickers),
                    )
                    st.session_state["buy_result"] = res
                except Exception as e:
                    st.error(f"오류 발생: {e}")

    if "buy_result" in st.session_state:
        res = st.session_state["buy_result"]

        tickers_r  = res["tickers"]
        weights    = res["weights"]
        buy_krw    = res["buy_krw"]
        buy_usd    = res["buy_usd"]
        buy_shares = res["buy_shares"]
        prices_r   = res["prices"]
        fx         = res["fx_rate"]
        fx_est     = res.get("fx_estimated", False)
        is_bull    = res["is_bull"]
        total_usd  = res["total_value_usd"]

        if fx_est:
            st.markdown(
                '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 — 추정값 사용</div>',
                unsafe_allow_html=True,
            )

        regime_text = "🐂 강세장 (모멘텀 강화)" if is_bull else "🐻 약세장 (방어 모드)"

        c1, c2, c3 = st.columns(3)
        c1.markdown(
            f'<div class="metric-card"><div class="label">시장 국면</div>'
            f'<div class="value" style="font-size:1rem">{regime_text}</div></div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div class="metric-card"><div class="label">환율 (USD/KRW)</div>'
            f'<div class="value">{fx:,.2f}</div></div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div class="metric-card"><div class="label">포트폴리오 총액</div>'
            f'<div class="value">${total_usd:,.0f}</div></div>',
            unsafe_allow_html=True,
        )
        st.write("")

        rows = []
        for t in tickers_r:
            try:
                p = float(prices_r[t])
                price_str = f"${p:,.2f}"
            except (KeyError, TypeError, ValueError):
                price_str = "N/A"

            rows.append({
                "티커":          t,
                "목표 비중":     f"{safe_get(weights, t):.1%}",
                "현재가 (USD)":  price_str,
                "매수금액 (KRW)": f"₩{safe_get(buy_krw, t):,.0f}",
                "매수금액 (USD)": f"${safe_get(buy_usd, t):,.2f}",
                "매수 수량":     f"{safe_get(buy_shares, t):.4f}",
            })

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        total_buy = safe_sum(buy_krw)
        st.markdown(
            f'<div class="success-banner">✅ 총 매수 금액: ₩{total_buy:,.0f}</div>',
            unsafe_allow_html=True,
        )

        pie_labels = tickers_r
        pie_values = [safe_get(weights, t) for t in tickers_r]

        fig_pie = go.Figure(go.Pie(
            labels=pie_labels, values=pie_values, hole=0.45,
            textinfo="percent", texttemplate="%{percent:.1%}",
            textposition="inside", insidetextorientation="radial",
            marker=dict(colors=[
                "#3949ab","#1e88e5","#00acc1","#43a047",
                "#fb8c00","#e53935","#8e24aa","#00897b","#f4511e","#6d4c41",
            ]),
        ))
        n = len(pie_labels)
        fig_pie.update_layout(
            title="목표 비중", paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
            font_color="#e0e0e0", margin=dict(t=40, b=10, l=10, r=10),
            height=320 + n * 20, showlegend=True,
            legend=dict(orientation="v", x=1.02, y=0.5,
                        font=dict(color="#e0e0e0", size=11), bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig_pie, width="stretch", key="pie_chart")

# ══════════════════════════════════════════════
# 탭 3 : 백테스트
# ══════════════════════════════════════════════

with tab3:
    st.markdown('<div class="section-label">백테스트 설정</div>', unsafe_allow_html=True)

    # ── 백테스트 신뢰도 안내 ──────────────────────────────────────
    st.markdown("""
<div class="info-banner">
⚠️ <b>백테스트 해석 주의사항</b><br>
① <b>생존 편향</b>: 현재 보유 중인 종목(살아남은 종목)으로만 과거를 시뮬레이션하므로 실제보다 성과가 과대평가될 수 있습니다.<br>
② <b>시가총액 근사</b>: 과거 시총은 <i>현재 발행주수 × 과거 주가</i>로 근사합니다. 자사주 매입·유상증자 등으로 인한 오차가 일부 존재합니다.<br>
③ <b>수익률 지표</b>: CAGR 대신 <b>XIRR(내부수익률)</b>을 사용합니다. 매주 나누어 투자하는 적립식 구조를 정확히 반영한 연수익률입니다.
</div>
""", unsafe_allow_html=True)

    col_p, col_m2, col_bm, col_run2 = st.columns([1.5, 1.5, 2.5, 1.5])
    with col_p:
        period_label = st.selectbox("기간", ["2년", "3년", "5년"], index=1)
        period_map   = {"2년": "2y", "3년": "3y", "5년": "5y"}
        period_str   = period_map[period_label]
    with col_m2:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        use_mcap_bt = st.checkbox(
            "시총 가중 반영", value=True,
            help="발행주수 × 해당 시점 주가로 시총을 근사합니다 (look-ahead bias 최소화).",
        )
    with col_bm:
        bm_input = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
        )
    with col_run2:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_bt = st.button("▶ 백테스트 실행", key="btn_bt")

    st.caption(f"📌 주간 투자금: ₩{portfolio.weekly_budget:,} | 보유 종목: {len(portfolio.holdings)}개")

    if run_bt:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        else:
            bm_tickers = [b.strip().upper() for b in bm_input.split(",") if b.strip()]
            portfolio.benchmarks = bm_tickers
            portfolio.save()

            # ── 고정 날짜 계산 ── ← 추가
            from datetime import date, timedelta
            period_to_days = {"2y": 730, "3y": 1095, "5y": 1825}
            end_date   = date.today().strftime("%Y-%m-%d")
            start_date = (
                date.today() - timedelta(days=period_to_days[period_str])
            ).strftime("%Y-%m-%d")

            progress_bar = st.progress(0)
            status_text  = st.empty()

            def progress_cb(cur, total):
                pct = int(cur / total * 100) if total > 0 else 0
                progress_bar.progress(pct)
                status_text.caption(f"백테스트 진행 중... ({cur}/{total} 주)")

            try:
                with st.spinner("데이터 수집 중..."):
                    df_bt = run_backtest(
                        portfolio.tickers(),
                        weekly_budget=portfolio.weekly_budget,
                        benchmark_tickers=bm_tickers,
                        period=period_str,
                        use_market_cap=use_mcap_bt,
                        progress_cb=progress_cb,
                        top_n=int(n_tickers),
                        start=start_date,   # ← 추가
                        end=end_date,       # ← 추가
                    )
                st.session_state["bt_result"] = df_bt
                progress_bar.progress(100)
                status_text.caption("✅ 완료!")
            except Exception as e:
                st.error(f"백테스트 오류: {e}")
                progress_bar.empty()
                status_text.empty()

    if "bt_result" in st.session_state:
        df_bt = st.session_state["bt_result"]

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df_bt.index, y=df_bt["Invested"], name="누적 투자금",
            fill="tozeroy", fillcolor="rgba(200,200,200,0.08)",
            line=dict(color="#cccccc", width=1, dash="dot"),
        ))
        fig.add_trace(go.Scatter(
            x=df_bt.index, y=df_bt["KH_Strategy"], name="KH 전략",
            line=dict(color="#7dd3fc", width=3),
        ))

        bm_colors = ["#f87171", "#4ade80", "#fbbf24", "#c084fc", "#34d399"]
        bm_cols   = [c for c in df_bt.columns if c not in ("KH_Strategy", "Invested")]
        for i, col in enumerate(bm_cols):
            fig.add_trace(go.Scatter(
                x=df_bt.index, y=df_bt[col],
                name=BENCHMARKS.get(col, col),
                line=dict(color=bm_colors[i % len(bm_colors)], width=2, dash="dash"),
            ))

        fig.update_layout(
            title=dict(text="포트폴리오 성과 비교", font=dict(color="#f1f5f9", size=15)),
            xaxis_title=None, yaxis_title=None,
            paper_bgcolor="#0f1117", plot_bgcolor="#1a1f2e",
            font=dict(color="#f1f5f9", size=11),
            legend=dict(
                orientation="h", yanchor="top", y=-0.18, xanchor="center", x=0.5,
                bgcolor="rgba(15,17,23,0.85)", bordercolor="#4a5568", borderwidth=1,
                font=dict(color="#f1f5f9", size=11), itemwidth=40,
            ),
            hovermode="x unified",
            hoverlabel=dict(bgcolor="#1e293b", font_color="#f1f5f9", font_size=11),
            margin=dict(t=50, b=110, l=55, r=10),
            height=520,
            yaxis=dict(
                tickformat=",.0f", gridcolor="#2d3748",
                tickfont=dict(color="#cbd5e1", size=10),
                tickprefix="₩", exponentformat="none",
            ),
            xaxis=dict(
                gridcolor="#2d3748",
                tickfont=dict(color="#cbd5e1", size=10),
                tickangle=-30,
            ),
        )
        st.plotly_chart(fig, width="stretch", key="bt_chart")

        # ── 성과 요약 (XIRR 기반) ────────────────────────────────
        st.markdown('<div class="section-label">성과 요약 (XIRR 기준)</div>', unsafe_allow_html=True)

        invested = df_bt["Invested"].iloc[-1]
        summary_rows = []
        all_cols = ["KH_Strategy"] + bm_cols

        for col in all_cols:
            final   = df_bt[col].iloc[-1]
            ret_pct = (final / invested - 1) * 100 if invested > 0 else 0.0

            # XIRR 계산
            xirr_val = calc_xirr_from_backtest(
                df_bt, portfolio.weekly_budget, col=col
            )

            running_max = df_bt[col].cummax()
            mdd = ((running_max - df_bt[col]) / running_max.replace(0, np.nan)).max() * 100

            summary_rows.append({
                "전략/벤치마크":  "✅ KH 전략" if col == "KH_Strategy" else col,
                "최종 평가금액":  f"₩{final / 1_000_000:.2f}M",
                "누적 수익률":    f"{ret_pct:+.1f}%",
                "XIRR (연수익률)": fmt_xirr(xirr_val),
                "MDD":            f"{mdd:.1f}%",
            })

        summary_rows.append({
            "전략/벤치마크":  "📌 누적 투자금",
            "최종 평가금액":  f"₩{invested / 1_000_000:.2f}M",
            "누적 수익률":    "–",
            "XIRR (연수익률)": "–",
            "MDD":            "–",
        })

        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)
        st.caption(
            f"기간: {df_bt.index[0].date()} ~ {df_bt.index[-1].date()} | "
            "XIRR = 각 투자 시점을 반영한 실질 연수익률 (적립식 표준 지표)"
        )

# ══════════════════════════════════════════════
# 탭 4 : 설정
# ══════════════════════════════════════════════

with tab4:
    st.markdown('<div class="section-label">투자 설정</div>', unsafe_allow_html=True)

    col_s1, col_s2 = st.columns(2)
    with col_s1:
        new_budget = st.number_input(
            "주간 투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
            value=portfolio.weekly_budget, step=10_000,
        )
    with col_s2:
        new_bm = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
            placeholder="QQQM, XLK, SPY",
        )

    st.markdown('<div class="section-label">저장 위치</div>', unsafe_allow_html=True)
    st.code(str(portfolio.path.resolve()), language=None)

    if st.button("💾 설정 저장", key="btn_save_settings"):
        portfolio.weekly_budget = new_budget
        bms = [b.strip().upper() for b in new_bm.split(",") if b.strip()]
        if not bms:
            st.error("벤치마크를 하나 이상 입력하세요.")
        else:
            portfolio.benchmarks = bms
            portfolio.save()
            st.success("✅ 설정이 저장되었습니다!")

    st.markdown('<div class="section-label">포트폴리오 JSON 내보내기</div>', unsafe_allow_html=True)
    if portfolio.path.exists():
        with open(portfolio.path, encoding="utf-8") as f:
            json_str = f.read()
        st.download_button(
            "⬇️ portfolio.json 다운로드",
            data=json_str, file_name="portfolio.json", mime="application/json",
        )

    st.markdown('<div class="section-label">포트폴리오 JSON 불러오기</div>', unsafe_allow_html=True)
    uploaded     = st.file_uploader("portfolio.json 업로드", type=["json"], key="json_uploader")
    last_uploaded = st.session_state.get("_last_uploaded_name")

    if uploaded is not None and uploaded.name != last_uploaded:
        try:
            raw_bytes = uploaded.read()
            if not raw_bytes:
                st.error("업로드된 파일이 비어 있습니다.")
            else:
                data = json.loads(raw_bytes.decode("utf-8"))
                if not isinstance(data, dict):
                    st.error("올바른 JSON 형식이 아닙니다 (object 타입이어야 합니다).")
                elif "holdings" not in data:
                    st.error("올바른 portfolio.json 형식이 아닙니다. holdings 키가 없습니다.")
                else:
                    portfolio._data = data
                    portfolio.save()
                    invalidate_cache("prices_data", "buy_result", "bt_result")
                    st.session_state["_last_uploaded_name"] = uploaded.name
                    st.success("✅ 포트폴리오를 불러왔습니다!")
        except json.JSONDecodeError as e:
            st.error(f"JSON 파싱 오류: {e}")
        except UnicodeDecodeError:
            st.error("파일 인코딩 오류: UTF-8 형식의 JSON 파일을 업로드하세요.")
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")