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
    """분석 결과를 토스증권 스타일 HTML 컴포넌트로 렌더링."""

    # Python 데이터 → JS에서 쓸 JSON
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
  }}
  body {{
    font-family: 'Pretendard', -apple-system, sans-serif;
    background: var(--bg);
    color: var(--text);
    padding: 0 0 24px;
  }}

  /* 필터 탭 */
  .filter-tabs {{
    display: flex; gap: 6px; padding: 10px 16px 0;
  }}
  .filter-tab {{
    padding: 7px 14px; border-radius: 20px; font-size: 13px;
    font-weight: 500; cursor: pointer; border: 1px solid var(--border);
    color: var(--text-sub); background: transparent;
    font-family: inherit; transition: all 0.2s;
  }}
  .filter-tab.active {{
    background: var(--accent-soft); border-color: var(--accent); color: var(--accent);
  }}

  /* 시그널 리스트 */
  .signal-list {{
    padding: 12px 16px; display: flex; flex-direction: column; gap: 10px;
  }}

  /* 시그널 카드 */
  .signal-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 14px; padding: 14px 16px; cursor: pointer;
    transition: all 0.2s; display: flex; align-items: center;
    gap: 12px; position: relative; overflow: hidden;
  }}
  .signal-card::before {{
    content: ''; position: absolute; left: 0; top: 0; bottom: 0;
    width: 3px; border-radius: 14px 0 0 14px;
  }}
  .signal-card.up::before   {{ background: var(--up); }}
  .signal-card.down::before {{ background: var(--down); }}
  .signal-card.neutral::before {{ background: var(--text-muted); }}
  .signal-card:hover {{
    border-color: var(--accent); transform: translateY(-1px);
    box-shadow: 0 4px 20px rgba(124,131,245,0.1);
  }}
  .signal-card.open {{ border-color: var(--accent); }}

  .ticker-icon {{
    width: 40px; height: 40px; border-radius: 11px;
    display: flex; align-items: center; justify-content: center;
    font-size: 13px; font-weight: 700; flex-shrink: 0; color: white;
  }}

  .card-content {{ flex: 1; min-width: 0; }}
  .card-top {{
    display: flex; align-items: center; justify-content: space-between; margin-bottom: 3px;
  }}
  .ticker-name {{ font-size: 15px; font-weight: 600; color: var(--text); }}
  .ticker-sub {{ font-size: 11px; color: var(--text-muted); font-weight: 400; margin-left: 5px; }}
  .signal-reason {{
    font-size: 13px; color: var(--text-sub); margin-bottom: 5px;
    line-height: 1.4; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }}
  .change-badge {{ display: inline-flex; align-items: center; gap: 3px; font-size: 13px; font-weight: 700; }}
  .change-badge.up   {{ color: var(--up); }}
  .change-badge.down {{ color: var(--down); }}
  .change-badge.neutral {{ color: var(--text-muted); }}
  .card-arrow {{ color: var(--text-muted); font-size: 18px; flex-shrink: 0; transition: transform 0.2s; }}
  .card-arrow.open {{ transform: rotate(90deg); }}

  /* 상세 패널 (인라인 확장) */
  .detail-panel {{
    display: none; overflow: hidden;
    background: var(--surface2); border-radius: 0 0 12px 12px;
    border: 1px solid var(--border); border-top: none;
    margin-top: -10px; padding: 16px;
  }}
  .detail-panel.open {{ display: block; }}

  .section-title {{
    font-size: 14px; font-weight: 700; color: var(--text);
    margin-bottom: 10px; display: flex; align-items: center; gap: 6px;
  }}
  .ai-badge {{
    font-size: 10px; color: var(--accent); font-weight: 600;
    background: var(--accent-soft); padding: 2px 7px; border-radius: 5px;
  }}

  /* 불릿 */
  .bullet-list {{ display: flex; flex-direction: column; gap: 8px; margin-bottom: 12px; }}
  .bullet-item {{ display: flex; gap: 8px; align-items: flex-start; font-size: 13px; color: var(--text-sub); line-height: 1.5; }}
  .bullet-dot {{ width: 5px; height: 5px; border-radius: 50%; background: var(--accent); margin-top: 7px; flex-shrink: 0; }}

  /* 태그 */
  .tag-row {{ display: flex; flex-wrap: wrap; gap: 5px; margin-bottom: 14px; }}
  .tag {{
    padding: 4px 9px; background: var(--tag-bg); border: 1px solid var(--border);
    border-radius: 7px; font-size: 11px; color: var(--text-sub); font-weight: 500;
  }}

  /* 연관 기업 */
  .related-section {{ border-top: 1px solid var(--border); padding-top: 12px; margin-top: 4px; }}
  .related-title {{ font-size: 13px; font-weight: 600; color: var(--text-sub); margin-bottom: 8px; }}
  .related-item {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 10px; padding: 10px 12px; margin-bottom: 7px;
  }}
  .related-ticker {{ font-size: 13px; font-weight: 600; color: var(--accent); }}
  .related-reason {{ font-size: 12px; color: var(--text-muted); margin-top: 3px; line-height: 1.4; }}

  /* 뉴스 출처 */
  .news-section {{ border-top: 1px solid var(--border); padding-top: 12px; margin-top: 4px; }}
  .news-title {{ font-size: 13px; font-weight: 600; color: var(--text-sub); margin-bottom: 8px; }}
  .news-item {{
    font-size: 12px; color: var(--text-muted); padding: 5px 0;
    border-bottom: 1px solid var(--border); line-height: 1.4;
  }}
  .news-item:last-child {{ border-bottom: none; }}

  /* 오류/미분석 */
  .no-signal {{
    font-size: 13px; color: var(--text-muted); padding: 8px 0; text-align: center;
  }}

  /* 빈 상태 */
  .empty-state {{ text-align: center; padding: 40px 20px; color: var(--text-muted); }}
  .empty-state .icon {{ font-size: 36px; margin-bottom: 10px; }}
  .empty-state p {{ font-size: 14px; line-height: 1.6; }}

  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(10px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
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

// 티커별 아이콘 색상
const COLORS = [
  "#3949ab","#1e88e5","#00acc1","#43a047",
  "#fb8c00","#e53935","#8e24aa","#00897b","#f4511e","#6d4c41",
  "#546e7a","#c0ca33","#26a69a","#ec407a","#7c83f5"
];
function tickerColor(ticker, idx) {{
  const map = {{
    AAPL:"#555",MSFT:"#0078d4",NVDA:"#76b900",AMZN:"#ff9900",
    GOOGL:"#4285f4",META:"#1877f2",TSLA:"#cc0000",
  }};
  return map[ticker] || COLORS[idx % COLORS.length];
}}

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

function setFilter(el, filter) {{
  document.querySelectorAll(".filter-tab").forEach(t => t.classList.remove("active"));
  el.classList.add("active");
  currentFilter = filter;
  renderList();
}}

function toggleDetail(ticker) {{
  openTicker = openTicker === ticker ? null : ticker;
  renderList();
}}

function getSignalClass(s) {{
  const sig = s?.signal?.signal || "neutral";
  if (sig === "up")   return "up";
  if (sig === "down") return "down";
  return "neutral";
}}

function getChangePct(item) {{
  const c = item.change_pct;
  if (c === null || c === undefined) return null;
  return parseFloat(c);
}}

function renderList() {{
  const list = document.getElementById("signalList");
  let data   = RAW_DATA;

  if (currentFilter === "up")      data = data.filter(d => getSignalClass(d) === "up");
  if (currentFilter === "down")    data = data.filter(d => getSignalClass(d) === "down");
  if (currentFilter === "neutral") data = data.filter(d => getSignalClass(d) === "neutral");

  if (data.length === 0) {{
    list.innerHTML = `<div class="empty-state"><div class="icon">🔍</div><p>해당하는 시그널이 없어요</p></div>`;
    return;
  }}

  list.innerHTML = data.map((item, i) => {{
    const ticker     = item.ticker;
    const sigClass   = getSignalClass(item);
    const change     = getChangePct(item);
    const changeStr  = change !== null ? (change >= 0 ? "+" : "") + change.toFixed(2) + "%" : "N/A";
    const arrow      = sigClass === "up" ? "▲" : sigClass === "down" ? "▼" : "—";
    const reason     = item.signal?.reason || "분석 정보 없음";
    const color      = tickerColor(ticker, i);
    const logoUrl    = item.logo_url || null;
    const isOpen     = openTicker === ticker;

    const detail     = isOpen ? renderDetail(item, color) : "";

    return `
      <div style="animation: fadeUp 0.25s ease ${{i * 0.05}}s both">
        <div class="signal-card ${{sigClass}} ${{isOpen ? "open" : ""}}"
             onclick="toggleDetail('${{ticker}}')"
             style="border-radius: ${{isOpen ? "14px 14px 0 0" : "14px"}}">
          ${{tickerIconHtml(ticker, i, logoUrl)}}
          <div class="card-content">
            <div class="card-top">
              <span class="ticker-name">${{ticker}}<span class="ticker-sub">${{item.shares?.toFixed(2)}}주</span></span>
            </div>
            <div class="signal-reason">${{reason}}</div>
            <span class="change-badge ${{sigClass}}">${{arrow}} ${{changeStr}}</span>
          </div>
          <div class="card-arrow ${{isOpen ? "open" : ""}}">›</div>
        </div>
        ${{detail}}
      </div>
    `;
  }}).join("");
}}

function renderDetail(item, color) {{
  if (!item.signal) {{
    return `
      <div class="detail-panel open">
        <div class="no-signal">⚠️ AI 분석에 실패했습니다. 잠시 후 재시도해주세요.</div>
      </div>`;
  }}
  if (item.signal._error) {{
    return `
      <div class="detail-panel open">
        <div class="no-signal">⚠️ 오류: ${{item.signal._error}}</div>
      </div>`;
  }}

  const sig      = item.signal;
  const bullets  = sig.bullets  || [];
  const tags     = sig.tags     || [];
  const related  = sig.related  || [];
  const headlines = item.headlines || [];

  const bulletsHtml = bullets.map(b => `
    <div class="bullet-item">
      <div class="bullet-dot"></div>
      <span>${{b}}</span>
    </div>`).join("");

  const tagsHtml = tags.map(t => `<div class="tag">${{t}}</div>`).join("");

  const relatedHtml = related.length > 0
    ? `<div class="related-section">
         <div class="related-title">🔗 연관 기업</div>
         ${{related.map(r => `
           <div class="related-item">
             <div class="related-ticker">${{r.ticker}}</div>
             <div class="related-reason">${{r.reason}}</div>
           </div>`).join("")}}
       </div>`
    : "";

  const newsHtml = headlines.length > 0
    ? `<div class="news-section">
         <div class="news-title">📰 뉴스 출처</div>
         ${{headlines.slice(0,5).map(h => `<div class="news-item">${{h}}</div>`).join("")}}
       </div>`
    : "";

  return `
    <div class="detail-panel open">
      <div class="section-title">왜 움직였을까? <span class="ai-badge">AI 요약</span></div>
      <div class="bullet-list">${{bulletsHtml}}</div>
      <div class="tag-row">${{tagsHtml}}</div>
      ${{relatedHtml}}
      ${{newsHtml}}
    </div>`;
}}

renderList();
</script>
</body>
</html>
"""

    # 종목 수에 따라 높이 동적 조정
    n = len(signals)
    height = max(400, n * 90 + 200)
    components.html(html, height=height, scrolling=True)