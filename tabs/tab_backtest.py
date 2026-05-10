"""tabs/tab_backtest.py — 백테스트 탭"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta

from core.portfolio import Portfolio
from core.strategy import run_backtest, calc_xirr_from_backtest, BENCHMARKS


def render(portfolio: Portfolio):
    st.markdown('<div class="section-label">백테스트 설정</div>', unsafe_allow_html=True)

    with st.expander("📖 KH 전략이란? (클릭하여 펼치기)", expanded=False):
        st.markdown("""
<div class="info-banner">
<b>🔬 KH 전략 작동 방식</b><br><br>
<b>① 시장 국면 판단 (Bull / Bear)</b><br>
QQQ의 현재가가 200일 이동평균선 위에 있으면 <b>강세장(Bull)</b>, 아래면 <b>약세장(Bear)</b>으로 판단합니다.<br><br>
<b>② 팩터 점수 계산</b><br>
· <b>모멘텀 점수</b>: 21일(10%) · 63일(20%) · 126일(30%) · 252일(40%) 수익률의 가중 순위<br>
· <b>변동성 역수 점수</b>: 60일 변동성이 낮을수록 높은 점수<br><br>
<b>③ 국면별 팩터 배합</b><br>
· 강세장: 모멘텀 70% + 변동성역수 30%<br>
· 약세장: 모멘텀 40% + 변동성역수 60%<br><br>
<b>④ 기본 비중 × 팩터 점수</b><br>
단일 종목 최대 비중 <b>25%</b> 제한.<br><br>
<b>⑤ 매주 적립식 매수 시뮬레이션</b><br>
매주 월요일 주간 예산을 위 비중대로 상위 N개 종목에 분할 매수.
</div>
""", unsafe_allow_html=True)

    st.markdown("""
<div class="info-banner">
⚠️ <b>백테스트 해석 주의사항</b><br>
① <b>생존 편향</b>: 현재 보유 종목으로만 시뮬레이션하므로 성과가 과대평가될 수 있습니다.<br>
② <b>시가총액 근사</b>: 과거 시총은 현재 발행주수 × 과거 주가로 근사합니다.<br>
③ <b>수익률 지표</b>: CAGR 대신 <b>XIRR</b>을 사용합니다.
</div>
""", unsafe_allow_html=True)

    # ── 매수 추천 탭에서 저장된 설정 가져오기 ────────────────────
    use_mcap  = portfolio.get_setting("buy_use_mcap", True)
    n_tickers = portfolio.get_setting("top_n", 10)
    buy_res   = st.session_state.get("buy_result")

    # 현재 매수 추천 기준 배너
    mcap_label = "시총 가중" if use_mcap else "균등 가중"
    if buy_res:
        tickers_r = buy_res["tickers"]
        weights   = buy_res["weights"]
        weight_parts = ", ".join(
            f"{t} {weights.get(t, 0)*100:.1f}%" for t in tickers_r
        )
        st.markdown(
            f'<div class="success-banner">'
            f'📌 <b>매수 추천 기준으로 백테스트</b> · {mcap_label} · Top {n_tickers}개<br>'
            f'<span style="font-size:0.8rem;color:#a5d6a7">{weight_parts}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            f'<div class="info-banner">'
            f'📌 매수 추천 탭 기준으로 실행됩니다 · <b>{mcap_label}</b> · <b>Top {n_tickers}개</b><br>'
            f'<span style="font-size:0.8rem;color:#7986cb">'
            f'매수 추천을 먼저 실행하면 종목별 비중도 함께 표시됩니다.</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    # ── 기간 / 벤치마크 / 실행 ───────────────────────────────────
    _saved_period = portfolio.get_setting("bt_period", "3년")
    _period_opts  = ["2년", "3년", "5년", "직접 입력"]
    _period_idx   = _period_opts.index(_saved_period) if _saved_period in _period_opts else 1

    col_p, col_bm, col_run2 = st.columns([1.5, 3, 1.5])
    with col_p:
        period_label = st.selectbox("기간", _period_opts, index=_period_idx)
        period_map   = {"2년": "2y", "3년": "3y", "5년": "5y"}
        period_str   = period_map.get(period_label, "3y")
    with col_bm:
        bm_input = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
        )
    with col_run2:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_bt = st.button("▶ 백테스트 실행", key="btn_bt")

    # 직접 입력 모드 날짜 UI
    custom_start = custom_end = None
    if period_label == "직접 입력":
        col_sd, col_ed = st.columns(2)
        with col_sd:
            custom_start = st.date_input(
                "시작일",
                value=date.today() - timedelta(days=1095),
                max_value=date.today() - timedelta(days=365),
                key="bt_custom_start",
            )
        with col_ed:
            custom_end = st.date_input(
                "종료일",
                value=date.today(),
                max_value=date.today(),
                key="bt_custom_end",
            )
        if custom_start >= custom_end:
            st.error("시작일이 종료일보다 앞서야 합니다.")

    st.caption(
        f"📌 주간 투자금: ₩{portfolio.weekly_budget:,} | "
        f"등록 종목: {len(portfolio.holdings)}개 | "
        f"매수 집중 Top N: {n_tickers}개 | {mcap_label}"
    )

    if run_bt:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        elif period_label == "직접 입력" and (custom_start is None or custom_end is None or custom_start >= custom_end):
            st.error("올바른 날짜 범위를 입력하세요.")
        else:
            bm_tickers = [b.strip().upper() for b in bm_input.split(",") if b.strip()]
            portfolio.benchmarks = bm_tickers
            portfolio.set_setting("bt_period", period_label)
            portfolio.save()

            if period_label == "직접 입력":
                start_date = custom_start.strftime("%Y-%m-%d")
                end_date   = custom_end.strftime("%Y-%m-%d")
            else:
                period_to_days = {"2y": 730, "3y": 1095, "5y": 1825}
                end_date   = date.today().strftime("%Y-%m-%d")
                start_date = (date.today() - timedelta(days=period_to_days[period_str])).strftime("%Y-%m-%d")

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
                        use_market_cap=use_mcap,
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

    if "bt_result" not in st.session_state:
        return

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
        xaxis=dict(gridcolor="#2d3748", tickfont=dict(color="#cbd5e1", size=10), tickangle=-30),
    )
    st.plotly_chart(fig, width="stretch", key="bt_chart")

    st.markdown('<div class="section-label">성과 요약 (XIRR 기준)</div>', unsafe_allow_html=True)

    invested     = df_bt["Invested"].iloc[-1]
    summary_rows = []
    all_cols     = ["KH_Strategy"] + bm_cols

    for col in all_cols:
        final    = df_bt[col].iloc[-1]
        ret_pct  = (final / invested - 1) * 100 if invested > 0 else 0.0
        xirr_val = calc_xirr_from_backtest(df_bt, portfolio.weekly_budget, col=col)
        xirr_pct = xirr_val * 100 if not np.isnan(xirr_val) else None
        running_max = df_bt[col].cummax()
        mdd = ((running_max - df_bt[col]) / running_max.replace(0, np.nan)).max() * 100
        summary_rows.append({
            "전략/벤치마크":       "✅ KH 전략" if col == "KH_Strategy" else col,
            "최종 평가금액 (M원)": final / 1_000_000,
            "누적 수익률 (%)":     ret_pct,
            "XIRR (%)":           xirr_pct,
            "MDD (%)":            mdd,
        })

    summary_rows.append({
        "전략/벤치마크":       "📌 누적 투자금",
        "최종 평가금액 (M원)": invested / 1_000_000,
        "누적 수익률 (%)":     None,
        "XIRR (%)":           None,
        "MDD (%)":            None,
    })

    bt_col_cfg = {
        "최종 평가금액 (M원)": st.column_config.NumberColumn(format="₩%.2fM"),
        "누적 수익률 (%)":     st.column_config.NumberColumn(format="%+.1f%%"),
        "XIRR (%)":           st.column_config.NumberColumn(format="%+.1f%%"),
        "MDD (%)":            st.column_config.NumberColumn(format="%.1f%%"),
    }
    st.dataframe(pd.DataFrame(summary_rows), column_config=bt_col_cfg, width="stretch", hide_index=True)
    st.caption(
        f"기간: {df_bt.index[0].date()} ~ {df_bt.index[-1].date()} | "
        "XIRR = 각 투자 시점을 반영한 실질 연수익률"
    )


import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, timedelta

from core.portfolio import Portfolio
from core.strategy import run_backtest, calc_xirr_from_backtest, BENCHMARKS
