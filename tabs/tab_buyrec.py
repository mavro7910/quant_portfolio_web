"""tabs/tab_buyrec.py — 매수 추천 탭"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.portfolio import Portfolio
from core.strategy import buy_recommendation
from utils.plotly_theme import base_layout, LINE_COLORS, TEAL, AMBER, BG_PLOT


_PRESET_LABELS = {
    "factor":   "순수 팩터",
    "balanced": "균형",
    "mcap":     "시총 편향",
}
_PRESET_DESC = {
    "factor":   "모멘텀·변동성 팩터만 사용 (γ=0%)",
    "balanced": "팩터 85% + 시총 15% (γ=15%)",
    "mcap":     "팩터 70% + 시총 30% (γ=30%)",
}


def safe_sum(obj) -> float:
    if isinstance(obj, pd.Series): return float(obj.sum())
    if isinstance(obj, dict): return float(sum(obj.values()))
    try: return float(obj)
    except Exception: return 0.0


def safe_get(obj, key, default=0.0):
    try:
        if isinstance(obj, pd.Series): return float(obj.get(key, default))
        if isinstance(obj, dict): return float(obj.get(key, default))
        return default
    except Exception: return default


def render(portfolio: Portfolio):
    # ── 설정 행 ────────────────────────────────────────────
    col_b, col_m, col_run = st.columns([2.5, 2, 1.5])
    with col_b:
        budget = st.number_input(
            "투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
            value=portfolio.weekly_budget, step=10_000,
        )
    with col_m:
        _saved_preset = portfolio.get_setting("mcap_preset", "balanced")
        _preset_opts  = list(_PRESET_LABELS.keys())
        _preset_idx   = _preset_opts.index(_saved_preset) if _saved_preset in _preset_opts else 1
        mcap_preset = st.radio(
            "시총 반영",
            options=_preset_opts,
            format_func=lambda k: _PRESET_LABELS[k],
            index=_preset_idx,
            horizontal=False,
            help="\n".join(f"**{_PRESET_LABELS[k]}**: {_PRESET_DESC[k]}" for k in _preset_opts),
        )
    with col_run:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_buy = st.button("▶ 매수 추천 실행", key="btn_buy")

    _max_n     = len(portfolio.tickers()) if portfolio.tickers() else 20
    _saved_n   = portfolio.get_setting("top_n", 10)
    n_tickers = st.number_input(
        "추천 종목 수", min_value=1, max_value=_max_n,
        value=min(_saved_n, _max_n), step=1,
        help="포트폴리오 내 종목 중 상위 N개에 예산을 배분합니다.",
    )

    with st.expander("📐 QPM Alpha 알고리즘 개요", expanded=False):
        st.markdown("""
<div class="info-banner">
<b>① 시장 국면 판단</b> — QQQ 현재가 vs MA200 → 강세장 / 약세장<br><br>
<b>② 팩터 Z-score (AQR 방식)</b><br>
· <b>모멘텀</b>: 21일(10%) · 63일(20%) · 126일(30%) · 252일(40%) 수익률 Z-score 가중합<br>
· <b>변동성역수</b>: 60일 표준편차 역수 Z-score (낮은 변동성 → 높은 점수)<br><br>
<b>③ 국면별 가중합</b> — 강세장: 모멘텀 70% + 변동성역수 30% / 약세장: 40% + 60%<br><br>
<b>④ ReLU → 정규화 → 25% 캡</b> — 음수 alpha 종목 자연 배제 · 단일 종목 최대 25%
</div>
""", unsafe_allow_html=True)

    if run_buy:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            portfolio.weekly_budget = budget
            portfolio.set_setting("mcap_preset", mcap_preset)
            portfolio.set_setting("top_n", int(n_tickers))
            portfolio.save()
            with st.spinner("시장 데이터 수집 및 팩터 계산 중..."):
                try:
                    res = buy_recommendation(
                        holdings=portfolio.holdings,
                        budget_krw=budget,
                        mcap_preset=mcap_preset,
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
    mcap_gamma = res.get("mcap_gamma", 0.0)
    mcap_pname = res.get("mcap_preset", "balanced")
    is_bull    = res["is_bull"]
    total_usd  = res["total_value_usd"]

    if fx_est:
        st.markdown('<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 — 추정값 사용</div>', unsafe_allow_html=True)
    if mcap_gamma > 0 and not mcap_ok:
        st.markdown('<div class="warn-banner">⚠️ 시가총액 조회 실패 — 순수 팩터로 자동 전환되었습니다.</div>', unsafe_allow_html=True)

    # ── 요약 메트릭 ────────────────────────────────────────
    regime_text = "강세장" if is_bull else "약세장"
    regime_sub  = "QQQ > MA200" if is_bull else "QQQ < MA200"
    c1, c2, c3, c4 = st.columns(4)
    c1.markdown(
        f'<div class="metric-card"><div class="label">시장 국면</div>'
        f'<div class="value">{regime_text}</div>'
        f'<div class="sub {"up" if is_bull else "down"}">{regime_sub}</div></div>',
        unsafe_allow_html=True,
    )
    c2.markdown(
        f'<div class="metric-card"><div class="label">시총 반영</div>'
        f'<div class="value" style="font-size:1.05rem">{_PRESET_LABELS.get(mcap_pname, mcap_pname)}</div>'
        f'<div class="sub">{_PRESET_DESC.get(mcap_pname,"")}</div></div>',
        unsafe_allow_html=True,
    )
    c3.markdown(
        f'<div class="metric-card"><div class="label">USD/KRW</div>'
        f'<div class="value">{fx:,.0f}</div>'
        f'<div class="sub">{"추정값" if fx_est else "실시간"}</div></div>',
        unsafe_allow_html=True,
    )
    c4.markdown(
        f'<div class="metric-card"><div class="label">포트폴리오 총액</div>'
        f'<div class="value">${total_usd:,.0f}</div>'
        f'<div class="sub">현재가 기준</div></div>',
        unsafe_allow_html=True,
    )
    st.write("")

    # ── 매수 테이블 ────────────────────────────────────────
    st.markdown('<div class="section-label">종목별 매수 내역</div>', unsafe_allow_html=True)
    rows = []
    for t in tickers_r:
        try: p = float(prices_r[t])
        except (KeyError, TypeError, ValueError): p = None
        rows.append({
            "티커":          t,
            "목표 비중 (%)": safe_get(weights, t) * 100,
            "현재가 (USD)":  p,
            "매수금액 (KRW)":safe_get(buy_krw, t),
            "매수금액 (USD)":safe_get(buy_usd, t),
            "매수 수량":     safe_get(buy_shares, t),
        })

    st.dataframe(
        pd.DataFrame(rows),
        column_config={
            "목표 비중 (%)":  st.column_config.NumberColumn(format="%.1f%%"),
            "현재가 (USD)":   st.column_config.NumberColumn(format="$%.2f"),
            "매수금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "매수금액 (USD)": st.column_config.NumberColumn(format="$%.2f"),
            "매수 수량":      st.column_config.NumberColumn(format="%.4f"),
        },
        width="stretch", hide_index=True,
    )

    total_buy = safe_sum(buy_krw)
    st.markdown(
        f'<div class="success-banner">✅ 총 매수 금액: ₩{total_buy:,.0f}</div>',
        unsafe_allow_html=True,
    )

    # ── 파이 차트 ────────────────────────────────────────
    pie_values = [safe_get(weights, t) for t in tickers_r]
    _colors = [TEAL, "#4a90d9", AMBER, "#e05252", "#8b72c8",
               "#5ab87a", "#a0b4b2", "#c9873a", "#3a8fc8", "#7ab87a"]

    fig_pie = go.Figure(go.Pie(
        labels=tickers_r, values=pie_values, hole=0.48,
        textinfo="percent",
        texttemplate="%{percent:.1%}",
        textposition="inside",
        insidetextorientation="radial",
        marker=dict(colors=_colors[:len(tickers_r)],
                    line=dict(color="rgba(255,255,255,0.6)", width=1.5)),
        hovertemplate="<b>%{label}</b><br>비중: %{percent:.1%}<extra></extra>",
    ))
    lay = base_layout("목표 비중", height=340)
    lay.update(dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=36, b=10, l=10, r=10),
        showlegend=True,
        legend=dict(
            orientation="v", x=1.02, y=0.5,
            font=dict(color="#2a3a38", size=11),
            bgcolor="rgba(0,0,0,0)",
        ),
    ))
    fig_pie.update_layout(lay)
    st.plotly_chart(fig_pie, width="stretch", key="pie_chart")
