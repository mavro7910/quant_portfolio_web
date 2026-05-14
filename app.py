"""app.py — QPM Alpha 진입점"""

import hashlib, sys, os
from pathlib import Path

import streamlit as st
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(os.getcwd())))

from core.portfolio import Portfolio
from utils.ui import inject_all, HEADER_GRAD, BORDER, TEAL, TEXT, TEXT_SUB, TEXT_MUTED, SURFACE, ICON_B64
from tabs import (
    tab_portfolio, tab_ai_signal, tab_buyrec,
    tab_backtest, tab_sell_signal, tab_rebalance, tab_settings,
)

_icon_path = Path(os.getcwd()) / "assets" / "icon.png"
try:    _icon = Image.open(_icon_path).resize((64, 64))
except: _icon = "📊"

st.set_page_config(
    page_title="QPM Alpha",
    page_icon=_icon,
    layout="wide",
    initial_sidebar_state="collapsed",
)
inject_all()


def email_to_key(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]

def invalidate_cache(*keys):
    for k in keys: st.session_state.pop(k, None)


# ── 로그인 게이트 ────────────────────────────────────────
if not st.user.is_logged_in:
    st.markdown(f"""
<div style="background:{HEADER_GRAD};border:0.5px solid {BORDER};border-radius:14px;
            padding:20px 24px;margin-bottom:20px;display:flex;align-items:center;gap:14px">
  <img src="{ICON_B64}" width="44" height="44"
       style="border-radius:10px"
       onerror="this.style.display='none'">
  <div>
    <div style="font-size:1.4rem;font-weight:700;color:{TEXT}">
      QPM <span style="color:{TEAL}">Alpha</span>
    </div>
    <div style="font-size:0.78rem;color:{TEXT_MUTED};margin-top:2px">
      Quantitative Portfolio Manager · Factor Momentum Strategy
    </div>
  </div>
</div>
""", unsafe_allow_html=True)
    st.markdown(
        f'<div style="background:#eef5ff;border:0.5px solid rgba(60,120,210,0.18);border-radius:10px;'
        f'padding:12px 16px;color:#2a5090;font-size:0.84rem;margin-bottom:16px">'
        f'🔐 <b>로그인이 필요합니다</b><br>'
        f'Google 계정으로 로그인하면 어떤 기기에서든 동일한 포트폴리오를 사용할 수 있습니다.</div>',
        unsafe_allow_html=True,
    )
    col_login, _ = st.columns([1, 3])
    with col_login:
        if st.button("Google로 로그인", key="btn_login"):
            st.login("google")
    st.stop()


# ── 포트폴리오 로드 ───────────────────────────────────────
_user_email = st.user.email or st.user.get("sub", "unknown")
_user_name  = st.user.get("name", _user_email)
_file_key   = email_to_key(_user_email)

if "portfolio" not in st.session_state or st.session_state.get("_user_email") != _user_email:
    data_path = Path(os.getcwd()) / "data" / f"portfolio_{_file_key}.json"
    st.session_state.portfolio      = Portfolio(path=data_path)
    st.session_state["_user_email"] = _user_email
    invalidate_cache("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result")

portfolio: Portfolio = st.session_state.portfolio

# ── API 키 자동 로드 ──────────────────────────────────────
from utils.ai_client import (
    has_api_key, set_api_key, has_finnhub_key, set_finnhub_key,
    has_marketaux_key, set_marketaux_key,
)
from core.secrets_store import load_api_key, load_finnhub_key, load_marketaux_key

if not has_api_key():
    _k, _ = load_api_key(_file_key)
    if _k: set_api_key(_k)
if not has_finnhub_key():
    _k, _ = load_finnhub_key(_file_key)
    if _k: set_finnhub_key(_k)
if not has_marketaux_key():
    _k, _ = load_marketaux_key(_file_key)
    if _k: set_marketaux_key(_k)


# ── 헤더 ─────────────────────────────────────────────────
initials = "".join(p[0].upper() for p in _user_name.split()[:2]) if _user_name else "U"

st.markdown(f"""
<div style="background:{HEADER_GRAD};border:0.5px solid {BORDER};border-radius:14px;
            padding:14px 20px;margin-bottom:14px;
            display:flex;align-items:center;justify-content:space-between">
  <div style="display:flex;align-items:center;gap:11px">
    <img src="{ICON_B64}" width="36" height="36"
         style="border-radius:9px;box-shadow:0 1px 4px rgba(26,158,143,0.18)"
         onerror="this.style.display='none'">
    <div>
      <div style="font-size:1.2rem;font-weight:700;color:{TEXT};letter-spacing:-0.2px">
        QPM <span style="color:{TEAL}">Alpha</span>
      </div>
      <div style="font-size:0.75rem;color:{TEXT_MUTED};margin-top:1px">
        Quantitative Portfolio Manager · Factor Momentum Strategy
      </div>
    </div>
  </div>
  <div style="display:flex;align-items:center;gap:8px">
    <div style="display:inline-flex;align-items:center;gap:6px;
                background:rgba(255,255,255,0.8);border:0.5px solid rgba(26,158,143,0.2);
                border-radius:20px;padding:4px 10px 4px 6px">
      <div style="width:22px;height:22px;border-radius:50%;background:#d8f3ef;
                  display:flex;align-items:center;justify-content:center;
                  font-size:10px;font-weight:700;color:{TEAL}">{initials}</div>
      <span style="font-size:0.76rem;color:{TEXT_SUB}">{_user_email}</span>
    </div>
  </div>
</div>
""", unsafe_allow_html=True)

# 로그아웃 버튼 — 헤더 우측에 붙이기 위해 absolute 불가 → 별도 컬럼
_hcol1, _hcol2 = st.columns([8, 1])
with _hcol2:
    if st.button("로그아웃", key="btn_logout"):
        st.logout()

# ── 탭 ───────────────────────────────────────────────────
tab_port, tab_sig, tab_buy, tab_bt, tab_sell, tab_rebal, tab_cfg = st.tabs([
    "📋 포트폴리오", "📡 AI 시그널", "🧮 매수 추천",
    "📈 백테스트",   "🚨 매도 신호",  "⚖️ 리밸런싱", "⚙️ 설정",
])

with tab_port:  tab_portfolio.render(portfolio)
with tab_sig:   tab_ai_signal.render(portfolio, _file_key)
with tab_buy:   tab_buyrec.render(portfolio)
with tab_bt:    tab_backtest.render(portfolio)
with tab_sell:  tab_sell_signal.render(portfolio)
with tab_rebal: tab_rebalance.render(portfolio)
with tab_cfg:   tab_settings.render(portfolio, _user_email, _user_name, _file_key)
