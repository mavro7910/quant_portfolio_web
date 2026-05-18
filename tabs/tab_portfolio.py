"""tabs/tab_portfolio.py — 보유 종목 관리 탭"""

import base64, json, re, hashlib as _hashlib
import pandas as pd
import streamlit as st

from core.data import fetch_prices_and_fx
from core.portfolio import Portfolio
from utils.ai_client import get_finnhub_key, has_finnhub_key, get_api_key, has_api_key
from utils.ui import (
    section_title, metric_card, banner, TEAL, TEAL_LIGHT, TEAL_DARK,
    TEXT, TEXT_SUB, TEXT_MUTED, BORDER, SURFACE, SURFACE_DIM, RED, RED_LIGHT,
)

_KR_TICKER_HINTS = {
    "알파벳 a":"GOOGL","알파벳a":"GOOGL","알파벳":"GOOGL",
    "ge 버노바":"GEV","ge버노바":"GEV",
    "tsmc(adr)":"TSM","tsmc":"TSM",
    "asml 홀딩(adr)":"ASML","asml홀딩(adr)":"ASML",
    "arm 홀딩스(adr)":"ARM","arm홀딩스(adr)":"ARM",
    "kla":"KLAC",
}

_KNOWN_ETF_TICKERS = {
    "DIA", "IWM", "QQQ", "QQQM", "SPY", "VGT", "VOO", "VTI", "XLK", "XOVR",
}

_TICKER_COLORS = {
    "AAPL":"#555","MSFT":"#0078d4","NVDA":"#76b900","AMZN":"#ff9900",
    "GOOGL":"#4285f4","META":"#1877f2","TSLA":"#cc0000","AVGO":TEAL,
    "MU":"#e00","AMD":"#ed1c24","COST":"#005daa","V":"#1a1f71",
    "MA":"#eb001b","TSM":"#0066cc","QCOM":"#3253dc",
}
_FALLBACK_COLORS = [
    "#0F6E56","#4a90d9","#c9873a","#8b72c8","#5ab87a",
    "#e05252","#a0b4b2","#3a8fc8","#c96a8b","#6a9e4a",
]


def _ticker_color(ticker: str, idx: int) -> str:
    return _TICKER_COLORS.get(ticker, _FALLBACK_COLORS[idx % len(_FALLBACK_COLORS)])


def _logo_or_abbr_html(ticker: str, logo_url: str | None, color: str, class_name: str) -> str:
    abbr = ticker[:2]
    if logo_url:
        return (
            f'<div class="{class_name}" style="background:#F7F8FA;color:{color}">'
            f'<img src="{logo_url}" alt="{ticker}" '
            f'style="width:100%;height:100%;object-fit:contain;padding:5px;border-radius:inherit" '
            f'onerror="this.remove();this.parentElement.textContent=\'{abbr}\'">'
            f'</div>'
        )
    return f'<div class="{class_name}" style="background:{color}15;color:{color}">{abbr}</div>'


def _extract_names_and_shares(uploaded_files, api_key):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    prompt = (
        '이미지에서 "숫자주" 패턴을 모두 찾고 각 수량 바로 위의 종목명/티커와 쌍으로 추출.\n'
        '티커가 화면에 보이면 ticker_guess에 넣고, ETF/펀드로 보이면 asset_type을 "ETF"로 표시.\n'
        'JSON만 응답:\n'
        '[{"name_kr":"브로드컴","ticker_guess":"AVGO","shares":0.284328,"asset_type":"STOCK"},...]'
    )
    model = genai.GenerativeModel("gemini-2.5-flash-lite")
    parts = []
    for f in uploaded_files:
        data = f.read()
        mime = f.type or "image/jpeg"
        parts.append({"mime_type": mime, "data": base64.b64encode(data).decode()})
    parts.append(prompt)
    response = model.generate_content(parts)
    raw = re.sub(r"```(?:json)?", "", response.text.strip()).strip().rstrip("`").strip()
    return json.loads(raw)


def _map_to_tickers(items, universe, api_key, ticker_names):
    import google.generativeai as genai
    genai.configure(api_key=api_key)
    universe_lines = []
    for t in universe:
        eng = (ticker_names or {}).get(t, "")
        universe_lines.append(f"  {t}: {eng}" if eng else f"  {t}")
    hints_str = "\n".join(f"  {k} -> {v}" for k, v in _KR_TICKER_HINTS.items())
    names_str = "\n".join(
        f"  {i+1}. name={item.get('name_kr','')}, ticker_guess={item.get('ticker_guess','')}"
        for i, item in enumerate(items)
    )
    prompt = (
        "아래 종목명/티커 후보를 미국 상장 티커로 매핑하세요. "
        "포트폴리오 티커 목록은 힌트일 뿐이며, 목록에 없는 새 티커도 보이면 그대로 반환하세요.\n\n"
        f"[현재 포트폴리오 티커]\n{chr(10).join(universe_lines)}\n\n"
        f"[힌트]\n{hints_str}\n\n"
        f"[매핑할 종목]\n{names_str}\n\n"
        'JSON만:\n[{"name_kr":"브로드컴","ticker":"AVGO"},...]'
    )
    model = genai.GenerativeModel("gemini-2.5-flash")
    response = model.generate_content(prompt)
    raw = re.sub(r"```(?:json)?", "", response.text.strip()).strip().rstrip("`").strip()
    mapping = json.loads(raw)
    map_dict = {m["name_kr"]: m.get("ticker") for m in mapping}
    result = []
    for item in items:
        ticker = (map_dict.get(item.get("name_kr")) or item.get("ticker_guess") or "").upper().strip()
        if ticker and re.match(r"^[A-Z][A-Z0-9.-]{0,9}$", ticker):
            result.append({
                "ticker": ticker,
                "name_kr": item.get("name_kr", ""),
                "shares": item["shares"],
                "asset_type": item.get("asset_type", "STOCK"),
            })
    return result


def _default_asset_type(ticker: str, name: str = "", raw_type: str = "STOCK") -> str:
    text = f"{ticker} {name} {raw_type}".upper()
    if raw_type.upper() == "ETF" or ticker.upper() in _KNOWN_ETF_TICKERS or "ETF" in text:
        return "ETF"
    return "STOCK"


def render(portfolio: Portfolio):
    def inv(*keys):
        for k in keys:
            st.session_state.pop(k, None)

    def render_management(expanded: bool = False):
        with st.expander("종목 관리", expanded=expanded):
            with st.form("portfolio_add_form", clear_on_submit=False):
                col_t, col_s, col_kind = st.columns([1, 1, 0.8])
                with col_t:
                    new_ticker = st.text_input("티커", placeholder="AAPL", key="inp_ticker").upper().strip()
                with col_s:
                    new_shares = st.number_input(
                        "보유 수량",
                        min_value=0.0,
                        max_value=9_999_999.0,
                        value=0.0,
                        step=0.000001,
                        format="%.6f",
                        key="inp_shares",
                    )
                with col_kind:
                    st.markdown('<div style="height:1.7rem"></div>', unsafe_allow_html=True)
                    new_is_etf = st.checkbox("ETF", key="inp_is_etf")
                if st.form_submit_button("추가/수정", type="primary", width="stretch"):
                    if new_ticker:
                        portfolio.set_holding(new_ticker, new_shares, "ETF" if new_is_etf else "STOCK")
                        portfolio.save()
                        inv("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result", "signal_cache")
                        st.success(f"{new_ticker} 저장 완료!")
                        st.rerun()
                    else:
                        st.error("티커를 입력하세요.")

            tickers_list = portfolio.tickers()
            if tickers_list:
                with st.form("portfolio_etf_form", clear_on_submit=False):
                    etf_selected = st.multiselect(
                        "ETF 별도 관리 종목",
                        options=tickers_list,
                        default=portfolio.etf_tickers(),
                        help="선택한 종목은 총 평가금액에는 포함되지만 QPM 분석, 백테스트, 리밸런싱, 매도 시그널에서는 제외됩니다.",
                    )
                    if st.form_submit_button("ETF 설정 저장", width="stretch"):
                        selected = set(etf_selected)
                        for ticker in tickers_list:
                            portfolio.set_asset_type(ticker, "ETF" if ticker in selected else "STOCK")
                        portfolio.save()
                        inv("buy_result", "bt_result", "rebal_result", "sell_result", "signal_cache")
                        st.success("ETF 설정이 저장되었습니다.")
                        st.rerun()

            with st.form("portfolio_delete_form", clear_on_submit=False):
                del_ticker = st.selectbox("삭제할 종목 선택", ["선택..."] + tickers_list, key="del_select")
                if st.form_submit_button("삭제", width="stretch"):
                    if del_ticker != "선택...":
                        portfolio.remove_holding(del_ticker)
                        portfolio.save()
                        inv("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result", "signal_cache")
                        st.success(f"{del_ticker} 삭제 완료!")
                        st.rerun()

        with st.expander("증권사 캡쳐로 업데이트", expanded=False):
            if not has_api_key():
                st.markdown(banner("Gemini API 키가 필요합니다. 설정 탭에서 등록하세요.", "warn"), unsafe_allow_html=True)
            else:
                st.markdown(banner(
                    "포트폴리오 화면을 캡쳐해서 올려주세요.<br>"
                    '<span style="font-size:0.78rem;opacity:0.8">여러 장 동시 업로드 가능 · 토스증권 앱에서 테스트됨</span>', "info"
                ), unsafe_allow_html=True)
                uploaded = st.file_uploader(
                    "이미지 업로드 (JPG/PNG)",
                    type=["jpg", "jpeg", "png"],
                    accept_multiple_files=True,
                    key="portfolio_img_uploader",
                )
                if uploaded:
                    if st.button("AI로 종목/수량 추출", key="btn_extract_img", width="stretch", type="primary"):
                        try:
                            with st.status("AI 분석 중...", expanded=True) as status:
                                st.write("1단계: 이미지에서 종목명·수량 추출 중...")
                                raw_items = _extract_names_and_shares(uploaded, get_api_key())
                                st.write(f"2단계: {len(raw_items)}개 종목명 → 티커 매핑 중...")
                                extracted = _map_to_tickers(raw_items, portfolio.tickers(), get_api_key(),
                                                            st.session_state.get("ticker_names"))
                                seen = {}
                                for item in extracted:
                                    t = item.get("ticker", "").upper().strip()
                                    if t:
                                        seen[t] = item
                                extracted = list(seen.values())
                                status.update(label=f"완료 · {len(extracted)}개 종목 추출", state="complete")
                            st.session_state["img_extracted"] = extracted
                        except Exception as e:
                            st.error(f"추출 실패: {e}")

            if "img_extracted" in st.session_state:
                extracted = st.session_state["img_extracted"]
                st.markdown(section_title("추출 결과 확인"), unsafe_allow_html=True)
                df_preview = pd.DataFrame([{
                    "티커": item.get("ticker", ""),
                    "한글명": item.get("name_kr", ""),
                    "자산 유형": portfolio.asset_type(item.get("ticker", ""))
                    if item.get("ticker", "") in portfolio.holdings
                    else _default_asset_type(
                        item.get("ticker", ""),
                        item.get("name_kr", ""),
                        item.get("asset_type", "STOCK"),
                    ),
                    "추출 수량": float(item.get("shares", 0.0)),
                    "현재 수량": portfolio.holdings.get(item.get("ticker", ""), 0.0),
                } for item in extracted])
                edited = st.data_editor(
                    df_preview,
                    column_config={
                        "티커": st.column_config.TextColumn("티커"),
                        "한글명": st.column_config.TextColumn("한글명", disabled=True),
                        "자산 유형": st.column_config.SelectboxColumn("자산 유형", options=["STOCK", "ETF"]),
                        "추출 수량": st.column_config.NumberColumn("추출 수량", format="%.6f"),
                        "현재 수량": st.column_config.NumberColumn("현재 수량 (기존)", format="%.6f", disabled=True),
                    },
                    hide_index=True,
                    width="stretch",
                    num_rows="fixed",
                    key="img_preview_editor",
                )
                extracted_tickers = {str(row["티커"]).upper().strip() for _, row in edited.iterrows() if row["티커"]}
                missing = [t for t in portfolio.holdings if t not in extracted_tickers and portfolio.holdings[t] > 0]
                if missing:
                    st.markdown(banner(f"이미지에 없는 종목은 수량이 <b>0</b>으로 변경됩니다: {', '.join(missing)}", "warn"), unsafe_allow_html=True)

                col_apply, col_cancel = st.columns([3, 1])
                with col_apply:
                    if st.button("포트폴리오에 반영", key="btn_apply_img", width="stretch", type="primary"):
                        applied = set()
                        for _, row in edited.iterrows():
                            t = str(row["티커"]).upper().strip()
                            if t:
                                portfolio.set_holding(t, float(row["추출 수량"]), str(row.get("자산 유형", "STOCK")))
                                applied.add(t)
                        zeroed = []
                        for t in list(portfolio.holdings.keys()):
                            if t not in applied and portfolio.holdings.get(t, 0) > 0:
                                portfolio.set_holding(t, 0.0)
                                zeroed.append(t)
                        portfolio.save()
                        inv("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result", "signal_cache")
                        del st.session_state["img_extracted"]
                        msg = f"{len(applied)}개 종목 업데이트"
                        if zeroed:
                            msg += f" · {len(zeroed)}개 0으로 초기화 ({', '.join(zeroed)})"
                        st.success(msg)
                        st.rerun()
                with col_cancel:
                    if st.button("취소", key="btn_cancel_img", width="stretch"):
                        del st.session_state["img_extracted"]
                        st.rerun()

    # ── 보유 종목 현황 ────────────────────────────────────
    holdings = portfolio.holdings
    strategy_tickers = portfolio.strategy_tickers()
    etf_tickers = portfolio.etf_tickers()
    if not holdings:
        st.markdown(banner("📋 보유 종목이 없습니다. 위에서 티커와 수량을 입력해 추가하세요.", "info"), unsafe_allow_html=True)
        render_management(expanded=True)
        return

    st.markdown(section_title("보유 종목 현황"), unsafe_allow_html=True)

    prices_cache = st.session_state.get("prices_data")
    fx           = prices_cache[1] if prices_cache else None
    prices_map   = prices_cache[0] if prices_cache else None
    fx_est       = prices_cache[2] if prices_cache else False

    st.markdown('<div class="qpm-update-bar-label">데이터</div>', unsafe_allow_html=True)
    col_btn_ref, col_btn_name, col_auto = st.columns([1, 1, 1.15], gap="small")
    with col_btn_ref:
        if st.button("시세 갱신", key="btn_refresh", type="primary"):
            with st.spinner("시세 가져오는 중..."):
                try:
                    prices, fx_new, fx_est_new = fetch_prices_and_fx(portfolio.tickers())
                    st.session_state["prices_data"] = (prices, fx_new, fx_est_new)
                    st.rerun()
                except Exception as e:
                    st.error(f"시세 조회 실패: {e}")
    with col_btn_name:
        if st.button("종목명 조회", key="btn_names"):
            with st.spinner("종목명 가져오는 중..."):
                import yfinance as yf, requests
                names = {}
                fh_key = get_finnhub_key() if has_finnhub_key() else None
                for t in portfolio.tickers():
                    name = None
                    if fh_key:
                        try:
                            r = requests.get("https://finnhub.io/api/v1/stock/profile2",
                                             params={"symbol":t}, headers={"X-Finnhub-Token":fh_key}, timeout=5)
                            profile = r.json()
                            name = profile.get("name") or None
                            logo = profile.get("logo") or None
                            if logo: portfolio.set_logo(t, logo)
                        except Exception: pass
                    if not name:
                        try:
                            info = yf.Ticker(t).info
                            name = info.get("longName") or info.get("shortName") or None
                        except Exception: pass
                    names[t] = name or t
                if fh_key: portfolio.save()
                st.session_state["ticker_names"] = names
    with col_auto:
        _saved_auto = portfolio.get_setting("auto_refresh_prices", False)
        auto_refresh = st.toggle("자동 갱신", value=st.session_state.get("auto_refresh_prices", _saved_auto), key="toggle_auto_refresh")
        if auto_refresh != st.session_state.get("auto_refresh_prices", _saved_auto):
            portfolio.set_setting("auto_refresh_prices", auto_refresh)
            portfolio.save()
        st.session_state["auto_refresh_prices"] = auto_refresh

    if auto_refresh and portfolio.tickers() and "prices_data" not in st.session_state:
        with st.spinner("시세 자동 갱신 중..."):
            try:
                prices, fx_new, fx_est_new = fetch_prices_and_fx(portfolio.tickers())
                st.session_state["prices_data"] = (prices, fx_new, fx_est_new)
                st.rerun()
            except Exception as e:
                st.warning(f"자동 갱신 실패: {e}")

    if fx_est:
        st.markdown(banner("⚠️ USD/KRW 환율 조회 실패 — 추정값 사용 중", "warn"), unsafe_allow_html=True)

    # ── 총액 우선 구조 + 메트릭 그리드 ─────────────────────
    if prices_map is not None:
        def _v(t): 
            try: return float(prices_map[t]) * holdings.get(t,0) * fx
            except: return 0.0
        total_krw = sum(_v(t) for t in holdings)
        total_usd = sum((lambda p: p * holdings.get(t,0))(float(prices_map[t])) 
                        for t in holdings if t in prices_map and prices_map[t] == prices_map[t]) if prices_map is not None else 0
        fx_label = "추정환율" if fx_est else "실시간"

        st.markdown(f"""
<div class="qpm-total-section">
  <div class="qpm-total-label">총 평가금액</div>
  <div class="qpm-total-value">₩{total_krw:,.0f}</div>
  <div class="qpm-total-sub">{fx_label} · USD ${total_usd:,.2f}</div>
</div>
<div class="qpm-metric-grid">
  {metric_card("보유 종목 수", f"{len(holdings)}개")}
  {metric_card("QPM 분석 대상", f"{len(strategy_tickers)}개", f"ETF {len(etf_tickers)}개 제외")}
  {metric_card("총 평가금액 (USD)", f"${total_usd:,.2f}" if total_usd else "—", "현재가 기준")}
  {metric_card("USD / KRW", f"{fx:,.2f}", "실시간" if not fx_est else "추정값")}
</div>
""", unsafe_allow_html=True)
    else:
        st.markdown(f"""
<div class="qpm-total-section">
  <div class="qpm-total-label">총 평가금액</div>
  <div class="qpm-total-value">—</div>
  <div class="qpm-total-sub">시세 갱신 후 평가금액을 확인할 수 있습니다</div>
</div>
<div class="qpm-metric-grid">
  {metric_card("보유 종목 수", f"{len(holdings)}개")}
  {metric_card("QPM 분석 대상", f"{len(strategy_tickers)}개", f"ETF {len(etf_tickers)}개 제외")}
  {metric_card("투자금", "—", "시세 갱신 필요")}
  {metric_card("USD / KRW", "—")}
</div>
""", unsafe_allow_html=True)

    # ── 종목 리스트 (HTML) — QPM 대상 + ETF 별도 관리 ─────────────────
    names_map = st.session_state.get("ticker_names", {})
    def _holding_value(item):
        t, s = item
        if prices_map is None:
            return 0.0
        try:
            p = float(prices_map.get(t, 0) or 0)
            return p * s * (fx or 1)
        except Exception:
            return 0.0

    qpm_items = sorted(
        [(t, s) for t, s in holdings.items() if not portfolio.is_etf(t)],
        key=lambda item: (_holding_value(item), item[0]),
        reverse=True,
    )
    etf_items = sorted(
        [(t, s) for t, s in holdings.items() if portfolio.is_etf(t)],
        key=lambda item: (_holding_value(item), item[0]),
        reverse=True,
    )
    show_all  = st.session_state.get("portfolio_show_all", False)
    visible   = qpm_items if show_all else qpm_items[:3]

    def _stock_item_html(idx, t, s):
        p = val = None
        if prices_map is not None:
            try:
                p   = float(prices_map[t])
                val = p * s * (fx or 1)
            except: pass
        color     = _ticker_color(t, idx)
        logo_html = _logo_or_abbr_html(t, portfolio.get_logo(t), color, "qpm-stock-icon")
        name_str  = names_map.get(t, "")
        type_badge = " · ETF · QPM 제외" if portfolio.is_etf(t) else ""
        price_str = f"${p:,.2f}" if p else "—"
        val_str   = f"₩{val:,.0f}" if val else "—"
        yf_url    = f"https://finance.yahoo.com/quote/{t}/"
        return f"""
<a href="{yf_url}" target="_blank" rel="noopener noreferrer" style="text-decoration:none;color:inherit;display:block">
<div class="qpm-stock-row" style="cursor:pointer">
  {logo_html}
  <div style="flex:1;min-width:0">
    <div class="qpm-stock-ticker">{t}</div>
    <div class="qpm-stock-shares">{s:.4f}주{" · " + name_str if name_str else ""}{type_badge}</div>
  </div>
  <div class="qpm-stock-price" style="text-align:right;flex-shrink:0">
    <div class="qpm-stock-price-main">{price_str}</div>
    <div class="qpm-stock-value">{val_str}</div>
  </div>
  <div style="margin-left:8px;opacity:0.35;font-size:0.8rem;align-self:center">↗</div>
</div>
</a>"""

    if qpm_items:
        items_html = "".join(_stock_item_html(i, t, s) for i, (t, s) in enumerate(visible))
        st.markdown(f"""
<div class="qpm-stock-list">
  {items_html}
</div>
""", unsafe_allow_html=True)

    remaining = len(qpm_items) - 3
    if not show_all and remaining > 0:
        left_spacer, center_action, right_spacer = st.columns([1, 1, 1], gap="small")
        with center_action:
            if st.button(f"{remaining}개 종목 더보기", key="btn_show_all_stocks"):
                st.session_state["portfolio_show_all"] = True
                st.rerun()
    elif show_all and len(qpm_items) > 3:
        left_spacer, center_action, right_spacer = st.columns([1, 1, 1], gap="small")
        with center_action:
            if st.button("접기", key="btn_hide_stocks"):
                st.session_state["portfolio_show_all"] = False
                st.rerun()

    if etf_items:
        st.markdown(section_title("ETF 별도 관리"), unsafe_allow_html=True)
        etf_html = "".join(_stock_item_html(i, t, s) for i, (t, s) in enumerate(etf_items))
        st.markdown(f"""
<div class="qpm-stock-list">
  {etf_html}
</div>
""", unsafe_allow_html=True)

    render_management(expanded=False)

    # ── 인터랙티브 수량 편집 테이블 ───────────────────────
    st.markdown(section_title("수량 직접 편집"), unsafe_allow_html=True)
    df_hold = pd.DataFrame([{
        "티커": t, "보유 수량": s,
        "현재가 (USD)": (float(prices_map[t]) if prices_map is not None and t in prices_map else None),
        "평가금액 (KRW)": (float(prices_map[t]) * s * (fx or 1) if prices_map is not None and t in prices_map else None),
    } for t, s in holdings.items()])

    if names_map:
        df_hold.insert(1, "종목명", df_hold["티커"].map(names_map))

    _ticker_hash = _hashlib.md5(",".join(sorted(holdings.keys())).encode()).hexdigest()[:8]
    edited_df = st.data_editor(
        df_hold,
        column_config={
            "현재가 (USD)":   st.column_config.NumberColumn(format="$%.2f"),
            "평가금액 (KRW)": st.column_config.NumberColumn(format="₩%.0f"),
            "보유 수량":      st.column_config.NumberColumn(format="%.6f"),
        },
        disabled=[c for c in df_hold.columns if c != "보유 수량"],
        width="stretch", hide_index=True,
        key=f"hold_editor_{_ticker_hash}",
    )
    changed = False
    for _, row in edited_df.iterrows():
        t = row["티커"]
        new_s = float(row["보유 수량"])
        if abs(new_s - holdings.get(t, 0.0)) > 1e-9:
            portfolio.set_holding(t, new_s)
            changed = True
    if changed:
        portfolio.save()
        inv("buy_result","bt_result","rebal_result","sell_result","signal_cache")
