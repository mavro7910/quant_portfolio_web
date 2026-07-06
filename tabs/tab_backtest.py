"""tabs/tab_backtest.py — 백테스트 탭"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta

from core.portfolio import Portfolio
from core.strategy import run_backtest, calc_xirr_from_backtest, BENCHMARKS
from core.universe import get_universe
from utils.ui import section_title, banner, metric_card, badge, TEAL, TEAL_DARK, TEAL_LIGHT, TEXT, TEXT_SUB, TEXT_MUTED, BORDER, SURFACE
from utils.plotly_theme import base_layout, TEAL, BLUE, AMBER, RED, PURPLE, GREEN, TICK_COLOR, FONT_COLOR


def _calc_sharpe(series, risk_free=0.04):
    if len(series) < 4: return float("nan")
    wr = series.pct_change().dropna()
    if wr.std() == 0 or len(wr) < 4: return float("nan")
    return (wr.mean() * 52 - risk_free) / (wr.std() * np.sqrt(52))


def _calc_annual_vol(series):
    wr = series.pct_change().dropna()
    if len(wr) < 4: return float("nan")
    return float(wr.std() * np.sqrt(52) * 100)


def _return_metrics(returns, risk_free=0.04):
    values = pd.Series(returns).dropna()
    if len(values) < 4 or values.std() == 0:
        return float("nan"), float("nan"), float("nan")
    volatility = float(values.std() * np.sqrt(52) * 100)
    sharpe = float((values.mean() * 52 - risk_free) / (values.std() * np.sqrt(52)))
    curve = (1 + values).cumprod()
    mdd = float((curve / curve.cummax() - 1).min() * -100)
    return sharpe, volatility, mdd


def render(portfolio: Portfolio):
    mcap_preset = "factor"
    n_tickers   = portfolio.get_setting("top_n", 10)
    buy_res     = st.session_state.get("buy_result")
    universe = get_universe()
    strategy_tickers = list(universe.tickers)
    etf_count = len(portfolio.etf_tickers())

    _PRESET_LABELS = {"factor": "순수 팩터", "balanced": "균형", "mcap": "시총 편향"}
    mcap_label = "자동 Top 100 · 순수 팩터"

    if buy_res:
        tickers_r    = buy_res["tickers"]
        weights      = buy_res["weights"]
        weight_parts = ", ".join(f"{t} {weights.get(t,0)*100:.1f}%" for t in tickers_r)
        # Fix4: bt_result가 캐시돼 있으면 실제 실행 당시 설정을 표시 (stale 방지)
        _bt_cached = st.session_state.get("bt_result_meta", {})
        _display_n    = _bt_cached.get("top_n", n_tickers)
        with st.expander("📌 매수 추천 탭 설정 반영 중", expanded=False):
            st.markdown(banner(
                f"<b>유니버스:</b> 자동 Top 100 · <b>Top N:</b> {_display_n}<br>"
                f"<b>종목 비중:</b> {weight_parts}", "info"
            ), unsafe_allow_html=True)

    with st.expander("ℹ️ 백테스트 해석 주의사항", expanded=False):
        st.markdown("""
<div class="info-banner">
① <b>생존 편향</b>: 현재 Top 100을 과거에도 사용한 고정 유니버스이므로 성과가 과대평가될 수 있습니다.<br>
② <b>체결 지연</b>: 전일 종가까지 신호를 계산하고 다음 거래일 종가로 체결합니다.<br>
③ <b>수익률 지표</b>: XIRR과 입출금을 제거한 시간가중 수익률로 위험지표를 계산합니다.<br>
④ <b>비교 기준</b>: QPM Alpha와 벤치마크에 동일 시점·동일 금액을 투자합니다.
</div>
""", unsafe_allow_html=True)

    _period_opts  = ["1년", "2년", "3년", "5년", "직접 입력"]
    _saved_period = portfolio.get_setting("bt_period", "3년")
    _period_idx   = _period_opts.index(_saved_period) if _saved_period in _period_opts else 2

    col_p, col_bm, col_run2 = st.columns([1.5, 3, 1.5])
    with col_p:
        period_label = st.selectbox("기간", _period_opts, index=_period_idx)
        period_map   = {"1년": "1y", "2년": "2y", "3년": "3y", "5년": "5y"}
        period_str   = period_map.get(period_label, "3y")
    with col_bm:
        bm_input = st.text_input("벤치마크 티커 (쉼표 구분)", value=", ".join(portfolio.benchmarks))
    with col_run2:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_bt = st.button("▶ 백테스트 실행", key="btn_bt", type="primary")

    custom_start = custom_end = None
    if period_label == "직접 입력":
        col_sd, col_ed = st.columns(2)
        with col_sd:
            custom_start = st.date_input("시작일", value=date.today() - timedelta(days=1095),
                                         max_value=date.today() - timedelta(days=1), key="bt_custom_start")
        with col_ed:
            custom_end = st.date_input("종료일", value=date.today(),
                                       max_value=date.today(), key="bt_custom_end")
        if custom_start >= custom_end:
            st.error("시작일이 종료일보다 앞서야 합니다.")

    if period_label == "1년":
        st.markdown(
            '<div class="info-banner">ℹ️ 1년 선택 시 워밍업(252거래일) 확보를 위해 내부적으로 약 2년치 데이터를 수집합니다.</div>',
            unsafe_allow_html=True,
        )

    st.caption(
        f"📌 주간 투자금: ₩{portfolio.weekly_budget:,} · QPM 대상 {len(strategy_tickers)}개 · "
        f"Top {n_tickers} · {mcap_label}"
    )
    if etf_count:
        st.caption(f"ETF {etf_count}개는 백테스트 계산에서 제외됩니다.")

    if run_bt:
        if not strategy_tickers:
            st.error("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        elif period_label == "직접 입력" and (
            custom_start is None or custom_end is None or custom_start >= custom_end
        ):
            st.error("올바른 날짜 범위를 입력하세요.")
        else:
            bm_tickers = [b.strip().upper() for b in bm_input.split(",") if b.strip()]
            portfolio.benchmarks = bm_tickers
            portfolio.set_setting("bt_period", period_label)
            portfolio.save()

            if period_label == "직접 입력":
                sim_start_date = custom_start.strftime("%Y-%m-%d")
                end_date       = custom_end.strftime("%Y-%m-%d")
            else:
                period_to_days = {"1y": 365, "2y": 730, "3y": 1095, "5y": 1825}
                end_date       = date.today().strftime("%Y-%m-%d")
                sim_start_date = (date.today() - timedelta(days=period_to_days[period_str])).strftime("%Y-%m-%d")

            progress_bar = st.progress(0)
            status_text  = st.empty()

            def progress_cb(cur, total):
                pct = int(cur / total * 100) if total > 0 else 0
                progress_bar.progress(pct)
                status_text.caption(f"백테스트 진행 중... ({cur}/{total} 주)")

            try:
                with st.spinner("데이터 수집 중..."):
                    df_bt = run_backtest(
                        strategy_tickers,
                        weekly_budget=portfolio.weekly_budget,
                        benchmark_tickers=bm_tickers,
                        period=period_str,
                        mcap_preset=mcap_preset,
                        progress_cb=progress_cb,
                        top_n=int(n_tickers),
                        start=None, end=end_date,
                        sim_start=sim_start_date,
                    )
                st.session_state["bt_result"] = df_bt
                st.session_state["bt_result_meta"] = {
                    "mcap_preset": mcap_preset,
                    "top_n": n_tickers,
                }
                progress_bar.progress(100)
                status_text.caption("✅ 완료!")
            except Exception as e:
                st.error(f"백테스트 오류: {e}")
                import traceback
                st.code(traceback.format_exc())
                progress_bar.empty()
                status_text.empty()

    if "bt_result" not in st.session_state:
        return

    df_bt   = st.session_state["bt_result"]
    bm_cols = [
        c for c in df_bt.columns
        if c not in ("QPM_Alpha", "Invested", "QPM_Return")
        and not c.endswith("_Return")
    ]

    chart_mode = st.radio(
        "차트 기준", ["평가금액 (KRW)", "누적 수익률 (%)"],
        horizontal=True, key="bt_chart_mode",
    )

    # ── 차트 ──────────────────────────────────────────────
    bm_colors = [BLUE, AMBER, RED, PURPLE, GREEN]
    fig = go.Figure()
    lay = base_layout("", height=500)

    if chart_mode == "평가금액 (KRW)":
        fig.add_trace(go.Scatter(
            x=df_bt.index, y=df_bt["Invested"], name="누적 투자금",
            fill="tozeroy", fillcolor="rgba(15,110,86,0.05)",
            line=dict(color="rgba(15,110,86,0.3)", width=1, dash="dot"),
        ))
        fig.add_trace(go.Scatter(
            x=df_bt.index, y=df_bt["QPM_Alpha"], name="QPM Alpha",
            line=dict(color=TEAL, width=2.5),
            fill="tonexty", fillcolor="rgba(15,110,86,0.06)",
        ))
        for i, col in enumerate(bm_cols):
            fig.add_trace(go.Scatter(
                x=df_bt.index, y=df_bt[col],
                name=BENCHMARKS.get(col, col),
                line=dict(color=bm_colors[i % len(bm_colors)], width=1.8, dash="dash"),
            ))
        lay["yaxis"].update(tickformat=",.0f", tickprefix="₩", exponentformat="none")
        lay["title"]["text"] = "포트폴리오 성과 비교 (평가금액)"
    else:
        invested_s = df_bt["Invested"].replace(0, float("nan"))  # Fix1: 0→NaN으로 div 방어
        ret_kh = (df_bt["QPM_Alpha"] / invested_s - 1) * 100
        fig.add_hline(y=0, line_color="rgba(15,110,86,0.25)", line_dash="dot", line_width=1)
        fig.add_trace(go.Scatter(
            x=df_bt.index, y=ret_kh, name="QPM Alpha",
            line=dict(color=TEAL, width=2.5),
            fill="tozeroy", fillcolor="rgba(15,110,86,0.07)",
        ))
        for i, col in enumerate(bm_cols):
            ret_bm = (df_bt[col] / invested_s - 1) * 100
            fig.add_trace(go.Scatter(
                x=df_bt.index, y=ret_bm,
                name=BENCHMARKS.get(col, col),
                line=dict(color=bm_colors[i % len(bm_colors)], width=1.8, dash="dash"),
            ))
        lay["yaxis"].update(ticksuffix="%", zeroline=True, zerolinecolor="rgba(15,110,86,0.2)")
        lay["title"]["text"] = "포트폴리오 성과 비교 (누적 수익률)"

    lay.update(dict(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        xaxis=dict(
            gridcolor="rgba(15,110,86,0.12)", showgrid=False,
            tickfont=dict(color=TICK_COLOR, size=10), tickangle=-25,
        ),
        yaxis=dict(gridcolor="rgba(15,110,86,0.15)", tickfont=dict(color=TICK_COLOR, size=10)),
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.18,
            xanchor="center", x=0.5,
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)", borderwidth=0,
            font=dict(color=FONT_COLOR, size=11),
        ),
        margin=dict(t=60, b=90, l=60, r=16),
    ))
    fig.update_layout(lay)
    st.plotly_chart(fig, width="stretch", key="bt_chart")

    # ── 성과 요약 ──────────────────────────────────────────
    st.markdown(section_title("성과 요약"), unsafe_allow_html=True)

    invested_final = df_bt["Invested"].iloc[-1]
    summary_rows   = []

    for col in ["QPM_Alpha"] + bm_cols:
        final   = df_bt[col].iloc[-1]
        ret_pct = (final / invested_final - 1) * 100 if invested_final > 0 else 0.0
        xirr_val = calc_xirr_from_backtest(df_bt, col=col)
        xirr_pct = xirr_val * 100 if not np.isnan(xirr_val) else None
        return_col = "QPM_Return" if col == "QPM_Alpha" else f"{col}_Return"
        sharpe, ann_vol, mdd = _return_metrics(
            df_bt[return_col] if return_col in df_bt else pd.Series(dtype=float)
        )

        summary_rows.append({
            "전략":              "✅ QPM Alpha" if col == "QPM_Alpha" else BENCHMARKS.get(col, col),
            "최종 평가금액 (M원)": final / 1_000_000,
            "누적 수익률 (%)":   ret_pct,
            "XIRR (%)":         xirr_pct,
            "MDD (%)":          mdd,
            "연 변동성 (%)":     ann_vol,
            "Sharpe":           sharpe if not np.isnan(sharpe) else None,
        })

    summary_rows.append({
        "전략":              "📌 누적 투자금",
        "최종 평가금액 (M원)": invested_final / 1_000_000,
        "누적 수익률 (%)":   None,
        "XIRR (%)":         None,
        "MDD (%)":          None,
        "연 변동성 (%)":     None,
        "Sharpe":           None,
    })

    st.dataframe(
        pd.DataFrame(summary_rows),
        column_config={
            "최종 평가금액 (M원)": st.column_config.NumberColumn(format="₩%.2fM"),
            "누적 수익률 (%)":     st.column_config.NumberColumn(format="%+.1f%%"),
            "XIRR (%)":           st.column_config.NumberColumn(format="%+.1f%%"),
            "MDD (%)":            st.column_config.NumberColumn(format="%.1f%%"),
            "연 변동성 (%)":       st.column_config.NumberColumn(format="%.1f%%"),
            "Sharpe":             st.column_config.NumberColumn(format="%.2f"),
        },
        width="stretch", hide_index=True,
    )
    st.caption(
        f"기간: {df_bt.index[0].date()} ~ {df_bt.index[-1].date()} ({len(df_bt)}주) · "
        "XIRR = 적립식 내부수익률 · Sharpe = 무위험수익률 4% 기준"
    )
