"""tabs/tab_sell_signal.py — 매도 신호 탭"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.portfolio import Portfolio


def render(portfolio: Portfolio):
    st.markdown('<div class="section-label">매도 신호 설정</div>', unsafe_allow_html=True)

    st.markdown(
        '<div class="info-banner">'
        '📌 <b>매도 신호 탭</b>: 지난 1달(약 21 거래일) 동안 <b>매일</b> 종목별 랭킹을 계산하여, '
        '한 번도 설정한 순위(Top N) 안에 들지 못한 종목을 리스트업합니다.'
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
        )
    with col_mcap6:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        use_mcap6 = st.checkbox("시가총액 가중 사용", value=True, key="sell_mcap")
    with col_run6:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_sell = st.button("🔍 매도 후보 분석", key="btn_sell_signal")

    if run_sell:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            _run_sell_analysis(portfolio, top_n_sell, use_mcap6)

    if "sell_result" in st.session_state:
        _render_sell_result(portfolio, top_n_sell)


def _run_sell_analysis(portfolio, top_n_sell, use_mcap6):
    from core.strategy import fetch_prices, fetch_market_caps
    tickers_all = portfolio.tickers()
    if "mcap_cache6" in st.session_state:
        del st.session_state["mcap_cache6"]

    with st.spinner("1달치 일별 랭킹 계산 중..."):
        try:
            MOMENTUM_WEIGHTS_LOCAL = {21: 0.1, 63: 0.2, 126: 0.3, 252: 0.4}
            VOL_WINDOW_LOCAL = 60

            data6   = fetch_prices(tickers_all, extra=["QQQ"], period="14mo")
            prices6 = data6["prices"].reindex(columns=tickers_all).ffill()
            qqq6    = data6.get("QQQ", pd.Series(dtype=float))

            trading_days = prices6.index[-21:]
            daily_ranks  = {}
            daily_scores = {}

            for date in trading_days:
                loc = prices6.index.get_loc(date)
                start_loc = max(0, loc - 252)
                sub = prices6.iloc[start_loc: loc + 1]
                if len(sub) < 22:
                    continue

                mom    = pd.Series(0.0, index=sub.columns)
                total_w = 0.0
                for days, w in MOMENTUM_WEIGHTS_LOCAL.items():
                    if len(sub) <= days:
                        continue
                    ret = sub.pct_change(days).iloc[-1].fillna(0)
                    mom += w * ret.rank(pct=True)
                    total_w += w
                if total_w > 0:
                    mom /= total_w

                vol      = sub.pct_change().rolling(VOL_WINDOW_LOCAL).std().iloc[-1]
                inv      = (1 / vol.replace(0, np.nan)).fillna(0)
                vol_rank = inv.rank(pct=True) if inv.sum() > 0 else pd.Series(1.0 / len(sub.columns), index=sub.columns)

                if qqq6 is not None and len(qqq6) > loc:
                    qqq_sub  = qqq6.iloc[start_loc: loc + 1]
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
                    mcaps6  = st.session_state["mcap_cache6"].reindex(sub.columns).fillna(0)
                    w_base6 = (mcaps6 / mcaps6.sum()) if mcaps6.sum() > 0 else pd.Series(1.0 / len(sub.columns), index=sub.columns)
                else:
                    w_base6 = pd.Series(1.0 / len(sub.columns), index=sub.columns)

                alpha    = w_base6 * ((mom ** p_mom6) * m_w6 + (vol_rank ** p_vol6) * v_w6)
                combined = alpha / alpha.sum() if alpha.sum() > 0 else alpha
                ranks    = combined.rank(ascending=False, method="min").astype(int)
                daily_ranks[date]  = ranks
                daily_scores[date] = combined

            if not daily_ranks:
                st.error("랭킹을 계산할 수 있는 거래일이 부족합니다.")
                return

            rank_df     = pd.DataFrame(daily_ranks).T
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


def _render_sell_result(portfolio, top_n_sell):
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
        f'<div class="value">{total_days}일</div></div>', unsafe_allow_html=True,
    )
    c2.markdown(
        f'<div class="metric-card"><div class="label" style="color:#ef5350">매도 후보</div>'
        f'<div class="value" style="color:#ef5350">{len(sell_candidates)}종목</div></div>', unsafe_allow_html=True,
    )
    c3.markdown(
        f'<div class="metric-card"><div class="label" style="color:#ffa726">관찰 종목</div>'
        f'<div class="value" style="color:#ffa726">{len(watch_candidates)}종목</div></div>', unsafe_allow_html=True,
    )
    st.write("")

    if sell_candidates:
        st.markdown(
            f'<div style="background:#2a0e0e;border:1px solid #ef5350;border-radius:8px;padding:10px 16px;color:#ef9a9a;margin:8px 0;">'
            f'🚨 <b>매도 후보 {len(sell_candidates)}종목</b> — 지난 {total_days}일간 단 하루도 Top {top_n_v} 안에 들지 못했습니다.</div>',
            unsafe_allow_html=True,
        )
        sell_rows = [{
            "티커": t,
            f"Top{top_n_v} 진입 (일)": int(in_top_n[t]),
            "최고 순위 (기간 내)": int(best_rank[t]),
            "평균 순위": round(float(avg_rank[t]), 1),
            "최근 순위": int(latest_rank[t]),
            "보유 수량": portfolio.holdings.get(t, 0),
        } for t in sell_candidates]
        st.dataframe(
            pd.DataFrame(sell_rows).sort_values("최근 순위"),
            column_config={"보유 수량": st.column_config.NumberColumn(format="%.4f")},
            hide_index=True, width="stretch",
        )
    else:
        st.markdown(
            f'<div class="success-banner">✅ 모든 종목이 지난 {total_days}일 중 최소 1일 이상 Top {top_n_v} 안에 진입했습니다.</div>',
            unsafe_allow_html=True,
        )

    if watch_candidates:
        st.markdown(
            f'<div style="background:#2a1a0e;border:1px solid #ffa726;border-radius:8px;padding:10px 16px;color:#ffcc80;margin:8px 0;">'
            f'⚠️ <b>관찰 종목 {len(watch_candidates)}종목</b></div>',
            unsafe_allow_html=True,
        )
        watch_rows = [{
            "티커": t,
            f"Top{top_n_v} 진입 (일)": int(in_top_n[t]),
            "진입률 (%)": round(in_top_n[t] / total_days * 100, 1),
            "최고 순위 (기간 내)": int(best_rank[t]),
            "평균 순위": round(float(avg_rank[t]), 1),
            "최근 순위": int(latest_rank[t]),
        } for t in watch_candidates]
        st.dataframe(
            pd.DataFrame(watch_rows).sort_values("진입률 (%)"),
            column_config={"진입률 (%)": st.column_config.ProgressColumn(min_value=0, max_value=50, format="%.1f%%")},
            hide_index=True, width="stretch",
        )

    # 히트맵
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
        z=heatmap_data.values, x=date_labels, y=heatmap_data.index.tolist(),
        colorscale=colorscale, zmin=1, zmax=n_tickers_total,
        colorbar=dict(title="순위", tickvals=[1, top_n_v, n_tickers_total],
                      ticktext=["1위", f"{top_n_v}위", f"{n_tickers_total}위"], thickness=12, len=0.7),
        text=heatmap_data.values, texttemplate="%{text}",
        textfont=dict(size=9, color="white"),
        hovertemplate="날짜: %{x}<br>종목: %{y}<br>순위: %{z}위<extra></extra>",
    ))
    fig_hm.update_layout(
        paper_bgcolor="#1a1f2e", plot_bgcolor="#1a1f2e", font_color="#e0e0e0",
        margin=dict(t=20, b=40, l=80, r=80),
        height=max(300, 28 * n_tickers_total + 80),
        xaxis=dict(side="bottom", tickangle=-45, tickfont=dict(size=9)),
        yaxis=dict(tickfont=dict(size=10)),
    )
    st.plotly_chart(fig_hm, width="stretch", key="sell_heatmap")
