"""
tabs/tab_ai_signal.py

AI 시그널 탭.
- Gemini API로 보유 종목 뉴스 분석
- 토스증권 스타일 HTML 컴포넌트로 렌더링 (st.components.v1.html)
- 하루 단위 session_state 캐시로 API 비용 절약
"""

from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor, as_completed
# date, datetime, timedelta를 가져옵니다.
from datetime import date, datetime, timedelta

import streamlit as st
import streamlit.components.v1 as components

from core.portfolio import Portfolio
from utils.ai_client import (
    analyze_portfolio_signals,
    get_api_key, has_api_key, set_api_key,
    get_finnhub_key, set_finnhub_key, has_finnhub_key,
    get_marketaux_key, set_marketaux_key, has_marketaux_key,
)
from core.secrets_store import (
    load_api_key, load_signal_cache, save_signal_cache,
    load_finnhub_key, load_marketaux_key,
)


# ─────────────────────────────────────────────
# 헬퍼 함수: 한국 시간 생성
# ─────────────────────────────────────────────
def get_kst_now():
    """서버(UTC) 시간에 9시간을 더해 한국 시간을 반환"""
    return datetime.utcnow() + timedelta(hours=9)


# ─────────────────────────────────────────────
# 캐시 (Supabase + session_state 이중화)
# ─────────────────────────────────────────────

def _get_cached(uid: str) -> list | None:
    # date.today() 대신 한국 시간 기준 날짜로 키 생성
    kst_today = get_kst_now().date().isoformat()
    key = f"signal_cache_{kst_today}"
    
    if key in st.session_state:
        return st.session_state[key]
    
    data, err = load_signal_cache(uid)
    if data:
        st.session_state[key] = data
    return data


def _set_cached(uid: str, data: list):
    # 저장할 때도 한국 시간 기준 날짜로 키 생성
    kst_today = get_kst_now().date().isoformat()
    key = f"signal_cache_{kst_today}"
    
    st.session_state[key] = data
    ok, err = save_signal_cache(uid, data)
    if not ok:
        st.warning(f"⚠️ 분석 결과 저장 실패: {err}")


# ─────────────────────────────────────────────
# 렌더 진입점
# ─────────────────────────────────────────────

def render(portfolio: Portfolio, file_key: str):
    if not has_finnhub_key():
        stored_fh, _ = load_finnhub_key(file_key)
        if stored_fh:
            set_finnhub_key(stored_fh)

    if not has_marketaux_key():
        stored_mx, _ = load_marketaux_key(file_key)
        if stored_mx:
            set_marketaux_key(stored_mx)

    if not has_api_key():
        stored, err = load_api_key(file_key)
        if stored:
            set_api_key(stored)
        else:
            col_key, col_keybtn = st.columns([4, 1])
            with col_key:
                if err:
                    st.warning(f"키 자동 로드 실패: {err}")
                else:
                    st.markdown(
                        '<div class="warn-banner">🔑 API 키가 없습니다. 설정 탭에서 등록하거나 불러오세요.</div>',
                        unsafe_allow_html=True,
                    )
            with col_keybtn:
                st.markdown('<div style="height:0.4rem"></div>', unsafe_allow_html=True)
                if st.button("🔑 키 불러오기", key="btn_load_key", use_container_width=True):
                    stored2, err2 = load_api_key(file_key)
                    if stored2:
                        set_api_key(stored2)
                        st.rerun()
                    elif err2:
                        st.error(f"불러오기 실패: {err2}")
                    else:
                        st.error("저장된 키가 없습니다. 설정 탭에서 등록하세요.")

    if not portfolio.tickers():
        st.markdown(
            '<div class="info-banner">📋 포트폴리오 탭에서 종목을 먼저 추가하세요.</div>',
            unsafe_allow_html=True,
        )
        return

    active_holdings = {t: s for t, s in portfolio.holdings.items() if s > 0}
    if not active_holdings:
        st.markdown(
            '<div class="warn-banner">⚠️ 보유 중인 종목이 없어요. 포트폴리오 탭에서 수량을 입력해주세요.</div>',
            unsafe_allow_html=True,
        )
        return

    if not has_api_key():
        st.markdown(
            '<div class="warn-banner">'
            '🔑 <b>Gemini API 키가 필요합니다.</b><br>'
            '설정 탭에서 API 키를 입력하세요.<br>'
            '<a href="https://aistudio.google.com/app/apikey" target="_blank" '
            'style="color:#f0a862">Google AI Studio에서 무료 발급 →</a>'
            '</div>',
            unsafe_allow_html=True,
        )
        return

    cached = _get_cached(file_key)
    ticker_count = len(portfolio.tickers())

    if cached:
        analyzed_count = len(cached)
        # 캐시된 데이터에서 날짜와 시간을 가져옴
        analyzed_date  = cached[0].get("analyzed_date", "-") if cached else "-"
        analyzed_time  = cached[0].get("analyzed_time", "") if cached else ""
        time_str = f" {analyzed_time}" if analyzed_time else ""
        st.markdown(
            f'<div class="success-banner">'
            f'✅ 분석 결과 로드됨 · <b>{analyzed_count}개 종목</b> · '
            f'{analyzed_date}{time_str} 기준'
            f'</div>',
            unsafe_allow_html=True,
        )
    else:
        active_count = len([t for t, s in portfolio.holdings.items() if s > 0])
        st.markdown(
            f'<div class="info-banner">'
            f'📡 보유 수량이 있는 <b>{active_count}개 종목</b>의 최신 뉴스를 AI가 분석합니다.<br>'
            f'<span style="font-size:0.8rem;color:#5c6f99">'
            f'분석 완료 후 결과가 저장됩니다</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

    col_btn1, col_btn2, col_btn3 = st.columns([1, 1, 1])
    with col_btn1:
        run_signal = st.button(
            "🔄 스마트 재분석" if cached else "🔍 시그널 분석",
            key="btn_run_signal",
            use_container_width=True,
            help="변동이 큰 종목만 재분석, 나머지는 캐시 사용" if cached else None,
        )
    with col_btn2:
        run_full = st.button(
            "🔃 전체 재분석",
            key="btn_run_full",
            use_container_width=True,
            disabled=not cached,
            help="모든 종목을 강제로 재분석",
        )
    with col_btn3:
        if st.button("📂 저장된 결과 불러오기", key="btn_load_cache", use_container_width=True):
            data, err = load_signal_cache(file_key)
            if data:
                _set_cached(file_key, data)
                st.rerun()
            elif err:
                st.error(f"불러오기 실패: {err}")
            else:
                st.info("저장된 분석 결과가 없습니다.")

    if run_signal:
        _run_analysis(portfolio, file_key, force_full=False)
        cached = _get_cached(file_key)

    if run_full:
        _run_analysis(portfolio, file_key, force_full=True)
        cached = _get_cached(file_key)

    if cached:
        _render_signal_html(cached)


# ─────────────────────────────────────────────
# 분석 실행
# ─────────────────────────────────────────────

def _run_analysis(portfolio: Portfolio, file_key: str, force_full: bool = False):
    api_key      = get_api_key()
    holdings     = {t: s for t, s in portfolio.holdings.items() if s > 0}
    total        = len(holdings)

    # 스마트 캐시: 당일 기존 결과 로드 (강제 전체 재분석이 아닐 때)
    cached_results = None
    if not force_full:
        cached_results = _get_cached(file_key)

    progress_bar = st.progress(0)
    status_text  = st.empty()

    def on_progress(current, total, ticker, item):
        pct = int(current / total * 100) if total > 0 else 0
        progress_bar.progress(pct)
        if ticker == "데이터 수집 중":
            sources = []
            if has_finnhub_key():
                sources.append("Finnhub")
            if has_marketaux_key():
                sources.append("Marketaux")
            if not sources:
                sources.append("yfinance")
            status_text.markdown(f"📡 **{'+'.join(sources)}**으로 **{total}개 종목** 데이터 수집 중...")
        elif ticker == "퀀트 지표 계산 중":
            status_text.markdown("📊 **퀀트 지표** 계산 중 (모멘텀/변동성/52주)...")
        elif ticker == "AI 분석 중":
            status_text.markdown("🤖 **Gemini AI** 분석 중...")
        elif item is not None:
            reused = item.get("reused_cache", False)
            tag    = "📋 캐시" if reused else "✅ 완료"
            status_text.markdown(f"{tag} **{ticker}** ({current}/{total})")
        else:
            status_text.markdown(f"🤖 **{ticker}** 분석 중... ({current}/{total})")

    try:
        results = analyze_portfolio_signals(
            holdings=holdings,
            api_key=api_key,
            finnhub_key=get_finnhub_key(),
            marketaux_key=get_marketaux_key(),
            progress_callback=on_progress,
            portfolio=portfolio,
            cached_results=cached_results,
        )

        if results:
            now_kst  = get_kst_now()
            kst_date = now_kst.strftime("%Y-%m-%d")
            kst_time = now_kst.strftime("%H:%M:%S")
            for res in results:
                if not res.get("reused_cache"):
                    res["analyzed_date"] = kst_date
                    res["analyzed_time"] = kst_time

    except Exception as e:
        progress_bar.empty()
        status_text.empty()
        st.error(f"❌ 분석 오류: {e}")
        return

    progress_bar.progress(100)
    reused_count   = sum(1 for r in results if r.get("reused_cache"))
    analyzed_count = len(results) - reused_count
    if reused_count > 0:
        status_text.markdown(
            f"✅ **분석 완료!** 재분석 {analyzed_count}개 · 캐시 재사용 {reused_count}개"
        )
    else:
        status_text.markdown(f"✅ **분석 완료!** {len(results)}개 종목")

    if results:
        _set_cached(file_key, results)
    st.rerun()


# ─────────────────────────────────────────────
# HTML 렌더링
# ─────────────────────────────────────────────

def _render_signal_html(signals: list[dict]):
    """탭 전환 + 스와이프 카드 UI로 렌더링."""

    signals_json = json.dumps(signals, ensure_ascii=False)

    html = f"""
<!DOCTYPE html>
<html lang="ko">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<style>
  @import url('https://fonts.googleapis.com/css2?family=Pretendard:wght@300;400;500;600;700&display=swap');
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  :root {{
    --bg: #0f1117;
    --surface: #1a1f2e;
    --surface2: #222736;
    --border: #2a3350;
    --text: #e8eaf6;
    --text-sub: #8892b0;
    --text-muted: #4a5278;
    --up: #ff6b6b;
    --down: #4d9cf8;
    --accent: #7c83f5;
    --accent-soft: rgba(124,131,245,0.12);
    --tag-bg: #1e2440;
    --green: #4ade80;
    --yellow: #fbbf24;
  }}
  body {{
    font-family: 'Pretendard', -apple-system, sans-serif;
    background: var(--bg); color: var(--text);
    padding: 0 0 32px;
  }}

  /* ── 필터 탭 ── */
  .filter-tabs {{
    display: flex; gap: 6px; padding: 10px 16px 0; flex-wrap: wrap;
  }}
  .filter-tab {{
    padding: 6px 14px; border-radius: 20px; font-size: 12px;
    font-weight: 500; cursor: pointer; border: 1px solid var(--border);
    color: var(--text-sub); background: transparent;
    font-family: inherit; transition: all 0.2s;
  }}
  .filter-tab.active {{
    background: var(--accent-soft); border-color: var(--accent); color: var(--accent);
  }}

  /* ── 카드 리스트 ── */
  .signal-list {{
    padding: 10px 16px; display: flex; flex-direction: column; gap: 8px;
  }}

  /* ── 카드 (닫힌 상태) ── */
  .signal-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 13px 14px;
    cursor: pointer; transition: all 0.2s;
    display: flex; align-items: center; gap: 11px;
    position: relative; overflow: hidden;
  }}
  .signal-card::before {{
    content:''; position:absolute; left:0; top:0; bottom:0;
    width:3px; border-radius:14px 0 0 14px;
  }}
  .signal-card.up::before    {{ background: var(--up); }}
  .signal-card.down::before  {{ background: var(--down); }}
  .signal-card.neutral::before {{ background: var(--text-muted); }}
  .signal-card:hover {{ border-color: var(--accent); transform: translateY(-1px); box-shadow: 0 4px 20px rgba(124,131,245,0.1); }}
  .signal-card.open  {{ border-radius: 14px 14px 0 0; border-color: var(--accent); border-bottom-color: transparent; }}

  /* ── 로고 ── */
  .ticker-icon {{
    width: 38px; height: 38px; border-radius: 10px;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px; font-weight: 700; flex-shrink: 0; color: white;
  }}

  /* ── 카드 본문 ── */
  .card-body {{ flex:1; min-width:0; }}
  .card-row1 {{
    display:flex; align-items:center; justify-content:space-between; margin-bottom:2px;
  }}
  .ticker-name {{ font-size:15px; font-weight:600; }}
  .ticker-sub  {{ font-size:11px; color:var(--text-muted); margin-left:5px; font-weight:400; }}
  .card-meta   {{ display:flex; align-items:center; gap:8px; }}
  .rec-badge {{
    font-size:10px; font-weight:700; padding:2px 7px;
    border-radius:5px; letter-spacing:0.3px;
  }}
  .rec-buy     {{ background:rgba(74,222,128,0.15); color:var(--green); border:1px solid rgba(74,222,128,0.3); }}
  .rec-hold    {{ background:rgba(251,191,36,0.15);  color:var(--yellow);border:1px solid rgba(251,191,36,0.3); }}
  .rec-sell    {{ background:rgba(255,107,107,0.15); color:var(--up);   border:1px solid rgba(255,107,107,0.3); }}
  .rec-none    {{ background:var(--tag-bg); color:var(--text-muted); border:1px solid var(--border); }}

  .card-row2 {{ display:flex; align-items:center; justify-content:space-between; }}
  .card-reason {{
    font-size:12px; color:var(--text-sub); flex:1;
    white-space:nowrap; overflow:hidden; text-overflow:ellipsis; padding-right:8px;
  }}
  .card-right  {{ display:flex; align-items:center; gap:8px; flex-shrink:0; }}
  .change-badge {{ font-size:13px; font-weight:700; }}
  .change-badge.up      {{ color:var(--up); }}
  .change-badge.down    {{ color:var(--down); }}
  .change-badge.neutral {{ color:var(--text-muted); }}
  .card-chips  {{ display:flex; gap:4px; margin-top:5px; flex-wrap:wrap; }}
  .chip {{
    font-size:10px; padding:2px 7px; border-radius:5px;
    background:var(--tag-bg); color:var(--text-muted); border:1px solid var(--border);
  }}
  .chip.warn {{ background:rgba(255,107,107,0.1); color:#ff9999; border-color:rgba(255,107,107,0.25); }}
  .chip.good {{ background:rgba(74,222,128,0.1);  color:#86efac; border-color:rgba(74,222,128,0.25); }}

  .card-arrow {{ color:var(--text-muted); font-size:16px; flex-shrink:0; transition:transform 0.2s; }}
  .card-arrow.open {{ transform:rotate(90deg); }}

  /* ── 상세 패널 ── */
  .detail-wrap {{
    background:var(--surface2); border:1px solid var(--accent);
    border-top:none; border-radius:0 0 14px 14px;
    overflow:hidden;
  }}

  /* 탭 헤더 */
  .dtab-header {{
    display:flex; border-bottom:1px solid var(--border);
  }}
  .dtab-btn {{
    flex:1; padding:10px 0; font-size:12px; font-weight:600;
    text-align:center; cursor:pointer; color:var(--text-muted);
    background:transparent; border:none; font-family:inherit;
    border-bottom:2px solid transparent; transition:all 0.2s;
    margin-bottom:-1px;
  }}
  .dtab-btn.active {{ color:var(--accent); border-bottom-color:var(--accent); }}

  /* 탭 콘텐츠 */
  .dtab-content {{ display:none; padding:14px 16px; }}
  .dtab-content.active {{ display:block; }}

  /* AI 의견 탭 */
  .ai-summary {{
    background:var(--accent-soft); border:1px solid var(--border);
    border-radius:10px; padding:11px 13px; margin-bottom:12px;
    font-size:13px; color:var(--text); line-height:1.55; font-weight:500;
  }}
  .bullet-list {{ display:flex; flex-direction:column; gap:8px; margin-bottom:10px; }}
  .bullet-item {{ display:flex; gap:8px; align-items:flex-start; font-size:12px; color:var(--text-sub); line-height:1.5; }}
  .bullet-label {{
    font-size:10px; font-weight:700; padding:1px 6px; border-radius:4px;
    flex-shrink:0; margin-top:1px;
  }}
  .bullet-label.q {{ background:rgba(124,131,245,0.2); color:#a5b4fc; }}
  .bullet-label.n {{ background:rgba(74,222,128,0.15); color:#86efac; }}
  .bullet-label.a {{ background:rgba(251,191,36,0.15);  color:#fde68a; }}
  .bullet-label.ai {{ background:rgba(77,156,248,0.15); color:#93c5fd; border:1px solid rgba(77,156,248,0.25); }}
  .tag-row {{ display:flex; flex-wrap:wrap; gap:5px; margin-top:8px; }}
  .tag {{
    padding:3px 8px; background:var(--tag-bg); border:1px solid var(--border);
    border-radius:6px; font-size:11px; color:var(--text-sub);
  }}

  /* 애널리스트 탭 */
  .ana-grid {{
    display:grid; grid-template-columns:1fr 1fr; gap:8px; margin-bottom:10px;
  }}
  .ana-card {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:10px; padding:10px 12px;
  }}
  .ana-label {{ font-size:10px; color:var(--text-muted); margin-bottom:3px; }}
  .ana-value {{ font-size:15px; font-weight:700; color:var(--text); }}
  .ana-sub   {{ font-size:11px; color:var(--text-muted); margin-top:2px; }}
  .ana-up    {{ color:var(--green); }}
  .ana-down  {{ color:var(--up); }}
  .earning-bar {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:10px; padding:10px 14px;
    display:flex; align-items:center; justify-content:space-between;
  }}
  .earning-left  {{ font-size:12px; color:var(--text-sub); }}
  .earning-right {{ font-size:13px; font-weight:700; }}
  .earning-right.soon {{ color:var(--yellow); }}
  .earning-right.past {{ color:var(--text-muted); }}

  /* 연관기업 */
  .related-section {{ border-top:1px solid var(--border); padding-top:10px; margin-top:4px; }}
  .related-title {{ font-size:12px; font-weight:600; color:var(--text-sub); margin-bottom:7px; }}
  .related-item {{
    background:var(--surface); border:1px solid var(--border);
    border-radius:9px; padding:8px 11px; margin-bottom:6px;
  }}
  .related-ticker {{ font-size:13px; font-weight:600; color:var(--accent); }}
  .related-reason {{ font-size:11px; color:var(--text-muted); margin-top:2px; line-height:1.4; }}

  /* 뉴스 탭 */
  .news-item {{
    padding:10px 0; border-bottom:1px solid var(--border);
  }}
  .news-item:last-child {{ border-bottom:none; }}
  .news-source {{ font-size:10px; color:var(--accent); font-weight:600; margin-bottom:3px; }}
  .news-title  {{ font-size:12px; color:var(--text-sub); line-height:1.45; margin-bottom:4px; }}
  .news-snippet {{ font-size:11px; color:var(--text-muted); line-height:1.45; }}
  .news-senti  {{ display:inline-block; font-size:10px; padding:1px 6px; border-radius:4px; margin-top:4px; }}
  .news-senti.pos {{ background:rgba(74,222,128,0.15);  color:#86efac; }}
  .news-senti.neg {{ background:rgba(255,107,107,0.15); color:#ff9999; }}
  .news-senti.neu {{ background:var(--tag-bg); color:var(--text-muted); }}

  /* 오류 */
  .no-signal {{ font-size:13px; color:var(--text-muted); padding:16px 0; text-align:center; }}

  /* 빈 상태 */
  .empty-state {{ text-align:center; padding:40px 20px; color:var(--text-muted); }}
  .empty-state .icon {{ font-size:36px; margin-bottom:10px; }}

  @keyframes fadeUp {{
    from {{ opacity:0; transform:translateY(8px); }}
    to   {{ opacity:1; transform:translateY(0); }}
  }}
</style>
</head>
<body>

<div class="filter-tabs">
  <button class="filter-tab active" onclick="setFilter(this,'all')">전체</button>
  <button class="filter-tab" onclick="setFilter(this,'up')">상승</button>
  <button class="filter-tab" onclick="setFilter(this,'down')">하락</button>
  <button class="filter-tab" onclick="setFilter(this,'neutral')">중립</button>
</div>

<div class="signal-list" id="signalList"></div>

<script>
const RAW_DATA = {signals_json};

const COLORS = [
  "#3949ab","#1e88e5","#00acc1","#43a047",
  "#fb8c00","#e53935","#8e24aa","#00897b","#f4511e","#6d4c41",
  "#546e7a","#c0ca33","#26a69a","#ec407a","#7c83f5"
];
const TICKER_COLORS = {{
  AAPL:"#555",MSFT:"#0078d4",NVDA:"#76b900",AMZN:"#ff9900",
  GOOGL:"#4285f4",META:"#1877f2",TSLA:"#cc0000",
}};

function tickerColor(t, i) {{ return TICKER_COLORS[t] || COLORS[i % COLORS.length]; }}

function tickerIconHtml(ticker, idx, logoUrl) {{
  const color = tickerColor(ticker, idx);
  if (logoUrl) {{
    return `<div class="ticker-icon" style="background:#1a1f2e;overflow:hidden">
      <img src="${{logoUrl}}" alt="${{ticker}}"
           style="width:100%;height:100%;object-fit:contain;padding:5px;"
           onerror="this.parentElement.style.background='${{color}}';this.parentElement.innerHTML='${{ticker.slice(0,2)}}'">
    </div>`;
  }}
  return `<div class="ticker-icon" style="background:${{color}}">${{ticker.slice(0,2)}}</div>`;
}}

let currentFilter = "all";
let openTicker    = null;
let openTab       = {{}};  // ticker → 'ai'|'analyst'|'news'

function setFilter(el, f) {{
  document.querySelectorAll(".filter-tab").forEach(t => t.classList.remove("active"));
  el.classList.add("active");
  currentFilter = f;
  renderList();
}}

function toggleCard(ticker) {{
  openTicker = openTicker === ticker ? null : ticker;
  if (openTicker && !openTab[ticker]) openTab[ticker] = "ai";
  renderList();
}}

function switchTab(ticker, tab, e) {{
  e.stopPropagation();
  openTab[ticker] = tab;
  renderList();
}}

function getSignalClass(item) {{
  const c = item?.change_pct;
  if (c == null) return "neutral";
  return c > 0 ? "up" : c < 0 ? "down" : "neutral";
}}

function recBadgeHtml(rec) {{
  if (!rec) return `<span class="rec-badge rec-none">N/A</span>`;
  const r = rec.toUpperCase();
  const cls = r.includes("BUY") ? "rec-buy" : r.includes("SELL") ? "rec-sell" : "rec-hold";
  const label = r === "STRONG_BUY" ? "강력매수" : r === "BUY" ? "매수" :
                r === "HOLD" ? "보유" : r === "SELL" ? "매도" :
                r === "UNDERPERFORM" ? "매도" : rec;
  return `<span class="rec-badge ${{cls}}">${{label}}</span>`;
}}

function earningChipHtml(ana) {{
  if (ana?.earnings_days_left == null) return "";
  const d = ana.earnings_days_left;
  if (d < 0)  return `<span class="chip">어닝 D+${{Math.abs(d)}} 발표완료</span>`;
  if (d <= 7) return `<span class="chip warn">🔔 어닝 D-${{d}}</span>`;
  if (d <= 30) return `<span class="chip">어닝 D-${{d}}</span>`;
  return "";
}}

function upsideChipHtml(ana) {{
  if (ana?.target_upside_pct == null) return "";
  const u = ana.target_upside_pct;
  const cls = u > 15 ? "good" : u < -5 ? "warn" : "";
  return `<span class="chip ${{cls}}">목표가 ${{u > 0 ? "+" : ""}}${{u.toFixed(1)}}%</span>`;
}}

function renderList() {{
  const list = document.getElementById("signalList");
  let data = RAW_DATA;
  if (currentFilter === "up")      data = data.filter(d => getSignalClass(d) === "up");
  if (currentFilter === "down")    data = data.filter(d => getSignalClass(d) === "down");
  if (currentFilter === "neutral") data = data.filter(d => getSignalClass(d) === "neutral");

  if (!data.length) {{
    list.innerHTML = `<div class="empty-state"><div class="icon">🔍</div><p>해당하는 시그널이 없어요</p></div>`;
    return;
  }}

  list.innerHTML = data.map((item, i) => {{
    const ticker   = item.ticker;
    const sigClass = getSignalClass(item);
    const change   = item.change_pct != null ? parseFloat(item.change_pct) : null;
    const changeStr = change != null ? (change >= 0 ? "+" : "") + change.toFixed(2) + "%" : "N/A";
    const arrow    = sigClass === "up" ? "▲" : sigClass === "down" ? "▼" : "—";
    const reason   = item.signal?.reason || "분석 정보 없음";
    const logoUrl  = item.logo_url || null;
    const ana      = item.analyst || {{}};
    const isOpen   = openTicker === ticker;

    const detail = isOpen ? renderDetail(item, i) : "";

    return `
      <div style="animation:fadeUp 0.22s ease ${{i*0.04}}s both">
        <div class="signal-card ${{sigClass}}${{isOpen ? " open" : ""}}"
             onclick="toggleCard('${{ticker}}')">
          ${{tickerIconHtml(ticker, i, logoUrl)}}
          <div class="card-body">
            <div class="card-row1">
              <span class="ticker-name">${{ticker}}<span class="ticker-sub">${{item.shares?.toFixed(2)}}주</span></span>
              <div class="card-meta">
                ${{recBadgeHtml(ana.rec_key)}}
              </div>
            </div>
            <div class="card-row2">
              <span class="card-reason">${{reason}}</span>
              <span class="change-badge ${{sigClass}}">${{arrow}} ${{changeStr}}</span>
            </div>
            <div class="card-chips">
              ${{earningChipHtml(ana)}}
              ${{upsideChipHtml(ana)}}
            </div>
          </div>
          <div class="card-arrow${{isOpen ? " open" : ""}}">›</div>
        </div>
        ${{detail}}
      </div>`;
  }}).join("");
}}

function renderDetail(item, idx) {{
  if (!item.signal || item.signal._error) {{
    const msg = item.signal?._error || "AI 분석 실패";
    return `<div class="detail-wrap"><div class="no-signal">⚠️ ${{msg}}</div></div>`;
  }}

  const ticker  = item.ticker;
  const tab     = openTab[ticker] || "ai";
  const sig     = item.signal;
  const ana     = item.analyst || {{}};
  const articles = item.articles || [];

  // ── 탭 헤더 ──────────────────────────────────────────
  const tabs = [
    {{ id:"ai",      label:"💡 AI 의견" }},
    {{ id:"analyst", label:"📊 애널리스트" }},
    {{ id:"news",    label:"📰 뉴스" }},
  ];
  const headerHtml = `<div class="dtab-header">
    ${{tabs.map(t => `<button class="dtab-btn${{tab===t.id?" active":""}}"
      onclick="switchTab('${{ticker}}','${{t.id}}',event)">${{t.label}}</button>`).join("")}}
  </div>`;

  // ── AI 탭 ─────────────────────────────────────────────
  const bullets = sig.bullets || [];
  const labels  = ["뉴스","애널리스트","액션","AI 의견"];
  const lclass  = ["q","n","a","ai"];
  const bulletsHtml = bullets.map((b, i) => `
    <div class="bullet-item">
      <span class="bullet-label ${{lclass[i] || 'q'}}">${{labels[i] || ""}}</span>
      <span>${{b}}</span>
    </div>`).join("");
  const tags    = sig.tags || [];
  const tagsHtml = tags.map(t => `<div class="tag">${{t}}</div>`).join("");
  const related = sig.related || [];
  const relatedHtml = related.length > 0
    ? `<div class="related-section">
         <div class="related-title">🔗 연관 기업</div>
         ${{related.map(r => `
           <div class="related-item">
             <div class="related-ticker">${{r.ticker}}</div>
             <div class="related-reason">${{r.reason}}</div>
           </div>`).join("")}}
       </div>` : "";
  const aiContent = `
    <div class="dtab-content${{tab==="ai"?" active":""}}">
      <div class="ai-summary">${{reason_full(sig)}}</div>
      <div class="bullet-list">${{bulletsHtml}}</div>
      <div class="tag-row">${{tagsHtml}}</div>
      ${{relatedHtml}}
    </div>`;

  // ── 애널리스트 탭 ──────────────────────────────────────
  const recLabel = ana.rec_key
    ? ({{ "STRONG_BUY":"강력 매수","BUY":"매수","HOLD":"보유",
          "SELL":"매도","UNDERPERFORM":"매도" }}[ana.rec_key] || ana.rec_key)
    : "—";
  const nAna = ana.n_analysts ? `${{ana.n_analysts}}명` : "";
  const recColor = ana.rec_key?.includes("BUY") ? "ana-up" :
                   ana.rec_key?.includes("SELL") ? "ana-down" : "";
  const upside = ana.target_upside_pct;
  const upClass = upside != null ? (upside > 0 ? "ana-up" : "ana-down") : "";
  const upStr   = upside != null ? `${{upside > 0 ? "+" : ""}}${{upside.toFixed(1)}}%` : "—";

  const epsSurp = ana.eps_surprise_pct;
  const epsCls  = epsSurp != null ? (epsSurp > 0 ? "ana-up" : "ana-down") : "";
  const epsStr  = epsSurp != null ? `${{epsSurp > 0 ? "+" : ""}}${{epsSurp.toFixed(1)}}%` : "—";

  let earningHtml = "";
  if (ana.earnings_date) {{
    const d = ana.earnings_days_left;
    const label = d < 0 ? `D+${{Math.abs(d)}} 발표완료` : `D-${{d}} 발표예정`;
    const cls   = d != null && d <= 14 && d >= 0 ? "soon" : "past";
    earningHtml = `
      <div class="earning-bar">
        <span class="earning-left">📅 실적 발표</span>
        <span class="earning-right ${{cls}}">${{ana.earnings_date}} · ${{label}}</span>
      </div>`;
  }}

  const analystContent = `
    <div class="dtab-content${{tab==="analyst"?" active":""}}">
      <div class="ana-grid">
        <div class="ana-card">
          <div class="ana-label">투자의견</div>
          <div class="ana-value ${{recColor}}">${{recLabel}}</div>
          <div class="ana-sub">${{nAna}} 애널리스트</div>
        </div>
        <div class="ana-card">
          <div class="ana-label">목표주가 상승여력</div>
          <div class="ana-value ${{upClass}}">${{upStr}}</div>
          <div class="ana-sub">${{ana.target_mean ? "$" + ana.target_mean : "—"}}</div>
        </div>
        <div class="ana-card">
          <div class="ana-label">직전 EPS 서프라이즈</div>
          <div class="ana-value ${{epsCls}}">${{epsStr}}</div>
          <div class="ana-sub">전분기 대비</div>
        </div>
        <div class="ana-card">
          <div class="ana-label">목표가 범위</div>
          <div class="ana-value" style="font-size:12px">
            ${{ana.target_low ? "$"+ana.target_low : "—"}} ~ ${{ana.target_high ? "$"+ana.target_high : "—"}}
          </div>
          <div class="ana-sub">Low ~ High</div>
        </div>
      </div>
      ${{earningHtml}}
    </div>`;

  // ── 뉴스 탭 ────────────────────────────────────────────
  const newsItems = articles.length > 0
    ? articles.slice(0, 5).map(a => {{
        const senti = a.sentiment;
        const scls  = senti != null ? (senti > 0.2 ? "pos" : senti < -0.2 ? "neg" : "neu") : "";
        const slabel = senti != null ? (senti > 0.2 ? "긍정" : senti < -0.2 ? "부정" : "중립") : "";
        return `<div class="news-item">
          ${{a.source ? `<div class="news-source">${{a.source}}</div>` : ""}}
          <div class="news-title">${{a.title || ""}}</div>
          ${{a.snippet ? `<div class="news-snippet">${{a.snippet.slice(0,150)}}</div>` : ""}}
          ${{scls ? `<span class="news-senti ${{scls}}">${{slabel}}</span>` : ""}}
        </div>`;
      }}).join("")
    : `<div class="no-signal">최근 뉴스 없음</div>`;

  const newsContent = `<div class="dtab-content${{tab==="news"?" active":""}}">
    ${{newsItems}}
  </div>`;

  return `<div class="detail-wrap">
    ${{headerHtml}}
    ${{aiContent}}
    ${{analystContent}}
    ${{newsContent}}
  </div>`;
}}

function reason_full(sig) {{
  // reason이 짧으면 bullets[2](액션시사점)도 붙여서 표시
  const r = sig.reason || "";
  return r;
}}

renderList();
</script>
</body>
</html>
"""

    n = len(signals)
    height = max(500, n * 100 + 200)
    components.html(html, height=height, scrolling=True)