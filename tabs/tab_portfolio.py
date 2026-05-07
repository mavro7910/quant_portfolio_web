"""tabs/tab_portfolio.py — 보유 종목 관리 탭"""

import base64
import json
import re

import pandas as pd
import streamlit as st

from core.data import fetch_prices_and_fx
from core.portfolio import Portfolio
from utils.ai_client import get_finnhub_key, has_finnhub_key, get_api_key, has_api_key


# ─────────────────────────────────────────────
# 한글 종목명 → 티커 힌트 (Gemini 보조용)
# ─────────────────────────────────────────────

_KR_TICKER_HINTS = {
    "알파벳 a": "GOOGL", "알파벳a": "GOOGL", "알파벳": "GOOGL",  # GOOG vs GOOGL
    "ge 버노바": "GEV", "ge버노바": "GEV",                        # 신규 분사 종목
    "tsmc(adr)": "TSM", "tsmc": "TSM",                           # ADR 표기
    "asml 홀딩(adr)": "ASML", "asml홀딩(adr)": "ASML",           # ADR 표기
    "arm 홀딩스(adr)": "ARM", "arm홀딩스(adr)": "ARM",            # ADR 표기
    "kla": "KLAC",                                                # 표기명과 티커 불일치
}


# ─────────────────────────────────────────────
# Gemini Vision 추출
# ─────────────────────────────────────────────

def _fetch_ticker_names(tickers: list[str]) -> dict[str, str]:
    """yfinance로 티커 → 영문 회사명 매핑 (캐시 활용)."""
    cached = st.session_state.get("_ticker_names_cache", {})
    missing = [t for t in tickers if t not in cached]

    if missing:
        import yfinance as yf
        for t in missing:
            try:
                info = yf.Ticker(t).info
                name = info.get("shortName") or info.get("longName") or t
                cached[t] = name
            except Exception:
                cached[t] = t
        st.session_state["_ticker_names_cache"] = cached

    return {t: cached.get(t, t) for t in tickers}


def _parse_portfolio_images(uploaded_files: list, api_key: str, universe: list[str]) -> list[dict]:
    """Gemini Vision으로 캡쳐 이미지(여러 장)에서 종목/수량 추출."""
    import google.generativeai as genai
    genai.configure(api_key=api_key)

    # 포트폴리오 티커 → 영문 회사명 매핑
    name_map = _fetch_ticker_names(universe)
    universe_str = "\n".join(f"  {ticker}: {name}" for ticker, name in name_map.items())

    hints_str = "\n".join(f"  {k} -> {v}" for k, v in _KR_TICKER_HINTS.items())

    prompt = f"""이미지에서 "숫자주" 패턴(예: 0.409813주, 1.23456주)을 모두 찾고,
각 수량 바로 위에 있는 종목명과 쌍으로 추출하세요.
여러 장에 같은 종목이 있으면 마지막 이미지 기준으로 사용하세요.

아래는 포트폴리오 티커와 영문 회사명입니다. 이미지의 종목명을 이 목록의 티커로 매핑하세요:
{universe_str}

추가 참고 매핑 (한글명 → 티커):
{hints_str}

JSON만 응답, 코드블록 없이:
[{{"ticker":"AAPL","shares":0.409813,"name_kr":"애플"}}, ...]"""

    model = genai.GenerativeModel("gemini-2.5-flash-lite")

    parts = []
    for f in uploaded_files:
        data = f.read()
        mime = f.type or "image/jpeg"
        parts.append({"mime_type": mime, "data": base64.b64encode(data).decode()})
    parts.append(prompt)

    response = model.generate_content(parts)
    raw = response.text.strip()
    raw = re.sub(r"```(?:json)?", "", raw).strip().rstrip("`").strip()
    return json.loads(raw)


# ─────────────────────────────────────────────
# 렌더
# ─────────────────────────────────────────────

def render(portfolio: Portfolio):
    def invalidate_cache(*keys):
        for k in keys:
            if k in st.session_state:
                del st.session_state[k]

    st.markdown('<div class="section-label">보유 종목 관리</div>', unsafe_allow_html=True)

    # ── 수동 추가/수정 ────────────────────────────────────────────
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

    # ── 삭제 ─────────────────────────────────────────────────────
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

    # ── 캡쳐 업로드로 업데이트 ───────────────────────────────────
    with st.expander("📸 증권사 캡쳐로 포트폴리오 업데이트", expanded=False):
        if not has_api_key():
            st.markdown(
                '<div class="warn-banner">🔑 Gemini API 키가 필요합니다. 설정 탭에서 등록하세요.</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(
                '<div class="info-banner">'
                '📱 포트폴리오 화면을 캡쳐해서 올려주세요.<br>'
                '<span style="font-size:0.8rem;color:#5c6f99">'
                '여러 장 동시 업로드 가능 · 이미지에 있는 종목 수량만 덮어씌워집니다<br>'
                '⚠️ AI 인식 결과는 반드시 확인 후 반영하세요 · 토스증권 앱에서 테스트됨'
                '</span>'
                '</div>',
                unsafe_allow_html=True,
            )

            uploaded = st.file_uploader(
                "이미지 업로드 (JPG/PNG)",
                type=["jpg", "jpeg", "png"],
                accept_multiple_files=True,
                key="portfolio_img_uploader",
            )

            if uploaded:
                if st.button("🔍 AI로 종목/수량 추출", key="btn_extract_img", use_container_width=True):
                    with st.spinner("Gemini Vision으로 분석 중..."):
                        try:
                            extracted = _parse_portfolio_images(uploaded, get_api_key(), portfolio.tickers())
                            # 유니버스 필터: 포트폴리오에 없는 티커 제거
                            universe = set(portfolio.tickers())
                            extracted = [e for e in extracted if e.get("ticker", "").upper().strip() in universe]
                            # 중복 티커 제거 (같은 티커면 마지막 것만 유지)
                            seen = {}
                            for item in extracted:
                                ticker = item.get("ticker", "").upper().strip()
                                if ticker:
                                    seen[ticker] = item
                            extracted = list(seen.values())
                            st.session_state["img_extracted"] = extracted
                        except Exception as e:
                            st.error(f"추출 실패: {e}")

        # ── 추출 결과 검토 ──────────────────────────────────────
        if "img_extracted" in st.session_state:
            extracted = st.session_state["img_extracted"]

            st.markdown(
                '<div class="section-label" style="margin-top:14px">'
                '✏️ 추출 결과 확인 · 수정 후 반영하세요'
                '</div>',
                unsafe_allow_html=True,
            )
            st.markdown(
                '<div class="info-banner" style="font-size:0.8rem">'
                '티커나 수량이 잘못 인식된 경우 직접 수정할 수 있습니다.'
                '</div>',
                unsafe_allow_html=True,
            )

            df_preview = pd.DataFrame([
                {
                    "티커":      item.get("ticker", ""),
                    "한글명":    item.get("name_kr", ""),
                    "추출 수량": float(item.get("shares", 0.0)),
                    "현재 수량": portfolio.holdings.get(item.get("ticker", ""), 0.0),
                }
                for item in extracted
            ])

            edited = st.data_editor(
                df_preview,
                column_config={
                    "티커":      st.column_config.TextColumn("티커", help="잘못된 경우 수정하세요"),
                    "한글명":    st.column_config.TextColumn("한글명", disabled=True),
                    "추출 수량": st.column_config.NumberColumn("추출 수량", format="%.6f",
                                                               help="잘못 인식된 경우 수정하세요"),
                    "현재 수량": st.column_config.NumberColumn("현재 수량 (기존)", format="%.6f",
                                                               disabled=True),
                },
                hide_index=True,
                use_container_width=True,
                num_rows="fixed",
                key="img_preview_editor",
            )

            # 이미지에 없는 기존 종목 → 0으로 표시 (미리보기용)
            extracted_tickers = {str(row["티커"]).upper().strip() for _, row in edited.iterrows() if row["티커"]}
            missing = [t for t in portfolio.holdings if t not in extracted_tickers and portfolio.holdings[t] > 0]
            if missing:
                st.markdown(
                    f'<div class="warn-banner" style="font-size:0.82rem">'
                    f'⚠️ 이미지에 없는 종목은 수량이 <b>0</b>으로 변경됩니다: '
                    f'{", ".join(missing)}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

            col_apply, col_cancel = st.columns([3, 1])
            with col_apply:
                if st.button("✅ 포트폴리오에 반영", key="btn_apply_img", use_container_width=True):
                    updated = []
                    applied_tickers = set()

                    # 추출된 종목 덮어씌우기
                    for _, row in edited.iterrows():
                        ticker = str(row["티커"]).upper().strip()
                        shares = float(row["추출 수량"])
                        if ticker:
                            portfolio.set_holding(ticker, shares)
                            applied_tickers.add(ticker)
                            updated.append(f"{ticker} {shares:.6f}주")

                    # 이미지에 없는 기존 종목 → 0
                    zeroed = []
                    for t in list(portfolio.holdings.keys()):
                        if t not in applied_tickers and portfolio.holdings.get(t, 0) > 0:
                            portfolio.set_holding(t, 0.0)
                            zeroed.append(t)

                    portfolio.save()
                    invalidate_cache("prices_data", "buy_result", "bt_result", "rebal_result", "signal_cache")
                    del st.session_state["img_extracted"]

                    msg = f"✅ {len(updated)}개 종목 업데이트"
                    if zeroed:
                        msg += f" · {len(zeroed)}개 0으로 초기화 ({', '.join(zeroed)})"
                    st.success(msg)
                    st.rerun()
            with col_cancel:
                if st.button("❌ 취소", key="btn_cancel_img", use_container_width=True):
                    del st.session_state["img_extracted"]
                    st.rerun()

    # ─────────────────────────────────────────────
    # 보유 종목 현황
    # ─────────────────────────────────────────────

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