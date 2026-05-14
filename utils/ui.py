"""
utils/ui.py — QPM Alpha HTML 컴포넌트 헬퍼
시안 그대로 재현하는 HTML 빌딩 블록
"""

# ── 색상 팔레트 ─────────────────────────────────────────
TEAL        = "#1a9e8f"
TEAL_DARK   = "#0d7a6e"
TEAL_LIGHT  = "#e0f5f2"
GOLD        = "#b8922a"
GOLD_LIGHT  = "#fdf4e0"
RED         = "#e05252"
RED_LIGHT   = "#fff2f2"
BLUE        = "#4a90d9"
TEXT        = "#1a2a28"
TEXT_SUB    = "#5a8a85"
TEXT_MUTED  = "#7ab0aa"
BORDER      = "rgba(26,158,143,0.16)"
SURFACE     = "rgba(255,255,255,0.92)"
SURFACE_DIM = "rgba(255,255,255,0.7)"
BG_GRAD     = "linear-gradient(160deg,#f0faf9 0%,#f4f8fd 55%,#f6f5ff 100%)"
HEADER_GRAD = "linear-gradient(135deg,#e4f7f4 0%,#eaf4fb 50%,#ece9ff 100%)"
TAB_GRAD    = "linear-gradient(135deg,#e6f7f5 0%,#eef5fb 50%,#eeeaff 100%)"


def section_title(text: str) -> str:
    return (
        f'<div style="font-size:0.7rem;font-weight:700;color:{TEXT_MUTED};'
        f'text-transform:uppercase;letter-spacing:0.8px;margin:18px 0 8px 0">'
        f'{text}</div>'
    )


def metric_card(label: str, value: str, sub: str = "", sub_color: str = TEXT_MUTED) -> str:
    return f"""
<div style="background:{SURFACE};border:0.5px solid {BORDER};border-radius:12px;padding:14px 15px;">
  <div style="font-size:0.68rem;font-weight:700;color:{TEXT_MUTED};text-transform:uppercase;
              letter-spacing:0.5px;margin-bottom:5px">{label}</div>
  <div style="font-size:1.25rem;font-weight:700;color:{TEXT};line-height:1.2">{value}</div>
  {'<div style="font-size:0.7rem;margin-top:4px;color:' + sub_color + '">' + sub + '</div>' if sub else ''}
</div>"""


def banner(text: str, kind: str = "info") -> str:
    styles = {
        "info":    (f"#eef5ff", f"rgba(60,120,210,0.18)", f"#2a5090"),
        "success": (f"#f0faf7", f"rgba(26,158,143,0.28)", f"#0e7a6e"),
        "warn":    (f"#fff8f0", f"rgba(200,120,40,0.28)", f"#9a5a18"),
        "danger":  (f"#fff2f2", f"rgba(220,70,70,0.28)",  f"#a82020"),
    }
    bg, border, color = styles.get(kind, styles["info"])
    return (
        f'<div style="background:{bg};border:0.5px solid {border};border-radius:10px;'
        f'padding:10px 14px;color:{color};font-size:0.82rem;margin:6px 0;line-height:1.6">'
        f'{text}</div>'
    )


def badge(text: str, kind: str = "default") -> str:
    styles = {
        "bull":    (TEAL_LIGHT,  TEAL_DARK),
        "bear":    (RED_LIGHT,   RED),
        "gold":    (GOLD_LIGHT,  GOLD),
        "info":    ("#e6f1fd",   BLUE),
        "default": ("#f0f0f0",   TEXT_SUB),
    }
    bg, color = styles.get(kind, styles["default"])
    return (
        f'<span style="display:inline-flex;align-items:center;gap:3px;font-size:0.7rem;'
        f'font-weight:600;padding:3px 9px;border-radius:20px;background:{bg};color:{color}">'
        f'{text}</span>'
    )


def status_pill(text: str, dot_color: str = "#22c55e") -> str:
    return (
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'background:{SURFACE};border:0.5px solid {BORDER};border-radius:20px;'
        f'padding:4px 10px;font-size:0.72rem;color:{TEXT_SUB}">'
        f'<span style="width:6px;height:6px;border-radius:50%;background:{dot_color};flex-shrink:0"></span>'
        f'{text}</span>'
    )


GLOBAL_CSS = f"""
<style>
/* ── 기본 ── */
.stApp {{
    background: {BG_GRAD} !important;
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif !important;
}}
[data-testid="stAppViewContainer"] > .main {{ background: transparent !important; }}
[data-testid="stHeader"] {{ background: transparent !important; }}
section[data-testid="stSidebar"] {{ background: {HEADER_GRAD} !important; }}

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {{
    background: {TAB_GRAD} !important;
    border-radius: 12px !important;
    padding: 4px 6px !important;
    gap: 2px !important;
    border: 0.5px solid {BORDER} !important;
}}
.stTabs [data-baseweb="tab"] {{
    border-radius: 8px !important;
    color: {TEXT_SUB} !important;
    font-weight: 500 !important;
    font-size: 0.83rem !important;
    padding: 7px 12px !important;
    background: transparent !important;
}}
.stTabs [aria-selected="true"] {{
    background: rgba(255,255,255,0.92) !important;
    color: {TEAL} !important;
    box-shadow: 0 1px 4px rgba(26,158,143,0.14) !important;
}}
.stTabs [data-baseweb="tab-panel"] {{ padding-top: 16px !important; }}

/* ── 버튼 ── */
.stButton > button {{
    background: {TEAL} !important;
    color: #fff !important;
    border: none !important;
    border-radius: 9px !important;
    font-weight: 600 !important;
    font-size: 0.83rem !important;
    transition: all 0.15s !important;
    width: 100% !important;
}}
.stButton > button:hover {{
    background: {TEAL_DARK} !important;
    box-shadow: 0 3px 10px rgba(26,158,143,0.22) !important;
    transform: translateY(-1px) !important;
}}
.stButton > button:active {{ transform: translateY(0) !important; }}

/* ── 입력 ── */
.stTextInput input, .stNumberInput input, .stSelectbox > div > div {{
    background: rgba(255,255,255,0.95) !important;
    color: {TEXT} !important;
    border: 0.5px solid rgba(26,158,143,0.22) !important;
    border-radius: 8px !important;
    font-size: 0.86rem !important;
}}
.stTextInput input:focus, .stNumberInput input:focus {{
    border-color: {TEAL} !important;
    box-shadow: 0 0 0 2px rgba(26,158,143,0.1) !important;
}}
.stTextInput input::placeholder {{ color: #b0ccc9 !important; }}
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stRadio label, div[data-testid="stWidgetLabel"] p {{
    color: {TEXT_SUB} !important;
    font-size: 0.78rem !important;
    font-weight: 600 !important;
}}

/* ── 라디오 ── */
.stRadio [data-testid="stMarkdownContainer"] p {{
    color: {TEXT} !important;
    font-size: 0.82rem !important;
}}

/* ── 데이터프레임 ── */
[data-testid="stDataFrame"] th {{
    background: linear-gradient(135deg,#e4f7f4,#eaf3fb) !important;
    color: {TEAL} !important;
    font-weight: 700 !important;
    font-size: 0.76rem !important;
    letter-spacing: 0.2px !important;
    border-bottom: 0.5px solid rgba(26,158,143,0.15) !important;
}}
[data-testid="stDataFrame"] td {{
    color: {TEXT} !important;
    font-size: 0.82rem !important;
}}
[data-testid="stDataFrame"] tr:hover td {{
    background: rgba(26,158,143,0.03) !important;
}}
[data-testid="stDataFrame"] {{ border-radius: 10px !important; overflow: hidden !important; }}

/* ── 익스팬더 ── */
.stExpander {{
    background: rgba(255,255,255,0.78) !important;
    border: 0.5px solid {BORDER} !important;
    border-radius: 10px !important;
}}
details > summary {{ color: {TEXT_SUB} !important; font-size: 0.83rem !important; font-weight:500 !important; }}

/* ── 캡션 ── */
.stCaption, div[data-testid="stCaptionContainer"] {{
    color: {TEXT_MUTED} !important;
    font-size: 0.73rem !important;
}}

/* ── 다운로드 버튼 ── */
.stDownloadButton > button {{
    background: {TEAL_DARK} !important;
    color: white !important;
    border: none !important;
    border-radius: 9px !important;
}}

/* ── 토글 ── */
.stToggle > label span {{ color: {TEXT_SUB} !important; }}

/* ── 파일 업로더 ── */
[data-testid="stFileUploader"] {{
    background: rgba(255,255,255,0.75) !important;
    border: 0.5px dashed rgba(26,158,143,0.28) !important;
    border-radius: 10px !important;
}}

/* ── 컬럼 정렬 ── */
div[data-testid="column"] {{ display:flex !important; flex-direction:column !important; }}
div[data-testid="column"]:has(.stButton) {{ justify-content:flex-end !important; }}
div[data-testid="column"] > div {{
    height:100% !important; display:flex !important; flex-direction:column !important;
}}
div[data-testid="column"]:has(.stButton) .stButton {{ margin-bottom:0 !important; }}

/* ── 프로그레스 ── */
.stProgress > div > div {{ background: {TEAL} !important; }}

/* ── 숨기기 ── */
#MainMenu {{ visibility:hidden; }}
footer    {{ visibility:hidden; }}
header    {{ visibility:hidden; }}

/* ── 반응형 ── */
@media (max-width: 768px) {{
    .qpm-metric-grid {{ grid-template-columns: 1fr 1fr !important; }}
    .qpm-form-row    {{ grid-template-columns: 1fr !important; }}
    .qpm-rec-amount  {{ display:none !important; }}
    .stTabs [data-baseweb="tab"] {{ padding: 6px 8px !important; font-size:0.76rem !important; }}
}}
@media (max-width: 480px) {{
    .qpm-metric-grid {{ grid-template-columns: 1fr !important; }}
    .qpm-stock-price {{ display:none !important; }}
}}
</style>
"""


def inject_all():
    import streamlit as st
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)
