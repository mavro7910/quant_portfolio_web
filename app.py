"""
app.py

Quant Portfolio Manager - Streamlit 웹 앱 버전
PyQt6 데스크톱 앱을 모바일/브라우저에서 실행 가능한 웹앱으로 변환.
core/ 폴더의 로직은 그대로 재사용.

변경사항 (최신화):

- buy_krw dict/Series 타입 안전 처리
- 종목 추가/삭제 시 세션 캐시 자동 무효화
- 환율 하드코딩 제거, core에서 받은 값만 사용
- 가격 조회 실패 종목 명시적 표시 ("N/A")
- st.progress text 파라미터 호환성 개선
- label_visibility 정리, 명시적 label 사용
- 전반적인 에러 핸들링 강화
- pandas Series/dict 혼용 방어 로직 추가
"""

import json
import sys
import os
from pathlib import Path

import numpy as np
import pandas as pd
import streamlit as st
import plotly.graph_objects as go

# core 모듈 경로 추가
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from core.portfolio import Portfolio
from core.data import fetch_prices_and_fx
from core.strategy import buy_recommendation, run_backtest, BENCHMARKS

# ─────────────────────────────────────────────
# 유틸 함수
# ─────────────────────────────────────────────

def safe_sum(obj) -> float:
    """dict 또는 pandas Series 모두 안전하게 합산"""
    if isinstance(obj, pd.Series):
        return float(obj.sum())
    elif isinstance(obj, dict):
        return float(sum(obj.values()))
    try:
        return float(obj)
    except Exception:
        return 0.0

def safe_get(obj, key, default=0.0):
    """dict 또는 pandas Series에서 안전하게 값 조회"""
    try:
        if isinstance(obj, pd.Series):
            return float(obj.get(key, default))
        elif isinstance(obj, dict):
            return float(obj.get(key, default))
        return default
    except Exception:
        return default

def invalidate_cache(*keys):
    """세션 캐시에서 지정된 키 제거"""
    for k in keys:
        if k in st.session_state:
            del st.session_state[k]

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
# CSS 스타일
# ─────────────────────────────────────────────

st.markdown("""
<style>
/* 전체 배경 */
.stApp { background-color: #0f1117; color: #e0e0e0; }

/* 메인 헤더 */
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
.main-header p {
    margin: 4px 0 0 0;
    font-size: 0.85rem;
    color: #7986cb;
}

/* 카드 */
.metric-card {
    background: #1a1f2e;
    border: 1px solid #2a3a5c;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
}
.metric-card .label { font-size: 0.78rem; color: #7986cb; margin-bottom: 6px; }
.metric-card .value { font-size: 1.4rem; font-weight: 700; color: #e8eaf6; }

/* 경고 배너 */
.warn-banner {
    background: #2a1f0e;
    border: 1px solid #e67e22;
    border-radius: 8px;
    padding: 10px 16px;
    color: #e67e22;
    font-size: 0.85rem;
    margin: 8px 0;
}

/* 성공 배너 */
.success-banner {
    background: #0e2a1a;
    border: 1px solid #27ae60;
    border-radius: 8px;
    padding: 10px 16px;
    color: #27ae60;
    font-size: 0.85rem;
    margin: 8px 0;
}

/* 섹션 헤더 */
.section-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #7986cb;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 20px 0 8px 0;
}

/* 탭 스타일 */
.stTabs [data-baseweb="tab-list"] {
    background: #1a1f2e;
    border-radius: 10px;
    padding: 4px;
    gap: 4px;
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    color: #7986cb;
    font-weight: 600;
}
.stTabs [aria-selected="true"] {
    background: #283593 !important;
    color: #e8eaf6 !important;
}

/* 데이터프레임 */
.dataframe { font-size: 0.85rem; }

/* 버튼 */
.stButton > button {
    background: linear-gradient(135deg, #283593, #1a237e);
    color: white;
    border: none;
    border-radius: 8px;
    font-weight: 600;
    padding: 8px 20px;
    transition: all 0.2s;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #3949ab, #283593);
    transform: translateY(-1px);
}

/* 숨기기 */
#MainMenu { visibility: hidden; }
footer { visibility: hidden; }
header { visibility: hidden; }
</style>

""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
# 포트폴리오 세션 초기화
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
# 탭 구성
# ─────────────────────────────────────────────

tab1, tab2, tab3, tab4 = st.tabs([
    "📋 포트폴리오",
    "🧮 매수 추천",
    "📈 백테스트",
    "⚙️ 설정",
])

# ══════════════════════════════════════════════
# 탭 1 : 포트폴리오
# ══════════════════════════════════════════════

with tab1:
    st.markdown('<div class="section-label">보유 종목 관리</div>', unsafe_allow_html=True)

    col_t, col_s, col_btn1, col_btn2 = st.columns([2, 2, 1.5, 1.5])

    with col_t:
        new_ticker = st.text_input(
            "티커 입력",
            placeholder="AAPL",
            key="inp_ticker",
        ).upper().strip()

    with col_s:
        new_shares = st.number_input(
            "보유 수량",
            min_value=0.000001,
            max_value=9_999_999.0,
            value=1.0,
            step=0.1,
            format="%.6f",
            key="inp_shares",
        )

    with col_btn1:
        st.write("")  # 버튼 수직 정렬
        if st.button("➕ 추가/수정", width='stretch'):
            if new_ticker:
                portfolio.set_holding(new_ticker, new_shares)
                portfolio.save()
                # 종목 변경 → 관련 캐시 무효화
                invalidate_cache("prices_data", "buy_result", "bt_result")
                st.success(f"{new_ticker} 저장 완료!")
                st.rerun()
            else:
                st.error("티커를 입력하세요.")

    with col_btn2:
        tickers_list = portfolio.tickers()
        del_ticker = st.selectbox(
            "삭제할 종목 선택",
            ["선택..."] + tickers_list,
            key="del_select",
        )
        if st.button("🗑️ 삭제", width='stretch'):
            if del_ticker != "선택...":
                portfolio.remove_holding(del_ticker)
                portfolio.save()
                # 종목 변경 → 관련 캐시 무효화
                invalidate_cache("prices_data", "buy_result", "bt_result")
                st.success(f"{del_ticker} 삭제 완료!")
                st.rerun()

    # 보유 종목 테이블
    holdings = portfolio.holdings

    if not holdings:
        st.info("보유 종목이 없습니다. 위에서 티커와 수량을 입력해 추가하세요.")
    else:
        st.markdown('<div class="section-label">보유 종목 현황</div>', unsafe_allow_html=True)

        # 기본 테이블 (시세 없이)
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

        # 캐시된 시세 표시
        if "prices_data" in st.session_state:
            prices, fx, fx_est = st.session_state["prices_data"]

            if fx_est:
                st.markdown(
                    '<div class="warn-banner">⚠️ USD/KRW 환율 조회 실패 -- 추정값 사용 중</div>',
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

            df_hold = pd.DataFrame(
                rows,
                columns=["티커", "보유 수량", "현재가 (USD)", "평가금액 (KRW)"],
            )

            # 요약 지표
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

    col_b, col_m, col_run = st.columns([2, 2, 1.5])

    with col_b:
        budget = st.number_input(
            "투자 금액 (KRW)",
            min_value=10_000,
            max_value=100_000_000,
            value=portfolio.weekly_budget,
            step=10_000,
        )

    with col_m:
        use_mcap = st.checkbox(
            "시가총액 가중 사용",
            value=True,
            help="체크 시 실시간 시가총액 조회 (속도 느림)",
        )

    with col_run:
        st.write("")
        run_buy = st.button("▶ 매수 추천 실행", width='stretch', key="btn_buy")

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
                price_str = f"${p:,.2f}"
            except (KeyError, TypeError, ValueError):
                price_str = "N/A"

            krw_val = safe_get(buy_krw, t)
            usd_val = safe_get(buy_usd, t)
            shr_val = safe_get(buy_shares, t)
            wgt_val = safe_get(weights, t)

            rows.append({
                "티커": t,
                "목표 비중": f"{wgt_val:.1%}",
                "현재가 (USD)": price_str,
                "매수금액 (KRW)": f"₩{krw_val:,.0f}",
                "매수금액 (USD)": f"${usd_val:,.2f}",
                "매수 수량": f"{shr_val:.4f}",
            })

        st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)

        # 총 매수금액 -- dict/Series 모두 안전하게 합산
        total_buy = safe_sum(buy_krw)
        st.markdown(
            f'<div class="success-banner">✅ 총 매수 금액: ₩{total_buy:,.0f}</div>',
            unsafe_allow_html=True,
        )

        # 비중 파이차트
        pie_labels = tickers_r
        pie_values = [safe_get(weights, t) for t in tickers_r]

        fig_pie = go.Figure(go.Pie(
            labels=pie_labels,
            values=pie_values,
            hole=0.45,
            textinfo="label+percent",
            marker=dict(colors=[
                "#3949ab", "#1e88e5", "#00acc1", "#43a047",
                "#fb8c00", "#e53935", "#8e24aa", "#00897b",
                "#f4511e", "#6d4c41"
            ]),
        ))
        fig_pie.update_layout(
            title="목표 비중",
            paper_bgcolor="#1a1f2e",
            plot_bgcolor="#1a1f2e",
            font_color="#e0e0e0",
            margin=dict(t=40, b=10, l=10, r=10),
            height=320,
            showlegend=False,
        )
        st.plotly_chart(fig_pie, use_container_width=True, key="pie_chart")

# ══════════════════════════════════════════════
# 탭 3 : 백테스트
# ══════════════════════════════════════════════

with tab3:
    st.markdown('<div class="section-label">백테스트 설정</div>', unsafe_allow_html=True)

    col_p, col_m2, col_bm, col_run2 = st.columns([1.5, 2, 2, 1.5])

    with col_p:
        period_label = st.selectbox("기간", ["2년", "3년", "5년"], index=1)
        period_map = {"2년": "2y", "3년": "3y", "5년": "5y"}
        period_str = period_map[period_label]

    with col_m2:
        use_mcap_bt = st.checkbox(
            "시총 가중 반영",
            value=True,
            help="리밸런싱 시점에 시가총액 비중 사용",
        )

    with col_bm:
        bm_input = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
        )

    with col_run2:
        st.write("")
        run_bt = st.button("▶ 백테스트 실행", width='stretch', key="btn_bt")

    st.caption(f"📌 주간 투자금: ₩{portfolio.weekly_budget:,} | 보유 종목: {len(portfolio.holdings)}개")

    if run_bt:
        if not portfolio.tickers():
            st.error("포트폴리오 탭에서 종목을 먼저 추가하세요.")
        else:
            bm_tickers = [b.strip().upper() for b in bm_input.split(",") if b.strip()]
            portfolio.benchmarks = bm_tickers
            portfolio.save()

            # st.progress -- text 파라미터는 Streamlit 1.27+ 에서만 지원.
            # 안전하게 별도 status 텍스트로 분리.
            progress_bar = st.progress(0)
            status_text = st.empty()

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

        # 차트
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=df_bt.index,
            y=df_bt["Invested"],
            name="누적 투자금",
            fill="tozeroy",
            fillcolor="rgba(170,170,170,0.12)",
            line=dict(color="#aaaaaa", width=1),
        ))

        fig.add_trace(go.Scatter(
            x=df_bt.index,
            y=df_bt["KH_Strategy"],
            name="KH 전략",
            line=dict(color="#3f51b5", width=2.5),
        ))

        bm_colors = ["#e53935", "#43a047", "#fb8c00", "#9c27b0", "#00bcd4"]
        bm_cols = [c for c in df_bt.columns if c not in ("KH_Strategy", "Invested")]

        for i, col in enumerate(bm_cols):
            fig.add_trace(go.Scatter(
                x=df_bt.index,
                y=df_bt[col],
                name=BENCHMARKS.get(col, col),
                line=dict(color=bm_colors[i % len(bm_colors)], width=1.8, dash="dash"),
            ))

        fig.update_layout(
            title="포트폴리오 성과 비교",
            xaxis_title="날짜",
            yaxis_title="평가금액 (KRW)",
            paper_bgcolor="#1a1f2e",
            plot_bgcolor="#16213e",
            font_color="#e0e0e0",
            legend=dict(bgcolor="#1a1f2e", bordercolor="#2a3a5c", borderwidth=1),
            hovermode="x unified",
            margin=dict(t=50, b=40, l=60, r=20),
            height=450,
            yaxis=dict(tickformat=",.0f"),
            xaxis=dict(gridcolor="#2a3a5c"),
            yaxis_gridcolor="#2a3a5c",
        )
        st.plotly_chart(fig, use_container_width=True, key="bt_chart")

        # 요약 테이블
        st.markdown('<div class="section-label">성과 요약</div>', unsafe_allow_html=True)

        invested = df_bt["Invested"].iloc[-1]
        years = (df_bt.index[-1] - df_bt.index[0]).days / 365.25

        summary_rows = []
        all_cols = ["KH_Strategy"] + bm_cols

        for col in all_cols:
            final = df_bt[col].iloc[-1]
            ret_pct = (final / invested - 1) * 100 if invested > 0 else 0.0
            cagr = ((final / invested) ** (1 / max(years, 0.01)) - 1) * 100 if invested > 0 else 0.0
            running_max = df_bt[col].cummax()
            mdd = ((running_max - df_bt[col]) / running_max.replace(0, np.nan)).max() * 100

            summary_rows.append({
                "전략/벤치마크": "✅ KH 전략" if col == "KH_Strategy" else col,
                "최종 평가금액": f"₩{final / 1_000_000:.2f}M",
                "누적 수익률": f"{ret_pct:+.1f}%",
                "CAGR": f"{cagr:+.1f}%",
                "MDD": f"{mdd:.1f}%",
            })

        # 누적 투자금 행 추가
        summary_rows.append({
            "전략/벤치마크": "📌 누적 투자금",
            "최종 평가금액": f"₩{invested / 1_000_000:.2f}M",
            "누적 수익률": "–",
            "CAGR": "–",
            "MDD": "–",
        })

        st.dataframe(pd.DataFrame(summary_rows), width="stretch", hide_index=True)
        st.caption(f"기간: {df_bt.index[0].date()} ~ {df_bt.index[-1].date()}")

# ══════════════════════════════════════════════
# 탭 4 : 설정
# ══════════════════════════════════════════════

with tab4:
    st.markdown('<div class="section-label">투자 설정</div>', unsafe_allow_html=True)

    col_s1, col_s2 = st.columns(2)

    with col_s1:
        new_budget = st.number_input(
            "주간 투자 금액 (KRW)",
            min_value=10_000,
            max_value=100_000_000,
            value=portfolio.weekly_budget,
            step=10_000,
        )

    with col_s2:
        new_bm = st.text_input(
            "벤치마크 티커 (쉼표 구분)",
            value=", ".join(portfolio.benchmarks),
            placeholder="QQQM, XLK, SPY",
        )

    st.markdown('<div class="section-label">저장 위치</div>', unsafe_allow_html=True)
    st.code(str(portfolio.path.resolve()), language=None)

    if st.button("💾 설정 저장", width='content'):
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
            data=json_str,
            file_name="portfolio.json",
            mime="application/json",
        )

    st.markdown('<div class="section-label">포트폴리오 JSON 불러오기</div>', unsafe_allow_html=True)

    uploaded = st.file_uploader("portfolio.json 업로드", type=["json"])
    if uploaded is not None:
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
                    st.success("✅ 포트폴리오를 불러왔습니다!")
                    st.rerun()
        except json.JSONDecodeError as e:
            st.error(f"JSON 파싱 오류: {e}")
        except UnicodeDecodeError:
            st.error("파일 인코딩 오류: UTF-8 형식의 JSON 파일을 업로드하세요.")
        except Exception as e:
            st.error(f"파일 읽기 오류: {e}")