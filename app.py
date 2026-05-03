"""
app.py -- Google Auth 적용판

[수정 사항]
- UUID/URL 파라미터 기반 사용자 구분 → Streamlit 공식 Google OAuth (st.user) 로 교체
- 데이터 저장 경로: portfolio_{uid}.json → portfolio_{email_hash}.json (이메일 기반 고정)
- 로그인/로그아웃 버튼 헤더에 추가
- 나머지 UI/로직은 기존 유지
"""

import json
import sys
import os
import hashlib
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

from PIL import Image

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


def email_to_filename(email: str) -> str:
    """이메일을 파일명에 안전한 해시로 변환"""
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

_icon = Image.open(Path(__file__).parent / "assets" / "icon.png")
_icon = _icon.resize((64, 64))

st.set_page_config(
    page_title="Quant Portfolio Manager",
    page_icon=_icon,
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
# 🔐 Google 로그인 게이트
# ─────────────────────────────────────────────

if not st.user.is_logged_in:
    st.markdown("""
    <div class="main-header">
        <div style="font-size:2.2rem">📊</div>
        <div>
            <h1>Quant Portfolio Manager</h1>
            <p>팩터 가중 모멘텀 전략 · 백테스트 · 매수 추천</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

    st.markdown("""
    <div class="info-banner">
        🔐 <b>로그인이 필요합니다</b><br>
        Google 계정으로 로그인하면 어떤 기기에서든 동일한 포트폴리오 데이터를 사용할 수 있습니다.
    </div>
    """, unsafe_allow_html=True)

    col_login, col_empty = st.columns([1, 3])
    with col_login:
        if st.button("🔑 Google로 로그인", key="btn_login"):
            st.login()
    st.stop()


# ─────────────────────────────────────────────
# 로그인 성공 → 사용자 정보로 포트폴리오 로드
# ─────────────────────────────────────────────

_user_email = st.user.email or st.user.get("sub", "unknown")
_user_name  = st.user.get("name", _user_email)
_file_key   = email_to_filename(_user_email)

# 사용자가 바뀌었을 때만 포트폴리오 재로드
if "portfolio" not in st.session_state or st.session_state.get("_user_email") != _user_email:
    data_path = Path(__file__).parent / "data" / f"portfolio_{_file_key}.json"
    st.session_state.portfolio = Portfolio(path=data_path)
    st.session_state["_user_email"] = _user_email
    # 사용자 전환 시 캐시 초기화
    invalidate_cache("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result")

portfolio: Portfolio = st.session_state.portfolio


# ─────────────────────────────────────────────
# 헤더 (로그인 정보 + 로그아웃 버튼 포함)
# ─────────────────────────────────────────────

col_header, col_user = st.columns([5, 1])

with col_header:
    st.markdown("""
    <div class="main-header">
        <div style="font-size:2.2rem">📊</div>
        <div>
            <h1>Quant Portfolio Manager</h1>
            <p>팩터 가중 모멘텀 전략 · 백테스트 · 매수 추천</p>
        </div>
    </div>
    """, unsafe_allow_html=True)

with col_user:
    st.markdown(f"""
    <div style="text-align:right; padding-top:8px; font-size:0.82rem; color:#90caf9;">
        👤 {_user_name}<br>
        <span style="font-size:0.75rem; color:#5c6f99;">{_user_email}</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("로그아웃", key="btn_logout"):
        st.logout()


# ─────────────────────────────────────────────
# 탭
# ─────────────────────────────────────────────

tab1, tab2, tab3, tab6, tab4, tab5 = st.tabs([
    "📋 포트폴리오", "🧮 매수 추천", "📈 백테스트", "🚨 매도 신호", "⚖️ 리밸런싱", "⚙️ 설정",
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

        prices_cache = st.session_state.get("prices_data", None)
        fx = prices_cache[1] if prices_cache else None
        prices_map = prices_cache[0] if prices_cache else None
        fx_est = prices_cache[2] if prices_cache else False

        def build_df_hold(holdings_dict, prices_map, fx):
            rows = []
            for t, s in holdings_dict.items():
                p = None
                val = None
                if prices_map is not None:
                    try:
                        p = float(prices_map[t])
                        val = p * s * fx
                    except (KeyError, TypeError, ValueError):
                        p = None
                rows.append({"티커": t, "보유 수량": s, "현재가 (USD)": p, "평가금액 (KRW)": val})
            return pd.DataFrame(rows)

        df_hold = build_df_hold(holdings, prices_map, fx)

        hold_col_cfg = {
            "현재가 (USD)": st.column_config.NumberColumn(format="$%.2f"),
            "평가금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "보유 수량": st.column_config.NumberColumn(format="%.6f"),
        }

        col_btn_ref, col_btn_name = st.columns([1, 1])
        with col_btn_ref:
            if st.button("🔄 시세 갱신", key="btn_refresh"):
                with st.spinner("시세 가져오는 중..."):
                    try:
                        prices, fx_new, fx_est_new = fetch_prices_and_fx(portfolio.tickers())
                        st.session_state["prices_data"] = (prices, fx_new, fx_est_new)
                        st.rerun()
                    except Exception as e:
                        st.error(f"시세 조회 실패: {e}")
        with col_btn_name:
            if st.button("🔍 종목명 조회", key="btn_names"):
                with st.spinner("종목명 가져오는 중..."):
                    import yfinance as yf
                    names = {}
                    for t in portfolio.tickers():
                        try:
                            info = yf.Ticker(t).info
                            names[t] = info.get("longName") or info.get("shortName") or t
                        except Exception:
                            names[t] = t
                    st.session_state["ticker_names"] = names

        if fx_est:
            st.markdown(
                '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 -- 추정값 사용 중</div>',
                unsafe_allow_html=True,
            )

        if prices_map is not None:
            total_krw = df_hold["평가금액 (KRW)"].sum()
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

        if "ticker_names" in st.session_state:
            names_map = st.session_state["ticker_names"]
            df_hold.insert(1, "종목명", df_hold["티커"].map(names_map))

        edited_df = st.data_editor(
            df_hold,
            column_config=hold_col_cfg,
            disabled=[c for c in df_hold.columns if c != "보유 수량"],
            width='stretch',
            hide_index=True,
            key="hold_editor",
        )

        for _, row in edited_df.iterrows():
            t = row["티커"]
            new_shares = float(row["보유 수량"])
            if abs(new_shares - holdings.get(t, 0.0)) > 1e-9:
                portfolio.set_holding(t, new_shares)
                portfolio.save()
                invalidate_cache("buy_result", "bt_result", "rebal_result")
                if prices_map is not None:
                    try:
                        p = float(prices_map[t])
                        st.session_state["_recalc"] = True
                    except Exception:
                        pass
                st.rerun()

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
                '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 -- 추정값 사용</div>',
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
            except (KeyError, TypeError, ValueError):
                p = None

            rows.append({
                "티커":           t,
                "목표 비중 (%)":  safe_get(weights, t) * 100,
                "현재가 (USD)":   p,
                "매수금액 (KRW)": safe_get(buy_krw, t),
                "매수금액 (USD)": safe_get(buy_usd, t),
                "매수 수량":      safe_get(buy_shares, t),
            })

        buy_col_cfg = {
            "목표 비중 (%)":  st.column_config.NumberColumn(format="%.1f%%"),
            "현재가 (USD)":   st.column_config.NumberColumn(format="$%.2f"),
            "매수금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "매수금액 (USD)": st.column_config.NumberColumn(format="$%.2f"),
            "매수 수량":      st.column_config.NumberColumn(format="%.4f"),
        }
        st.dataframe(pd.DataFrame(rows), column_config=buy_col_cfg, width="stretch", hide_index=True)

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

    with st.expander("📖 KH 전략이란? (클릭하여 펼치기)", expanded=False):
        st.markdown("""
<div class="info-banner">
<b>🔬 KH 전략 작동 방식</b><br><br>

<b>① 시장 국면 판단 (Bull / Bear)</b><br>
QQQ(나스닥 100 ETF)의 현재가가 200일 이동평균선 위에 있으면 <b>강세장(Bull)</b>, 아래면 <b>약세장(Bear)</b>으로 판단합니다.<br><br>

<b>② 팩터 점수 계산</b><br>
· <b>모멘텀 점수</b>: 21일(10%) · 63일(20%) · 126일(30%) · 252일(40%) 수익률의 가중 순위 — 최근 수익률이 높은 종목에 높은 점수<br>
· <b>변동성 역수 점수</b>: 60일 변동성이 낮을수록 높은 점수 — 안정적인 종목 선호<br><br>

<b>③ 국면별 팩터 배합</b><br>
· 강세장: 모멘텀 70% + 변동성역수 30% → 공격적 배분<br>
· 약세장: 모멘텀 40% + 변동성역수 60% → 방어적 배분<br><br>

<b>④ 기본 비중 × 팩터 점수</b><br>
시가총액 가중(옵션)을 기본 비중으로 사용하고, 팩터 점수를 곱해 최종 비중을 산출합니다. 단일 종목 최대 비중은 <b>25%</b>로 제한됩니다.<br><br>

<b>⑤ 매주 적립식 매수 시뮬레이션</b><br>
매주 월요일 주간 예산을 위 비중대로 상위 N개 종목에 분할 매수하여 누적 포트폴리오 가치를 계산합니다.
</div>
""", unsafe_allow_html=True)

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

    st.caption(f"📌 주간 투자금: ₩{portfolio.weekly_budget:,} | 등록 종목: {len(portfolio.holdings)}개 | 매수 집중 Top N: {int(n_tickers)}개")

    if run_bt:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        else:
            bm_tickers = [b.strip().upper() for b in bm_input.split(",") if b.strip()]
            portfolio.benchmarks = bm_tickers
            portfolio.save()

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
                        start=start_date,
                        end=end_date,
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

        st.markdown('<div class="section-label">성과 요약 (XIRR 기준)</div>', unsafe_allow_html=True)

        invested = df_bt["Invested"].iloc[-1]
        summary_rows = []
        all_cols = ["KH_Strategy"] + bm_cols

        for col in all_cols:
            final   = df_bt[col].iloc[-1]
            ret_pct = (final / invested - 1) * 100 if invested > 0 else 0.0

            xirr_val = calc_xirr_from_backtest(
                df_bt, portfolio.weekly_budget, col=col
            )
            xirr_pct = xirr_val * 100 if not np.isnan(xirr_val) else None

            running_max = df_bt[col].cummax()
            mdd = ((running_max - df_bt[col]) / running_max.replace(0, np.nan)).max() * 100

            summary_rows.append({
                "전략/벤치마크":   "✅ KH 전략" if col == "KH_Strategy" else col,
                "최종 평가금액 (M원)": final / 1_000_000,
                "누적 수익률 (%)":  ret_pct,
                "XIRR (%)":        xirr_pct,
                "MDD (%)":         mdd,
            })

        summary_rows.append({
            "전략/벤치마크":   "📌 누적 투자금",
            "최종 평가금액 (M원)": invested / 1_000_000,
            "누적 수익률 (%)":  None,
            "XIRR (%)":        None,
            "MDD (%)":         None,
        })

        bt_col_cfg = {
            "최종 평가금액 (M원)": st.column_config.NumberColumn(format="₩%.2fM"),
            "누적 수익률 (%)":     st.column_config.NumberColumn(format="%+.1f%%"),
            "XIRR (%)":           st.column_config.NumberColumn(format="%+.1f%%", help="계산불가 시 빈칸"),
            "MDD (%)":            st.column_config.NumberColumn(format="%.1f%%"),
        }
        st.dataframe(pd.DataFrame(summary_rows), column_config=bt_col_cfg, width="stretch", hide_index=True)
        st.caption(
            f"기간: {df_bt.index[0].date()} ~ {df_bt.index[-1].date()} | "
            "XIRR = 각 투자 시점을 반영한 실질 연수익률 (적립식 표준 지표)"
        )

# ══════════════════════════════════════════════
# 탭 4 : 리밸런싱
# ══════════════════════════════════════════════

with tab4:
    st.markdown('<div class="section-label">리밸런싱 계산기</div>', unsafe_allow_html=True)

    st.markdown("""
<div class="info-banner">
📅 <b>리밸런싱이란?</b><br>
시간이 지나면 종목별 수익률 차이로 인해 실제 비중이 목표 비중에서 벗어납니다. 반기 또는 분기마다 초과 상승한 종목을 일부 매도하고 비중이 낮아진 종목을 매수하여 목표 비중으로 되돌리는 작업입니다.<br><br>
아래에서 현재 시세를 불러온 뒤 <b>알고리즘 목표 비중 대비 초과/부족 수량</b>을 확인하세요.
</div>
""", unsafe_allow_html=True)

    if not portfolio.tickers():
        st.info("포트폴리오 탭에서 종목을 먼저 추가하세요.")
    else:
        col_rb1, col_rb2, col_rb3 = st.columns([1.5, 1.5, 1.5])
        with col_rb1:
            rb_use_mcap = st.checkbox(
                "시가총액 가중 사용", value=True,
                help="목표 비중 계산 시 시가총액 가중 사용 여부. 매수 추천과 동일한 설정을 권장합니다.",
                key="rb_mcap",
            )
        with col_rb2:
            rb_top_n = st.number_input(
                "비중 산출 종목 수 (Top N)",
                min_value=1,
                max_value=len(portfolio.tickers()),
                value=min(10, len(portfolio.tickers())),
                step=1,
                help="목표 비중을 상위 N개 종목에만 배분합니다. 매수 추천 탭과 동일한 값을 사용하세요.",
                key="rb_topn",
            )
        with col_rb3:
            st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
            run_rebal = st.button("🔄 리밸런싱 계산 실행", key="btn_rebal")

        if run_rebal:
            with st.spinner("시세 및 목표 비중 계산 중..."):
                try:
                    res_rb = buy_recommendation(
                        holdings=portfolio.holdings,
                        budget_krw=portfolio.weekly_budget,
                        use_market_cap=rb_use_mcap,
                        top_n=int(rb_top_n),
                    )
                    st.session_state["rebal_result"] = res_rb
                except Exception as e:
                    st.error(f"오류 발생: {e}")

        if "rebal_result" in st.session_state:
            res_rb = st.session_state["rebal_result"]

            prices_rb   = res_rb["prices"]
            weights_rb  = res_rb["weights"]
            fx_rb       = res_rb["fx_rate"]
            fx_est_rb   = res_rb.get("fx_estimated", False)
            is_bull_rb  = res_rb["is_bull"]
            all_tickers = portfolio.tickers()

            if fx_est_rb:
                st.markdown(
                    '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 -- 추정값 사용 중</div>',
                    unsafe_allow_html=True,
                )

            regime_rb = "🐂 강세장 (모멘텀 강화)" if is_bull_rb else "🐻 약세장 (방어 모드)"

            holdings_rb = portfolio.holdings
            total_val_usd = 0.0
            curr_val_usd = {}
            for t in all_tickers:
                try:
                    p = float(prices_rb.get(t, 0) or 0)
                except Exception:
                    p = 0.0
                val = p * holdings_rb.get(t, 0)
                curr_val_usd[t] = val
                total_val_usd += val

            total_val_krw = total_val_usd * fx_rb

            c1, c2, c3 = st.columns(3)
            c1.markdown(
                f'<div class="metric-card"><div class="label">시장 국면</div>'
                f'<div class="value" style="font-size:0.95rem">{regime_rb}</div></div>',
                unsafe_allow_html=True,
            )
            c2.markdown(
                f'<div class="metric-card"><div class="label">포트폴리오 총액</div>'
                f'<div class="value">₩{total_val_krw:,.0f}</div></div>',
                unsafe_allow_html=True,
            )
            c3.markdown(
                f'<div class="metric-card"><div class="label">USD/KRW</div>'
                f'<div class="value">{fx_rb:,.2f}</div></div>',
                unsafe_allow_html=True,
            )
            st.write("")

            rows_rb = []
            for t in all_tickers:
                try:
                    curr_price = float(prices_rb.get(t, 0) or 0)
                except Exception:
                    curr_price = 0.0

                curr_shares = holdings_rb.get(t, 0.0)
                curr_val    = curr_val_usd.get(t, 0.0)
                curr_weight = (curr_val / total_val_usd) if total_val_usd > 0 else 0.0
                target_weight = float(weights_rb.get(t, 0.0)) if t in weights_rb.index else 0.0
                target_val_usd = total_val_usd * target_weight
                target_shares = (target_val_usd / curr_price) if curr_price > 0 else 0.0
                diff_shares = target_shares - curr_shares
                diff_usd    = diff_shares * curr_price
                diff_krw    = diff_usd * fx_rb

                rows_rb.append({
                    "티커":            t,
                    "현재가 (USD)":    curr_price if curr_price > 0 else None,
                    "보유 수량":       curr_shares,
                    "현재 비중 (%)":   curr_weight * 100,
                    "목표 비중 (%)":   target_weight * 100,
                    "비중 차이 (%)":   (target_weight - curr_weight) * 100,
                    "조정 수량":       diff_shares,
                    "조정 금액 (KRW)": diff_krw,
                })

            df_rb = pd.DataFrame(rows_rb)

            rb_col_cfg = {
                "현재가 (USD)":    st.column_config.NumberColumn(format="$%.2f"),
                "보유 수량":       st.column_config.NumberColumn(format="%.4f"),
                "현재 비중 (%)":   st.column_config.NumberColumn(format="%.1f%%"),
                "목표 비중 (%)":   st.column_config.NumberColumn(format="%.1f%%"),
                "비중 차이 (%)":   st.column_config.NumberColumn(format="%+.1f%%"),
                "조정 수량":       st.column_config.NumberColumn(format="%+.4f"),
                "조정 금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            }

            st.markdown('<div class="section-label">종목별 리밸런싱 내역</div>', unsafe_allow_html=True)
            st.dataframe(df_rb, column_config=rb_col_cfg, width="stretch", hide_index=True)

            sell_df = df_rb[df_rb["조정 수량"] < -0.0001].copy()
            buy_df  = df_rb[df_rb["조정 수량"] >  0.0001].copy()

            col_sell, col_buy = st.columns(2)
            with col_sell:
                st.markdown('<div class="section-label">📤 매도 대상 (초과 보유)</div>', unsafe_allow_html=True)
                if sell_df.empty:
                    st.markdown('<div class="success-banner">✅ 매도 필요 종목 없음</div>', unsafe_allow_html=True)
                else:
                    total_sell_krw = sell_df["조정 금액 (KRW)"].sum()
                    for _, row in sell_df.iterrows():
                        st.markdown(
                            f'<div class="warn-banner">'
                            f'<b>{row["티커"]}</b> — {row["조정 수량"]:+.4f}주 매도'
                            f'<br><span style="font-size:0.78rem">≈ ₩{row["조정 금액 (KRW)"]:,.0f} '
                            f'(현재 {row["현재 비중 (%)"]:.1f}% → 목표 {row["목표 비중 (%)"]:.1f}%)</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f'<div class="warn-banner" style="border-color:#c0392b">'
                        f'<b>총 매도 금액: ₩{total_sell_krw:,.0f}</b></div>',
                        unsafe_allow_html=True,
                    )

            with col_buy:
                st.markdown('<div class="section-label">📥 매수 대상 (비중 부족)</div>', unsafe_allow_html=True)
                if buy_df.empty:
                    st.markdown('<div class="success-banner">✅ 매수 필요 종목 없음</div>', unsafe_allow_html=True)
                else:
                    total_buy_krw = buy_df["조정 금액 (KRW)"].sum()
                    for _, row in buy_df.iterrows():
                        st.markdown(
                            f'<div class="success-banner">'
                            f'<b>{row["티커"]}</b> — {row["조정 수량"]:+.4f}주 매수'
                            f'<br><span style="font-size:0.78rem">≈ ₩{row["조정 금액 (KRW)"]:,.0f} '
                            f'(현재 {row["현재 비중 (%)"]:.1f}% → 목표 {row["목표 비중 (%)"]:.1f}%)</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )
                    st.markdown(
                        f'<div class="success-banner" style="border-color:#27ae60">'
                        f'<b>총 매수 금액: ₩{total_buy_krw:,.0f}</b></div>',
                        unsafe_allow_html=True,
                    )

            st.markdown('<div class="section-label">현재 비중 vs 목표 비중</div>', unsafe_allow_html=True)
            chart_colors = [
                "#3949ab","#1e88e5","#00acc1","#43a047",
                "#fb8c00","#e53935","#8e24aa","#00897b","#f4511e","#6d4c41",
                "#546e7a","#78909c","#c0ca33","#26a69a","#ec407a",
            ]

            has_holdings = df_rb["현재 비중 (%)"].sum() > 0.01

            fig_rb = go.Figure()

            if has_holdings:
                fig_rb.add_trace(go.Pie(
                    labels=df_rb["티커"],
                    values=df_rb["현재 비중 (%)"].clip(lower=0),
                    name="현재", hole=0.45,
                    textinfo="percent",
                    texttemplate="%{percent:.1%}",
                    textposition="inside",
                    insidetextorientation="radial",
                    domain={"x": [0.1, 0.9], "y": [0.52, 1.0]},
                    marker=dict(colors=chart_colors[:len(df_rb)]),
                    title=dict(text="현재 비중", font=dict(color="#e0e0e0", size=12)),
                ))

            fig_rb.add_trace(go.Pie(
                labels=df_rb["티커"],
                values=df_rb["목표 비중 (%)"].clip(lower=0),
                name="목표", hole=0.45,
                textinfo="percent",
                texttemplate="%{percent:.1%}",
                textposition="inside",
                insidetextorientation="radial",
                domain={"x": [0.1, 0.9], "y": [0.0, 0.48] if has_holdings else [0.1, 0.9]},
                marker=dict(colors=chart_colors[:len(df_rb)]),
                title=dict(text="목표 비중", font=dict(color="#e0e0e0", size=12)),
            ))

            fig_rb.update_layout(
                paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
                font_color="#e0e0e0",
                margin=dict(t=40, b=10, l=10, r=10),
                height=720 if has_holdings else 400,
                showlegend=True,
                legend=dict(orientation="v", x=1.02, y=0.5,
                            font=dict(color="#e0e0e0", size=11), bgcolor="rgba(0,0,0,0)"),
            )
            st.plotly_chart(fig_rb, width="stretch", key="rb_pie_chart")

            st.caption(
                "📌 조정 수량이 양수(+)이면 매수, 음수(-)이면 매도를 의미합니다. "
                "Top N 이외 종목의 목표 비중은 0%입니다."
            )

# ══════════════════════════════════════════════
# 탭 5 : 설정
# ══════════════════════════════════════════════

with tab5:
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

    st.markdown('<div class="section-label">계정 정보</div>', unsafe_allow_html=True)
    st.markdown(f"""
    <div class="info-banner">
        👤 <b>로그인 계정:</b> {_user_name} ({_user_email})<br>
        💾 <b>데이터 저장 경로:</b> <code>portfolio_{_file_key}.json</code>
    </div>
    """, unsafe_allow_html=True)

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
    json_str = json.dumps(portfolio._data, ensure_ascii=False, indent=2)
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

# ══════════════════════════════════════════════
# 탭 6 : 매도 신호 (랭킹 탈락 종목)
# ══════════════════════════════════════════════

with tab6:
    st.markdown('<div class="section-label">매도 신호 설정</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="info-banner">'
        '📌 <b>매도 신호 탭</b>: 지난 1달(약 21 거래일) 동안 <b>매일</b> 종목별 랭킹을 계산하여, '
        '한 번도 설정한 순위(Top N) 안에 들지 못한 종목을 리스트업합니다. '
        '해당 종목들은 다음 리밸런싱 시 일괄 매도 후보입니다.'
        '</div>',
        unsafe_allow_html=True,
    )

    col_top, col_mcap6, col_run6 = st.columns([2, 1.5, 1.5])
    with col_top:
        top_n_sell = st.number_input(
            "유지 기준 순위 (Top N)",
            min_value=1,
            max_value=len(portfolio.tickers()) if portfolio.tickers() else 50,
            value=min(15, len(portfolio.tickers())) if portfolio.tickers() else 15,
            step=1,
            help="최근 1달간 매일 이 순위 안에 한 번도 못 든 종목이 매도 후보가 됩니다.",
        )

    with col_mcap6:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        use_mcap6 = st.checkbox(
            "시가총액 가중 사용", value=True,
            help="매수 추천/리밸런싱 탭과 동일한 설정을 사용하세요.",
            key="sell_mcap",
        )

    with col_run6:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_sell = st.button("🔍 매도 후보 분석", key="btn_sell_signal")

    if run_sell:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            tickers_all = portfolio.tickers()
            if "mcap_cache6" in st.session_state:
                del st.session_state["mcap_cache6"]
            with st.spinner("1달치 일별 랭킹 계산 중..."):
                try:
                    from core.strategy import fetch_prices, momentum_score, vol_inv_rank, fetch_market_caps

                    data6 = fetch_prices(tickers_all, extra=["QQQ"], period="14mo")
                    prices6 = data6["prices"].reindex(columns=tickers_all).ffill()
                    qqq6    = data6.get("QQQ", pd.Series(dtype=float))

                    trading_days = prices6.index[-21:]

                    MOMENTUM_WEIGHTS_LOCAL = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
                    VOL_WINDOW_LOCAL = 60

                    daily_ranks  = {}
                    daily_scores = {}

                    for date in trading_days:
                        loc = prices6.index.get_loc(date)
                        start_loc = max(0, loc - 252)
                        sub = prices6.iloc[start_loc : loc + 1]

                        if len(sub) < 22:
                            continue

                        mom = pd.Series(0.0, index=sub.columns)
                        total_w = 0.0
                        for days, w in MOMENTUM_WEIGHTS_LOCAL.items():
                            if len(sub) <= days:
                                continue
                            ret = sub.pct_change(days).iloc[-1].fillna(0)
                            mom += w * ret.rank(pct=True)
                            total_w += w
                        if total_w > 0:
                            mom /= total_w

                        vol = sub.pct_change().rolling(VOL_WINDOW_LOCAL).std().iloc[-1]
                        inv = (1 / vol.replace(0, np.nan)).fillna(0)
                        vol_rank = inv.rank(pct=True) if inv.sum() > 0 else pd.Series(1.0 / len(sub.columns), index=sub.columns)

                        if qqq6 is not None and len(qqq6) > loc:
                            qqq_sub = qqq6.iloc[start_loc : loc + 1]
                            is_bull6 = float(qqq_sub.iloc[-1]) > float(qqq_sub.rolling(200).mean().iloc[-1]) if len(qqq_sub) >= 200 else True
                        else:
                            is_bull6 = True

                        p_mom6 = 2.0 if is_bull6 else 1.2
                        p_vol6 = 1.5
                        m_w6   = 0.7 if is_bull6 else 0.4
                        v_w6   = 0.3 if is_bull6 else 0.6

                        if use_mcap6:
                            if "mcap_cache6" not in st.session_state:
                                st.session_state["mcap_cache6"] = fetch_market_caps(tickers_all)
                            mcaps6 = st.session_state["mcap_cache6"].reindex(sub.columns).fillna(0)
                            w_base6 = (mcaps6 / mcaps6.sum()) if mcaps6.sum() > 0 else pd.Series(1.0 / len(sub.columns), index=sub.columns)
                        else:
                            w_base6 = pd.Series(1.0 / len(sub.columns), index=sub.columns)

                        alpha    = w_base6 * ((mom ** p_mom6) * m_w6 + (vol_rank ** p_vol6) * v_w6)
                        combined = alpha / alpha.sum() if alpha.sum() > 0 else alpha

                        ranks = combined.rank(ascending=False, method="min").astype(int)
                        daily_ranks[date]  = ranks
                        daily_scores[date] = combined

                    if not daily_ranks:
                        st.error("랭킹을 계산할 수 있는 거래일이 부족합니다.")
                    else:
                        rank_df  = pd.DataFrame(daily_ranks).T
                        score_df = pd.DataFrame(daily_scores).T

                        total_days  = len(rank_df)
                        in_top_n    = (rank_df <= top_n_sell).sum()
                        best_rank   = rank_df.min()
                        avg_rank    = rank_df.mean()
                        latest_rank = rank_df.iloc[-1]

                        st.session_state["sell_result"] = {
                            "top_n": top_n_sell,
                            "total_days": total_days,
                            "in_top_n": in_top_n,
                            "best_rank": best_rank,
                            "avg_rank": avg_rank,
                            "latest_rank": latest_rank,
                            "rank_df": rank_df,
                        }

                except Exception as e:
                    st.error(f"오류 발생: {e}")
                    import traceback
                    st.code(traceback.format_exc())

    if "sell_result" in st.session_state:
        sr          = st.session_state["sell_result"]
        top_n_v     = sr["top_n"]
        total_days  = sr["total_days"]
        in_top_n    = sr["in_top_n"]
        best_rank   = sr["best_rank"]
        avg_rank    = sr["avg_rank"]
        latest_rank = sr["latest_rank"]
        rank_df     = sr["rank_df"]
        tickers_all = portfolio.tickers()

        sell_candidates  = in_top_n[in_top_n == 0].index.tolist()
        watch_candidates = in_top_n[(in_top_n > 0) & (in_top_n < total_days * 0.5)].index.tolist()

        c1, c2, c3 = st.columns(3)
        c1.markdown(
            f'<div class="metric-card"><div class="label">분석 기간 (거래일)</div>'
            f'<div class="value">{total_days}일</div></div>',
            unsafe_allow_html=True,
        )
        c2.markdown(
            f'<div class="metric-card"><div class="label" style="color:#ef5350">매도 후보</div>'
            f'<div class="value" style="color:#ef5350">{len(sell_candidates)}종목</div></div>',
            unsafe_allow_html=True,
        )
        c3.markdown(
            f'<div class="metric-card"><div class="label" style="color:#ffa726">관찰 종목</div>'
            f'<div class="value" style="color:#ffa726">{len(watch_candidates)}종목</div></div>',
            unsafe_allow_html=True,
        )
        st.write("")

        if sell_candidates:
            st.markdown(
                f'<div style="background:#2a0e0e;border:1px solid #ef5350;border-radius:8px;padding:10px 16px;color:#ef9a9a;margin:8px 0;">'
                f'🚨 <b>매도 후보 {len(sell_candidates)}종목</b> — 지난 {total_days}일간 단 하루도 Top {top_n_v} 안에 들지 못했습니다.</div>',
                unsafe_allow_html=True,
            )
            sell_rows = []
            for t in sell_candidates:
                sell_rows.append({
                    "티커": t,
                    f"Top{top_n_v} 진입 (일)": int(in_top_n[t]),
                    "최고 순위 (기간 내)": int(best_rank[t]),
                    "평균 순위": round(float(avg_rank[t]), 1),
                    "최근 순위": int(latest_rank[t]),
                    "보유 수량": portfolio.holdings.get(t, 0),
                })
            sell_df = pd.DataFrame(sell_rows).sort_values("최근 순위")
            st.dataframe(
                sell_df,
                column_config={"보유 수량": st.column_config.NumberColumn(format="%.4f")},
                hide_index=True,
                width='stretch',
            )
        else:
            st.markdown(
                f'<div class="success-banner">✅ 모든 종목이 지난 {total_days}일 중 최소 1일 이상 Top {top_n_v} 안에 진입했습니다.</div>',
                unsafe_allow_html=True,
            )

        if watch_candidates:
            st.markdown(
                f'<div style="background:#2a1a0e;border:1px solid #ffa726;border-radius:8px;padding:10px 16px;color:#ffcc80;margin:8px 0;">'
                f'⚠️ <b>관찰 종목 {len(watch_candidates)}종목</b> — Top {top_n_v} 진입 일수가 전체 기간의 50% 미만입니다.</div>',
                unsafe_allow_html=True,
            )
            watch_rows = []
            for t in watch_candidates:
                pct = in_top_n[t] / total_days * 100
                watch_rows.append({
                    "티커": t,
                    f"Top{top_n_v} 진입 (일)": int(in_top_n[t]),
                    "진입률 (%)": round(pct, 1),
                    "최고 순위 (기간 내)": int(best_rank[t]),
                    "평균 순위": round(float(avg_rank[t]), 1),
                    "최근 순위": int(latest_rank[t]),
                })
            watch_df = pd.DataFrame(watch_rows).sort_values("진입률 (%)")
            st.dataframe(
                watch_df,
                column_config={
                    "진입률 (%)": st.column_config.ProgressColumn(min_value=0, max_value=50, format="%.1f%%"),
                },
                hide_index=True,
                width='stretch',
            )

        st.write("")
        st.markdown('<div class="section-label">일별 순위 히트맵 (최근 1달)</div>', unsafe_allow_html=True)

        heatmap_data    = rank_df[tickers_all].T
        date_labels     = [d.strftime("%m/%d") for d in heatmap_data.columns]
        n_tickers_total = len(tickers_all)

        colorscale = [
            [0.0, "#1b5e20"],
            [top_n_v / n_tickers_total if n_tickers_total > 0 else 0.5, "#66bb6a"],
            [(top_n_v + 1) / n_tickers_total if n_tickers_total > 0 else 0.5, "#ef5350"],
            [1.0, "#b71c1c"],
        ]

        fig_hm = go.Figure(go.Heatmap(
            z=heatmap_data.values,
            x=date_labels,
            y=heatmap_data.index.tolist(),
            colorscale=colorscale,
            zmin=1, zmax=n_tickers_total,
            colorbar=dict(
                title="순위",
                tickvals=[1, top_n_v, n_tickers_total],
                ticktext=["1위", f"{top_n_v}위", f"{n_tickers_total}위"],
                thickness=12, len=0.7,
            ),
            text=heatmap_data.values,
            texttemplate="%{text}",
            textfont=dict(size=9, color="white"),
            hoverongaps=False,
            hovertemplate="날짜: %{x}<br>종목: %{y}<br>순위: %{z}위<extra></extra>",
        ))
        fig_hm.update_layout(
            paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e", font_color="#e0e0e0",
            margin=dict(t=20, b=40, l=80, r=80),
            height=max(300, 28 * n_tickers_total + 80),
            xaxis=dict(side="bottom", tickangle=-45, tickfont=dict(size=9)),
            yaxis=dict(tickfont=dict(size=10)),
        )
        st.plotly_chart(fig_hm, width='stretch', key="sell_heatmap")

        st.markdown('<div class="section-label">종목별 Top N 진입률</div>', unsafe_allow_html=True)
        entry_pct  = (in_top_n / total_days * 100).reindex(tickers_all).sort_values(ascending=True)
        bar_colors = ["#ef5350" if v == 0 else ("#ffa726" if v < 50 else "#66bb6a") for v in entry_pct.values]

        fig_bar = go.Figure(go.Bar(
            x=entry_pct.values,
            y=entry_pct.index.tolist(),
            orientation="h",
            marker_color=bar_colors,
            text=[f"{v:.0f}%" for v in entry_pct.values],
            textposition="outside",
            textfont=dict(color="#e0e0e0", size=10),
            hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
        ))
        fig_bar.add_vline(
            x=50, line_dash="dash", line_color="#ffa726",
            annotation_text="50% 기준선",
            annotation_font_color="#ffa726",
            annotation_position="top right",
        )
        fig_bar.update_layout(
            paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e", font_color="#e0e0e0",
            xaxis=dict(title=f"Top {top_n_v} 진입률 (%)", range=[0, 115], gridcolor="#2a3a5c"),
            yaxis=dict(gridcolor="#2a3a5c"),
            margin=dict(t=20, b=40, l=80, r=60),
            height=max(300, 26 * n_tickers_total + 80),
            showlegend=False,
        )
        st.plotly_chart(fig_bar, width='stretch', key="sell_bar")