"""tabs/tab_portfolio.py — 보유 종목 관리 탭"""

import pandas as pd
import streamlit as st

from core.data import fetch_prices_and_fx
from core.portfolio import Portfolio
from utils.ai_client import get_finnhub_key, has_finnhub_key


def render(portfolio: Portfolio):
    def invalidate_cache(*keys):
        for k in keys:
            if k in st.session_state:
                del st.session_state[k]

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
                invalidate_cache("prices_data", "buy_result", "bt_result", "signal_cache")
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
                invalidate_cache("prices_data", "buy_result", "bt_result", "signal_cache")
                st.success(f"{del_ticker} 삭제 완료!")
                st.rerun()

    holdings = portfolio.holdings
    if not holdings:
        st.info("보유 종목이 없습니다. 위에서 티커와 수량을 입력해 추가하세요.")
        return

    st.markdown('<div class="section-label">보유 종목 현황</div>', unsafe_allow_html=True)

    prices_cache = st.session_state.get("prices_data", None)
    fx           = prices_cache[1] if prices_cache else None
    prices_map   = prices_cache[0] if prices_cache else None
    fx_est       = prices_cache[2] if prices_cache else False

    def build_df_hold(holdings_dict, prices_map, fx):
        rows = []
        for t, s in holdings_dict.items():
            p = val = None
            if prices_map is not None:
                try:
                    p   = float(prices_map[t])
                    val = p * s * fx
                except (KeyError, TypeError, ValueError):
                    pass
            rows.append({"티커": t, "보유 수량": s, "현재가 (USD)": p, "평가금액 (KRW)": val})
        return pd.DataFrame(rows)

    df_hold = build_df_hold(holdings, prices_map, fx)

    hold_col_cfg = {
        "현재가 (USD)":   st.column_config.NumberColumn(format="$%.2f"),
        "평가금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
        "보유 수량":      st.column_config.NumberColumn(format="%.6f"),
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
                import requests
                names = {}
                finnhub_key = get_finnhub_key() if has_finnhub_key() else None

                for t in portfolio.tickers():
                    name = None

                    # Finnhub 우선 (빠르고 정확) — 이름 + 로고 동시
                    if finnhub_key:
                        try:
                            r = requests.get(
                                "https://finnhub.io/api/v1/stock/profile2",
                                params={"symbol": t},
                                headers={"X-Finnhub-Token": finnhub_key},
                                timeout=5,
                            )
                            profile = r.json()
                            name = profile.get("name") or None
                            logo = profile.get("logo") or None
                            if logo:
                                portfolio.set_logo(t, logo)
                        except Exception:
                            pass

                    # yfinance fallback
                    if not name:
                        try:
                            info = yf.Ticker(t).info
                            name = info.get("longName") or info.get("shortName") or None
                        except Exception:
                            pass

                    names[t] = name or t

                if finnhub_key:
                    portfolio.save()
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
        width="stretch",
        hide_index=True,
        key="hold_editor",
    )

    for _, row in edited_df.iterrows():
        t          = row["티커"]
        new_shares = float(row["보유 수량"])
        if abs(new_shares - holdings.get(t, 0.0)) > 1e-9:
            portfolio.set_holding(t, new_shares)
            portfolio.save()
            invalidate_cache("buy_result", "bt_result", "rebal_result", "signal_cache")
            st.rerun()