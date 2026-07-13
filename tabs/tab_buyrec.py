"""tabs/tab_buyrec.py — 매수 추천 탭"""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.portfolio import Portfolio
from core.strategy import buy_recommendation
from utils.ui import section_title, metric_card, banner, badge, TEAL, TEAL_DARK, TEAL_LIGHT, TEXT, TEXT_SUB, TEXT_MUTED, BORDER, SURFACE, GOLD, GOLD_LIGHT, RED
from utils.plotly_theme import base_layout, TEAL as PT, BLUE, AMBER

_PRESET_LABELS = {"factor":"순수 팩터","balanced":"균형","mcap":"시총 편향"}
_PRESET_DESC   = {"factor":"모멘텀·변동성 팩터만 (γ=0%)","balanced":"팩터 85% + 시총 15%","mcap":"팩터 70% + 시총 30%"}

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
    strategy_tickers = list(strategy_holdings.keys())
    etf_count = len(portfolio.etf_tickers())

    col_b, col_m, col_run = st.columns([2.5, 2, 1.5])
    with col_b:
        budget = st.number_input("투자 금액 (KRW)", min_value=10_000, max_value=100_000_000,
                                 value=portfolio.weekly_budget, step=10_000)
    with col_m:
        _saved  = portfolio.get_setting("mcap_preset","balanced")
        _opts   = list(_PRESET_LABELS.keys())
        _idx    = _opts.index(_saved) if _saved in _opts else 1
        mcap_preset = st.radio("시총 반영", options=_opts,
                               format_func=lambda k: _PRESET_LABELS[k], index=_idx,
                               horizontal=False,
                               help="\n".join(f"**{_PRESET_LABELS[k]}**: {_PRESET_DESC[k]}" for k in _opts))
    with col_run:
        st.markdown('<div style="height:1.6rem"></div>', unsafe_allow_html=True)
        run_buy = st.button("▶ 매수 추천 실행", key="btn_buy", type="primary")

    _max_n    = len(strategy_tickers) if strategy_tickers else 20
    _saved_n  = portfolio.get_setting("top_n", 10)
    n_tickers = st.number_input("추천 종목 수", min_value=1, max_value=_max_n,
                                value=min(_saved_n,_max_n), step=1,
                                help="포트폴리오 내 종목 중 상위 N개에 예산을 배분합니다.")

    with st.expander("📐 QPM Alpha 알고리즘 개요", expanded=False):
        st.markdown(banner(
            "<b>① 시장 국면</b> — QQQ 현재가 vs MA200 → 강세장 / 약세장<br>"
            "<b>② 팩터 Z-score</b> — 모멘텀(21·63·126·252일 가중) + 변동성역수(60일)<br>"
            "<b>③ 국면별 가중합</b> — 강세장: 모멘텀 70% + 변동성역수 30% / 약세장: 40%+60%<br>"
            "<b>④ ReLU → 정규화 → 25% 캡</b>", "info"), unsafe_allow_html=True)

    if etf_count:
        st.caption(f"ETF {etf_count}개는 QPM 매수 추천 계산에서 제외됩니다.")

    if run_buy:
        if not strategy_tickers:
            st.error("포트폴리오 탭에서 종목을 먼저 입력하세요.")
        else:
            portfolio.weekly_budget = budget
            portfolio.set_setting("mcap_preset", mcap_preset)
            portfolio.set_setting("top_n", int(n_tickers))
            portfolio.save()
            with st.spinner("시장 데이터 수집 및 팩터 계산 중..."):
                try:
                    res = buy_recommendation(holdings=strategy_holdings, budget_krw=budget,
                                             mcap_preset=mcap_preset, top_n=int(n_tickers))
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
    mcap_pname = res.get("mcap_preset","balanced")
    is_bull    = res["is_bull"]
    total_usd  = res["total_value_usd"]

    if fx_est:
        st.markdown(banner("⚠️ USD/KRW 환율 조회 실패 — 추정값 사용", "warn"), unsafe_allow_html=True)
    if mcap_gamma > 0 and not mcap_ok:
        st.markdown(banner("⚠️ 시가총액 조회 실패 — 순수 팩터로 자동 전환되었습니다.", "warn"), unsafe_allow_html=True)

    # ── 메트릭 그리드 ─────────────────────────────────────
    regime_text = "강세장" if is_bull else "약세장"
    regime_sub  = f'<span style="color:{"#0F6E56" if is_bull else "#e05252"}">{"QQQ > MA200" if is_bull else "QQQ < MA200"}</span>'
    total_buy   = safe_sum(buy_krw)

    st.markdown(f"""
<div class="qpm-metric-grid" style="display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:10px;margin:14px 0">
  {metric_card("시장 국면", regime_text, f'{"QQQ > MA200" if is_bull else "QQQ < MA200"}', "#0F6E56" if is_bull else "#e05252")}
  {metric_card("시총 반영", _PRESET_LABELS.get(mcap_pname,mcap_pname), _PRESET_DESC.get(mcap_pname,""))}
  {metric_card("USD / KRW", f"{fx:,.0f}", "추정값" if fx_est else "실시간")}
  {metric_card("QPM 대상 총액", f"${total_usd:,.0f}", "ETF 제외")}
</div>
""", unsafe_allow_html=True)

    # ── 매수 추천 카드 ─────────────────────────────
    st.markdown(section_title("이번 주 매수 추천"), unsafe_allow_html=True)
    _colors = [TEAL,"#4a90d9","#c9873a","#8b72c8","#5ab87a","#e05252","#a0b4b2","#3a8fc8"]
    rows_html = ""
    for i, t in enumerate(tickers_r):
        w   = safe_get(weights, t) * 100
        krw = safe_get(buy_krw, t)
        shr = safe_get(buy_shares, t)
        c   = _colors[i % len(_colors)]
        logo_url = portfolio.get_logo(t)
        if logo_url:
            icon_html = (
                f'<div class="qpm-buy-icon">'
                f'<img src="{logo_url}" alt="{t}" '
                f'onerror="this.remove();this.parentElement.textContent=\'{t[:2]}\';'
                f'this.parentElement.style.color=\'{c}\'">'
                f'</div>'
            )
        else:
            icon_html = f'<div class="qpm-buy-icon" style="color:{c};background:{c}18">{t[:2]}</div>'

        rows_html += f"""
<div class="qpm-buy-rec-card">
  {icon_html}
  <div class="qpm-buy-rec-body">
    <div class="qpm-buy-rec-title">#{i + 1} {t}</div>
    <div class="qpm-buy-rec-meta">비중 <b>{w:.1f}%</b> · 매수수량 {shr:.4f}주</div>
    <div class="qpm-buy-rec-amount">매수금액 ₩{krw:,.0f}</div>
  </div>
</div>"""

    st.markdown(f"""
<div class="qpm-buy-rec-head">
  <span>{regime_text} · {_PRESET_LABELS.get(mcap_pname,mcap_pname)}</span>
  <span>예산 ₩{budget:,}</span>
</div>
<div class="qpm-buy-rec-list">
  {rows_html}
</div>
<div class="qpm-buy-rec-total">총 ₩{total_buy:,.0f}</div>
<style>
.qpm-buy-rec-head {{
  display: flex;
  justify-content: space-between;
  gap: 8px;
  color: var(--qpm-text-muted, {TEXT_MUTED});
  font-size: 11px;
  margin: 4px 0 10px;
  flex-wrap: wrap;
}}
.qpm-buy-rec-list {{
  width: 100%;
}}
.qpm-buy-rec-card {{
  display: flex;
  gap: 12px;
  width: 100%;
  box-sizing: border-box;
  padding: 12px 2px;
  border-bottom: 0.5px solid var(--qpm-border, rgba(15,110,86,0.1));
}}
.qpm-buy-icon {{
  width: 34px;
  height: 34px;
  flex: 0 0 34px;
  border-radius: 9px;
  background: var(--qpm-surface, #F7F8FA);
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10px;
  font-weight: 700;
}}
.qpm-buy-icon img {{
  width: 100%;
  height: 100%;
  object-fit: contain;
  padding: 5px;
  box-sizing: border-box;
}}
.qpm-buy-rec-body {{
  min-width: 0;
  flex: 1 1 auto;
}}
.qpm-buy-rec-title {{
  color: var(--qpm-text, {TEXT});
  font-size: 13.5px;
  font-weight: 700;
  line-height: 1.25;
}}
.qpm-buy-rec-meta {{
  color: var(--qpm-text-muted, {TEXT_MUTED});
  font-size: 11px;
  line-height: 1.35;
  margin-top: 2px;
}}
.qpm-buy-rec-amount {{
  color: var(--qpm-teal, {TEAL});
  font-size: 14px;
  font-weight: 800;
  line-height: 1.3;
  margin-top: 5px;
  overflow-wrap: anywhere;
}}
.qpm-buy-rec-total {{
  color: var(--qpm-teal, {TEAL});
  font-size: 14px;
  font-weight: 800;
  text-align: right;
  margin-top: 10px;
}}
@media (max-width: 480px) {{
  .qpm-buy-rec-card {{ gap: 10px; padding: 12px 0; }}
  .qpm-buy-rec-amount {{ font-size: 13.5px; }}
}}
</style>
""", unsafe_allow_html=True)

    # ── 상세 테이블 ────────────────────────────────────────
    with st.expander("📊 상세 내역 보기", expanded=False):
        rows = []
        for t in tickers_r:
            try: p = float(prices_r[t])
            except: p = None
            rows.append({"티커":t, "목표 비중(%)":safe_get(weights,t)*100,
                          "현재가(USD)":p, "매수금액(KRW)":safe_get(buy_krw,t),
                          "매수금액(USD)":safe_get(buy_usd,t), "매수 수량":safe_get(buy_shares,t)})
        st.dataframe(pd.DataFrame(rows), column_config={
            "목표 비중(%)":  st.column_config.NumberColumn(format="%.1f%%"),
            "현재가(USD)":   st.column_config.NumberColumn(format="$%.2f"),
            "매수금액(KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "매수금액(USD)": st.column_config.NumberColumn(format="$%.2f"),
            "매수 수량":     st.column_config.NumberColumn(format="%.4f"),
        }, width="stretch", hide_index=True)

    # ── 파이 차트 ─────────────────────────────────────────
    pie_values = [safe_get(weights,t) for t in tickers_r]
    fig_pie = go.Figure(go.Pie(
        labels=tickers_r, values=pie_values, hole=0.48,
        textinfo="percent", texttemplate="%{percent:.1%}", textposition="inside",
        insidetextorientation="radial",
        insidetextfont=dict(color="#ffffff", size=11),   # 흰색 고정 — 다크/라이트 모두 가독
        marker=dict(colors=_colors[:len(tickers_r)],
                    line=dict(color="rgba(255,255,255,0.5)", width=1.5)),
        hovertemplate="<b>%{label}</b><br>%{percent:.1%}<extra></extra>",
    ))
    fig_pie.update_layout(dict(
        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(t=30,b=10,l=10,r=10), height=320,
        font=dict(color="#9cb8b4", size=11), showlegend=True,
        legend=dict(orientation="v", x=1.02, y=0.5,
                    font=dict(color="#9cb8b4", size=11), bgcolor="rgba(0,0,0,0)"),
        title=dict(text="목표 비중", font=dict(color="#7aada8", size=12), x=0.01),
    ))
    st.plotly_chart(fig_pie, use_container_width=True, key="pie_chart")
