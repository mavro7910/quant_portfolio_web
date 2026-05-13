"""tabs/tab_buyrec.py — 매수 추천 탭"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.portfolio import Portfolio
from core.strategy import buy_recommendation


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


def render(portfolio: Portfolio):
    st.markdown('<div class="section-label">투자 설정</div>', unsafe_allow_html=True)

    with st.expander("📐 비중 산출 알고리즘 (클릭하여 펼치기)", expanded=False):
        st.markdown("""
<div class="info-banner">
<b>KH 전략 비중 산출 방식</b><br><br>

<b>① 시장 국면 판단</b><br>
QQQ 현재가가 200일 이동평균(MA200) 위면 <b>강세장(Bull)</b>, 아래면 <b>약세장(Bear)</b>.<br><br>

<b>② 팩터 점수 계산</b> — 모두 0~1 순위(rank)로 동일 스케일<br>
· <b>모멘텀</b>: 21일(10%) · 63일(20%) · 126일(30%) · 252일(40%) 수익률 순위 가중합<br>
· <b>변동성역수</b>: 60일 표준편차 역수 순위 — 덜 출렁일수록 높은 점수<br><br>

<b>③ 코어 알파 — 가중 기하평균(곱)</b><br>
<code>core = 모멘텀 ^ m_w  ×  변동성역수 ^ v_w</code><br>
두 팩터 모두 좋아야 높은 점수. 하나라도 낮으면 곱이 작아져 강한 패널티 부여.<br>
국면에 따라 지수(m_w / v_w)를 조절해 강세·약세 성격을 반영합니다.<br>

<table style="margin:6px 0;font-size:0.85rem">
<tr><th style="text-align:left;padding-right:16px">국면</th><th>모멘텀(m_w)</th><th>변동성역수(v_w)</th></tr>
<tr><td>🐂 강세장</td><td>0.7</td><td>0.3</td></tr>
<tr><td>🐻 약세장</td><td>0.4</td><td>0.6</td></tr>
</table>

<b>④ 시총 팩터 — 독립 가산(합)</b><br>
<code>최종비중 = core × (1 - γ)  +  시총rank × γ</code><br>
시총은 <b>유동성 참고 신호</b>로 소량(γ = 15%) 독립적으로 더합니다.<br>
· 토글 ON: γ = 15% → 대형주 방향으로 약하게 끌어당김<br>
· 토글 OFF: γ = 0% → 시총 완전 무시, 순수 팩터 알파만 사용<br>
시총 조회(yfinance) 실패 시에도 γ = 0 으로 자동 fallback됩니다.<br><br>

<b>⑤ 단일 종목 캡</b><br>
최종 비중이 <b>25%</b>를 초과하는 종목은 잘라낸 뒤 재정규화합니다.
</div>
""", unsafe_allow_html=True)

    col_b, col_m, col_run = st.columns([2.5, 2, 1.5])
    with col_b:
        budget = st.number_input(
            "투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
            value=portfolio.weekly_budget, step=10_000,
        )
    with col_m:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        use_mcap = st.checkbox(
            "시가총액 가중 사용 (γ=15%)",
            value=portfolio.get_setting("buy_use_mcap", True),
            help="ON: 코어 알파 85% + 시총 rank 15% 합산. OFF: 코어 알파 100% (시총 완전 무시).",
        )
    with col_run:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_buy = st.button("▶ 매수 추천 실행", key="btn_buy")

    _max_n     = len(portfolio.tickers()) if portfolio.tickers() else 20
    _saved_n   = portfolio.get_setting("top_n", 10)
    _default_n = min(_saved_n, _max_n)

    n_tickers = st.number_input(
        "추천 종목 수",
        min_value=1,
        max_value=_max_n,
        value=_default_n,
        step=1,
        help="포트폴리오 내 종목 중 상위 N개에만 이번 주 예산을 배분합니다.",
    )

    if run_buy:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            portfolio.weekly_budget = budget
            portfolio.set_setting("buy_use_mcap", use_mcap)
            portfolio.set_setting("top_n", int(n_tickers))
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

    if "buy_result" not in st.session_state:
        return

    res        = st.session_state["buy_result"]
    tickers_r  = res["tickers"]
    weights    = res["weights"]
    buy_krw    = res["buy_krw"]
    buy_usd    = res["buy_usd"]
    buy_shares = res["buy_shares"]
    prices_r   = res["prices"]
    fx         = res["fx_rate"]
    fx_est     = res.get("fx_estimated", False)
    mcap_ok    = res.get("mcap_ok", True)
    is_bull    = res["is_bull"]
    total_usd  = res["total_value_usd"]

    if fx_est:
        st.markdown(
            '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 -- 추정값 사용</div>',
            unsafe_allow_html=True,
        )

    use_mcap_display = portfolio.get_setting("buy_use_mcap", True)
    if use_mcap_display and not mcap_ok:
        st.markdown(
            '<div class="warn-banner">⚠️ 시가총액 데이터 조회 실패 — 이번 결과는 균등 가중으로 계산되었습니다.'
            ' yfinance 일시 장애일 수 있습니다. 잠시 후 재실행해 주세요.</div>',
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
    n = len(pie_labels)

    fig_pie = go.Figure(go.Pie(
        labels=pie_labels, values=pie_values, hole=0.45,
        textinfo="percent", texttemplate="%{percent:.1%}",
        textposition="inside", insidetextorientation="radial",
        marker=dict(colors=[
            "#3949ab","#1e88e5","#00acc1","#43a047",
            "#fb8c00","#e53935","#8e24aa","#00897b","#f4511e","#6d4c41",
        ]),
    ))
    fig_pie.update_layout(
        title="목표 비중", paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e",
        font_color="#e0e0e0", margin=dict(t=40, b=10, l=10, r=10),
        height=320 + n * 20, showlegend=True,
        legend=dict(orientation="v", x=1.02, y=0.5,
                    font=dict(color="#e0e0e0", size=11), bgcolor="rgba(0,0,0,0)"),
    )
    st.plotly_chart(fig_pie, width="stretch", key="pie_chart")
