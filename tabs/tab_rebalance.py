"""tabs/tab_rebalance.py — 리밸런싱 탭"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.portfolio import Portfolio
from core.strategy import buy_recommendation


def render(portfolio: Portfolio):
    st.markdown('<div class="section-label">리밸런싱 계산기</div>', unsafe_allow_html=True)

    st.markdown("""
<div class="info-banner">
📅 <b>리밸런싱이란?</b><br>
시간이 지나면 종목별 수익률 차이로 인해 실제 비중이 목표 비중에서 벗어납니다.
반기 또는 분기마다 초과 상승한 종목을 일부 매도하고 비중이 낮아진 종목을 매수하여
목표 비중으로 되돌리는 작업입니다.
</div>
""", unsafe_allow_html=True)

    if not portfolio.tickers():
        st.info("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        return

    col_rb1, col_rb2, col_rb3 = st.columns([1.5, 1.5, 1.5])
    with col_rb1:
        rb_use_mcap = st.checkbox("시가총액 가중 사용", value=True, key="rb_mcap")
    with col_rb2:
        rb_top_n = st.number_input(
            "비중 산출 종목 수 (Top N)",
            min_value=1,
            max_value=len(portfolio.tickers()),
            value=min(15, len(portfolio.tickers())),
            step=1,
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

    if "rebal_result" not in st.session_state:
        return

    res_rb      = st.session_state["rebal_result"]
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

    holdings_rb   = portfolio.holdings
    total_val_usd = 0.0
    curr_val_usd  = {}
    for t in all_tickers:
        try:
            p = float(prices_rb.get(t, 0) or 0)
        except Exception:
            p = 0.0
        val = p * holdings_rb.get(t, 0)
        curr_val_usd[t]  = val
        total_val_usd   += val

    total_val_krw = total_val_usd * fx_rb
    regime_rb     = "🐂 강세장 (모멘텀 강화)" if is_bull_rb else "🐻 약세장 (방어 모드)"

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
        curr_shares   = holdings_rb.get(t, 0.0)
        curr_val      = curr_val_usd.get(t, 0.0)
        curr_weight   = (curr_val / total_val_usd) if total_val_usd > 0 else 0.0
        target_weight = float(weights_rb.get(t, 0.0)) if t in weights_rb.index else 0.0
        target_val_usd = total_val_usd * target_weight
        target_shares  = (target_val_usd / curr_price) if curr_price > 0 else 0.0
        diff_shares    = target_shares - curr_shares
        diff_krw       = diff_shares * curr_price * fx_rb

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
        st.markdown('<div class="section-label">📤 매도 대상</div>', unsafe_allow_html=True)
        if sell_df.empty:
            st.markdown('<div class="success-banner">✅ 매도 필요 종목 없음</div>', unsafe_allow_html=True)
        else:
            for _, row in sell_df.iterrows():
                st.markdown(
                    f'<div class="warn-banner"><b>{row["티커"]}</b> — {row["조정 수량"]:+.4f}주 매도'
                    f'<br><span style="font-size:0.78rem">≈ ₩{row["조정 금액 (KRW)"]:,.0f} '
                    f'(현재 {row["현재 비중 (%)"]:,.1f}% → 목표 {row["목표 비중 (%)"]:,.1f}%)</span></div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="warn-banner" style="border-color:#c0392b">'
                f'<b>총 매도 금액: ₩{sell_df["조정 금액 (KRW)"].sum():,.0f}</b></div>',
                unsafe_allow_html=True,
            )

    with col_buy:
        st.markdown('<div class="section-label">📥 매수 대상</div>', unsafe_allow_html=True)
        if buy_df.empty:
            st.markdown('<div class="success-banner">✅ 매수 필요 종목 없음</div>', unsafe_allow_html=True)
        else:
            for _, row in buy_df.iterrows():
                st.markdown(
                    f'<div class="success-banner"><b>{row["티커"]}</b> — {row["조정 수량"]:+.4f}주 매수'
                    f'<br><span style="font-size:0.78rem">≈ ₩{row["조정 금액 (KRW)"]:,.0f} '
                    f'(현재 {row["현재 비중 (%)"]:,.1f}% → 목표 {row["목표 비중 (%)"]:,.1f}%)</span></div>',
                    unsafe_allow_html=True,
                )
            st.markdown(
                f'<div class="success-banner" style="border-color:#27ae60">'
                f'<b>총 매수 금액: ₩{buy_df["조정 금액 (KRW)"].sum():,.0f}</b></div>',
                unsafe_allow_html=True,
            )

    st.caption("📌 조정 수량이 양수(+)이면 매수, 음수(-)이면 매도를 의미합니다.")
