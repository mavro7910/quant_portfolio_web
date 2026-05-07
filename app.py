"""
app.py — Quant Portfolio Manager 진입점

탭별 로직은 tabs/ 폴더에 분리되어 있습니다:
  tabs/tab_portfolio.py   — 보유 종목 관리
  tabs/tab_ai_signal.py   — AI 시그널 (Gemini)
  tabs/tab_buyrec.py      — 매수 추천
  tabs/tab_backtest.py    — 백테스트
  tabs/tab_sell_signal.py — 매도 신호
  tabs/tab_rebalance.py   — 리밸런싱
  tabs/tab_settings.py    — 설정
"""

import hashlib
import sys
import os
from pathlib import Path

import streamlit as st
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(os.getcwd())))

from core.portfolio import Portfolio
from utils.styles import inject_css
from tabs import tab_portfolio
from tabs import tab_ai_signal
from tabs import tab_buyrec
from tabs import tab_backtest
from tabs import tab_sell_signal
from tabs import tab_rebalance
from tabs import tab_settings

# ─────────────────────────────────────────────
# 페이지 설정
# ─────────────────────────────────────────────

_icon = Image.open(Path(os.getcwd()) / "assets" / "icon.png")
_icon = _icon.resize((64, 64))

st.set_page_config(
    page_title="Quant Portfolio Manager",
    page_icon=_icon,
    layout="wide",
    initial_sidebar_state="collapsed",
)

inject_css()

# ─────────────────────────────────────────────
# 유틸
# ─────────────────────────────────────────────

def email_to_key(email: str) -> str:
    return hashlib.sha256(email.lower().encode()).hexdigest()[:16]


def invalidate_cache(*keys):
    for k in keys:
        st.session_state.pop(k, None)

# ─────────────────────────────────────────────
# Google 로그인 게이트
# ─────────────────────────────────────────────

if not st.user.is_logged_in:
    st.markdown("""
    <div class="main-header">
        <div style="font-size:2.2rem">📊</div>
        <div>
            <h1>Quant Portfolio Manager</h1>
            <p>팩터 가중 모멘텀 전략 · 백테스트 · AI 시그널</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
    st.markdown("""
    <div class="info-banner">
        🔐 <b>로그인이 필요합니다</b><br>
        Google 계정으로 로그인하면 어떤 기기에서든 동일한 포트폴리오 데이터를 사용할 수 있습니다.
    </div>
    """, unsafe_allow_html=True)
    col_login, _ = st.columns([1, 3])
    with col_login:
        if st.button("🔑 Google로 로그인", key="btn_login"):
            st.login("google")
    st.stop()

# ─────────────────────────────────────────────
# 로그인 성공 → 포트폴리오 로드
# ─────────────────────────────────────────────

_user_email = st.user.email or st.user.get("sub", "unknown")
_user_name  = st.user.get("name", _user_email)
_file_key   = email_to_key(_user_email)

if "portfolio" not in st.session_state or st.session_state.get("_user_email") != _user_email:
    data_path = Path(os.getcwd()) / "data" / f"portfolio_{_file_key}.json"
    st.session_state.portfolio  = Portfolio(path=data_path)
    st.session_state["_user_email"] = _user_email
    invalidate_cache("prices_data", "buy_result", "bt_result", "rebal_result", "sell_result")

portfolio: Portfolio = st.session_state.portfolio

# ─────────────────────────────────────────────
# API 키 자동 로드 (세션 시작 시 1회)
# ─────────────────────────────────────────────

from utils.ai_client import (
    has_api_key, set_api_key,
    has_finnhub_key, set_finnhub_key,
    has_marketaux_key, set_marketaux_key,
)
from core.secrets_store import load_api_key, load_finnhub_key, load_marketaux_key

if not has_api_key():
    _k, _ = load_api_key(_file_key)
    if _k:
        set_api_key(_k)

if not has_finnhub_key():
    _k, _ = load_finnhub_key(_file_key)
    if _k:
        set_finnhub_key(_k)

if not has_marketaux_key():
    _k, _ = load_marketaux_key(_file_key)
    if _k:
        set_marketaux_key(_k)

# ─────────────────────────────────────────────
# 헤더
# ─────────────────────────────────────────────

col_header, col_user = st.columns([5, 1])
with col_header:
    st.markdown("""
    <div class="main-header">
        <div style="font-size:2.2rem">📊</div>
        <div>
            <h1>Quant Portfolio Manager</h1>
            <p>팩터 가중 모멘텀 전략 · 백테스트 · AI 시그널</p>
        </div>
    </div>
    """, unsafe_allow_html=True)
with col_user:
    st.markdown(f"""
    <div style="text-align:right; padding-top:8px; font-size:0.82rem; color:#90caf9;">
        👤 {_user_name}<br>
        <span style="font-size:0.75rem; color:#5c6f99;">{_user_email}</span>
    </div>
    """, unsafe_allow_html=True)
    if st.button("로그아웃", key="btn_logout"):
        st.logout()

# ─────────────────────────────────────────────
# 탭
# ─────────────────────────────────────────────

tab_port, tab_sig, tab_buy, tab_bt, tab_sell, tab_rebal, tab_cfg = st.tabs([
    "📋 포트폴리오",
    "📡 AI 시그널",
    "🧮 매수 추천",
    "📈 백테스트",
    "🚨 매도 신호",
    "⚖️ 리밸런싱",
    "⚙️ 설정",
])

with tab_port:
    tab_portfolio.render(portfolio)

with tab_sig:
    tab_ai_signal.render(portfolio, _file_key)

with tab_buy:
    tab_buyrec.render(portfolio)

with tab_bt:
    tab_backtest.render(portfolio)

with tab_sell:
    tab_sell_signal.render(portfolio)

with tab_rebal:
    tab_rebalance.render(portfolio)

with tab_cfg:
    tab_settings.render(portfolio, _user_email, _user_name, _file_key)