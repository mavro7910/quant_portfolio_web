"""tabs/tab_buyrec.py — 매수 추천 탭"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from datetime import date, datetime

from core.portfolio import Portfolio
from core.insights import collect_execution_insights
from core.strategy import buy_recommendation
from core.universe import get_universe
from utils.ai_client import (
    get_finnhub_key, get_marketaux_key,
    has_finnhub_key, has_marketaux_key,
)
from utils.ui import section_title, metric_card, banner, badge, TEAL, TEAL_DARK, TEAL_LIGHT, TEXT, TEXT_SUB, TEXT_MUTED, BORDER, SURFACE, GOLD, GOLD_LIGHT, RED
from utils.plotly_theme import base_layout, TEAL as PT, BLUE, AMBER

def safe_sum(obj):
    if isinstance(obj, pd.Series): return float(obj.sum())
    if isinstance(obj, dict): return float(sum(obj.values()))
    try: return float(obj)
    except: return 0.0

def safe_get(obj, key, default=0.0):
    try:
        if isinstance(obj, pd.Series): return float(obj.get(key, default))
        if isinstance(obj, dict): return float(obj.get(key, default))
        return default
    except: return default


def render(portfolio: Portfolio):
    strategy_holdings = portfolio.strategy_holdings()
    etf_count = len(portfolio.etf_tickers())
    universe = get_universe()
    year_month = date.today().strftime("%Y-%m")

    col_b, col_n, col_run = st.columns([2.5, 2, 1.5])
    with col_b:
        budget = st.number_input("이번 주 배분할 금액 (KRW)", min_value=10_000, max_value=100_000_000,
                                 value=portfolio.weekly_budget, step=10_000)
    with col_n:
        _saved_n = portfolio.get_setting("top_n", 15)
        n_tickers = st.number_input(
            "추천 종목 수",
            min_value=5, max_value=30,
            value=max(5, min(int(_saved_n), 30)), step=1,
            help="자동 Top 100 유니버스에서 상위 N개를 선정합니다.",
        )
    with col_run:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_buy = st.button("▶ 매수 추천 실행", key="btn_buy", type="primary")

    with st.expander("Academic Momentum 알고리즘 개요", expanded=False):
        st.markdown(banner(
            "<b>① 자동 유니버스</b> — NYSE·Nasdaq 시가총액 상위 100개 보통주·ADR<br>"
            "<b>② 12-1 모멘텀</b> — 최근 1개월을 제외한 과거 12개월 수익률 65%<br>"
            "<b>③ 수익경로 지속성</b> — Frog-in-the-Pan 방식의 꾸준한 상승 20%<br>"
            "<b>④ 잔차변동성</b> — QQQ로 설명되지 않는 고유 변동성이 낮을수록 15%<br>"
            "<b>⑤ 월간 동일비중</b> — Top N을 한 달 고정하고 부족 비중에 입력금액 전액 배분",
            "info"), unsafe_allow_html=True)

    if etf_count:
        st.caption(f"ETF {etf_count}개는 QPM 매수 추천 계산에서 제외됩니다.")
    stale_text = " · 대체 스냅샷" if universe.stale else ""
    st.caption(
        f"유니버스 {len(universe.tickers)}개 · 기준일 {universe.as_of}"
        f" · {universe.source}{stale_text}"
    )
    include_insights = st.checkbox(
        "애널리스트·뉴스 이벤트 인사이트 포함",
        value=True,
        help="Finnhub·Marketaux·yfinance 데이터를 위험 플래그로 표시합니다. 검증 전까지 추천 비중은 변경하지 않습니다.",
    )

    if run_buy:
        portfolio.weekly_budget = budget
        portfolio.set_setting("top_n", int(n_tickers))
        locked = portfolio.locked_selection(year_month, int(n_tickers))
        with st.spinner("Top 100 시세 수집 및 팩터 계산 중..."):
            try:
                res = buy_recommendation(
                    holdings=strategy_holdings,
                    budget_krw=budget,
                    top_n=int(n_tickers),
                    universe_tickers=list(universe.tickers),
                    locked_selection=locked or None,
                )
                portfolio.save_strategy_selection(
                    year_month, res["tickers"], universe.as_of
                )
                res["universe_as_of"] = universe.as_of
                res["universe_stale"] = universe.stale
                if include_insights:
                    res["insights"] = collect_execution_insights(
                        res["tickers"],
                        get_finnhub_key() if has_finnhub_key() else None,
                        get_marketaux_key() if has_marketaux_key() else None,
                    )
                portfolio.save_strategy_observation({
                    "observed_at": datetime.now().isoformat(timespec="minutes"),
                    "universe_as_of": universe.as_of,
                    "selected": res["tickers"],
                    "weights": {
                        ticker: round(float(res["weights"].get(ticker, 0)), 6)
                        for ticker in res["tickers"]
                    },
                    "heat": {
                        ticker: round(float(res["scores"].loc[ticker, "heat"]), 4)
                        for ticker in res["tickers"]
                    },
                    "api_risk": {
                        ticker: res.get("insights", {}).get(ticker, {}).get("risk_level")
                        for ticker in res["tickers"]
                    },
                })
                portfolio.save()
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
    is_bull    = res["is_bull"]
    total_usd  = res["total_value_usd"]
    scores     = res.get("scores", pd.DataFrame())
    current_w  = res.get("current_weights", pd.Series(dtype=float))
    insights   = res.get("insights", {})
    result_budget = float(res.get("budget_krw", safe_sum(buy_krw)))

    if fx_est:
        st.markdown(banner("⚠️ USD/KRW 환율 조회 실패 — 추정값 사용", "warn"), unsafe_allow_html=True)

    # ── 메트릭 그리드 ─────────────────────────────────────
    regime_text = "강세장" if is_bull else "약세장"
    total_buy   = safe_sum(buy_krw)

    st.markdown(f"""
<div class="qpm-metric-grid">
  {metric_card("시장 상태", regime_text, f'{"QQQ > MA200" if is_bull else "QQQ < MA200"} · 순위에는 미반영', "#0F6E56" if is_bull else "#e05252")}
  {metric_card("자동 유니버스", f"{res.get('universe_size', 0)}개", f"기준 {res.get('universe_as_of', '—')}")}
  {metric_card("USD / KRW", f"{fx:,.0f}", "추정값" if fx_est else "실시간")}
  {metric_card("현재 주식 평가액", f"${total_usd:,.0f}", "ETF 제외")}
</div>
""", unsafe_allow_html=True)

    # ── 매수 추천 카드 (HTML) ─────────────────────────────
    st.markdown(section_title("이번 주 매수 추천"), unsafe_allow_html=True)
    rows_html = ""
    _colors = [TEAL,"#4a90d9","#c9873a","#8b72c8","#5ab87a","#e05252","#a0b4b2","#3a8fc8"]
    for i, t in enumerate(tickers_r):
        w   = safe_get(weights, t) * 100
        cw  = safe_get(current_w, t) * 100
        krw = safe_get(buy_krw, t)
        shr = safe_get(buy_shares, t)
        heat_state = str(scores.loc[t, "heat_state"]) if t in scores.index else "—"
        heat_pct = float(scores.loc[t, "heat"] * 100) if t in scores.index else 0
        api_risk = insights.get(t, {}).get("risk_level", "—")
        heat_tone = "risk" if heat_state == "과열" else "warn" if heat_state == "주의" else "quiet"
        api_tone = "risk" if api_risk == "높음" else "warn" if api_risk == "주의" else "quiet"
        c   = _colors[i % len(_colors)]
        logo_url = portfolio.get_logo(t)
        if logo_url:
            icon_html = (
                f'<div class="qpm-rec-icon">'
                f'<img src="{logo_url}" alt="{t}" '
                f'style="width:100%;height:100%;object-fit:contain;padding:5px;border-radius:inherit" '
                f'onerror="this.remove();this.parentElement.textContent=\'{t[:2]}\';'
                f'this.parentElement.style.color=\'{c}\'">'
                f'</div>'
            )
        else:
            icon_html = (
                f'<div class="qpm-rec-icon" style="background:{c}18;color:{c}">{t[:2]}</div>'
            )
        rows_html += f"""
<div class="qpm-rec-row">
  {icon_html}
  <div class="qpm-rec-main">
    <div class="qpm-rec-name"><span class="qpm-rec-rank">{i+1}</span>{t}</div>
    <div class="qpm-rec-meta">
      <span class="qpm-rec-chip {heat_tone}">과열 {heat_pct:.0f} · {heat_state}</span>
      <span class="qpm-rec-chip {api_tone}">API {api_risk}</span>
      <span>{shr:.4f}주</span>
    </div>
  </div>
  <div class="qpm-rec-figures">
    <div class="qpm-rec-amount">₩{krw:,.0f}</div>
    <div class="qpm-rec-weight">목표 {w:.1f}% · 현재 {cw:.1f}%</div>
  </div>
</div>"""

    regime_badge = badge("강세장","bull") if is_bull else badge("약세장","bear")
    preset_badge = badge(f"Top {len(tickers_r)} 월간 고정","gold")

    st.markdown(f"""
<div class="qpm-rec-shell">
  <div class="qpm-rec-head">
    <div class="qpm-rec-badges">
      {regime_badge} {preset_badge}
    </div>
    <span class="qpm-rec-budget">주간 예산 ₩{result_budget:,.0f}</span>
  </div>
  {rows_html}
  <div class="qpm-rec-total">
    <span>총 투자금</span><strong>₩{total_buy:,.0f}</strong>
  </div>
</div>
""", unsafe_allow_html=True)

    # ── 상세 테이블 ────────────────────────────────────────
    with st.expander("📊 상세 내역 보기", expanded=False):
        rows = []
        for t in tickers_r:
            try: p = float(prices_r[t])
            except: p = None
            rows.append({"티커":t,
                          "순위":int(scores.loc[t, "rank"]) if t in scores.index else None,
                          "12-1 수익률(%)":safe_get(scores["momentum_12_1"],t)*100 if "momentum_12_1" in scores else None,
                          "지속성(%)":safe_get(scores["continuity"],t)*100 if "continuity" in scores else None,
                          "잔차 변동성(%)":safe_get(scores["residual_vol"],t)*100 if "residual_vol" in scores else None,
                          "과열도":safe_get(scores["heat"],t)*100 if not scores.empty else None,
                          "상태":str(scores.loc[t, "heat_state"]) if t in scores.index else None,
                          "API 위험":insights.get(t, {}).get("risk_level"),
                          "API 근거":" · ".join(insights.get(t, {}).get("reasons", [])),
                          "현재 비중(%)":safe_get(current_w,t)*100,
                          "목표 비중(%)":safe_get(weights,t)*100,
                          "현재가(USD)":p, "매수금액(KRW)":safe_get(buy_krw,t),
                          "매수금액(USD)":safe_get(buy_usd,t), "매수 수량":safe_get(buy_shares,t)})
        st.dataframe(pd.DataFrame(rows), column_config={
            "12-1 수익률(%)": st.column_config.NumberColumn(format="%+.1f%%"),
            "지속성(%)":      st.column_config.NumberColumn(format="%.1f%%"),
            "잔차 변동성(%)": st.column_config.NumberColumn(format="%.1f%%"),
            "과열도":       st.column_config.NumberColumn(format="%.0f"),
            "현재 비중(%)": st.column_config.NumberColumn(format="%.1f%%"),
            "목표 비중(%)":  st.column_config.NumberColumn(format="%.1f%%"),
            "현재가(USD)":   st.column_config.NumberColumn(format="$%.2f"),
            "매수금액(KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "매수금액(USD)": st.column_config.NumberColumn(format="$%.2f"),
            "매수 수량":     st.column_config.NumberColumn(format="%.4f"),
        }, width="stretch", hide_index=True)

    # ── 현재 비중 vs 목표 비중 ────────────────────────────
    chart_tickers = list(reversed(tickers_r))
    fig_weights = go.Figure()
    fig_weights.add_trace(go.Bar(
        y=chart_tickers,
        x=[safe_get(current_w, ticker) * 100 for ticker in chart_tickers],
        name="현재",
        orientation="h",
        marker_color="rgba(148,163,184,0.55)",
        hovertemplate="<b>%{y}</b><br>현재 %{x:.1f}%<extra></extra>",
    ))
    fig_weights.add_trace(go.Bar(
        y=chart_tickers,
        x=[safe_get(weights, ticker) * 100 for ticker in chart_tickers],
        name="목표",
        orientation="h",
        marker_color=TEAL,
        hovertemplate="<b>%{y}</b><br>목표 %{x:.1f}%<extra></extra>",
    ))
    fig_weights.update_layout(
        barmode="group",
        height=max(340, len(chart_tickers) * 28),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=42, b=28, l=52, r=12),
        title=dict(text="현재 비중과 목표 비중", x=0, font=dict(size=13, color=TEXT_SUB)),
        xaxis=dict(ticksuffix="%", showgrid=True, gridcolor="rgba(148,163,184,0.15)"),
        yaxis=dict(showgrid=False),
        legend=dict(orientation="h", y=1.08, x=1, xanchor="right"),
        font=dict(color=TEXT_SUB, size=11),
    )
    st.plotly_chart(fig_weights, width="stretch", key="weight_comparison_chart")
