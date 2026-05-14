"""
utils/styles.py — QPM Alpha 디자인 시스템
파스텔 틸 그라데이션 + 미니멀 라이트 테마
"""

MAIN_CSS = """
<style>
/* ── 기본 배경 ── */
.stApp { background: linear-gradient(160deg, #f4fbfa 0%, #f6f9fd 60%, #f8f7ff 100%) !important; }
[data-testid="stAppViewContainer"] { background: transparent !important; }
[data-testid="stHeader"] { background: transparent !important; }

/* ── 헤더 ── */
.main-header {
    background: linear-gradient(135deg, #e8f8f6 0%, #eef6fb 50%, #f0f4ff 100%);
    border: 0.5px solid rgba(26,158,143,0.18);
    border-radius: 14px;
    padding: 16px 22px;
    margin-bottom: 18px;
    display: flex;
    align-items: center;
    gap: 12px;
}
.main-header h1 {
    margin: 0;
    font-size: 1.4rem;
    font-weight: 600;
    color: #1a2a28;
    letter-spacing: -0.3px;
}
.main-header h1 span { color: #1a9e8f; }
.main-header p { margin: 3px 0 0 0; font-size: 0.8rem; color: #6b8f8b; }

/* ── 탭 ── */
.stTabs [data-baseweb="tab-list"] {
    background: linear-gradient(135deg, #edf7f6 0%, #f2f7fb 50%, #f4f6ff 100%);
    border-radius: 12px;
    padding: 4px 6px;
    gap: 2px;
    border: 0.5px solid rgba(26,158,143,0.12);
}
.stTabs [data-baseweb="tab"] {
    border-radius: 8px;
    color: #6b8f8b;
    font-weight: 500;
    font-size: 0.85rem;
    padding: 7px 14px;
}
.stTabs [aria-selected="true"] {
    background: rgba(255,255,255,0.9) !important;
    color: #1a9e8f !important;
    box-shadow: 0 1px 4px rgba(26,158,143,0.12) !important;
}

/* ── 메트릭 카드 ── */
.metric-card {
    background: rgba(255,255,255,0.88);
    border: 0.5px solid rgba(26,158,143,0.14);
    border-radius: 12px;
    padding: 14px 16px;
    text-align: left;
}
.metric-card .label {
    font-size: 0.72rem;
    color: #7aada8;
    margin-bottom: 5px;
    font-weight: 500;
    letter-spacing: 0.3px;
    text-transform: uppercase;
}
.metric-card .value {
    font-size: 1.35rem;
    font-weight: 600;
    color: #1a2a28;
    line-height: 1.2;
}
.metric-card .sub {
    font-size: 0.72rem;
    margin-top: 4px;
    color: #7aada8;
}
.metric-card .sub.up { color: #1a9e8f; }
.metric-card .sub.down { color: #e05252; }

/* ── 배너 ── */
.warn-banner {
    background: #fff8f0;
    border: 0.5px solid rgba(224,130,60,0.35);
    border-radius: 10px;
    padding: 10px 15px;
    color: #a05a20;
    font-size: 0.83rem;
    margin: 7px 0;
    line-height: 1.55;
}
.success-banner {
    background: #f0faf7;
    border: 0.5px solid rgba(26,158,143,0.3);
    border-radius: 10px;
    padding: 10px 15px;
    color: #0d7a6e;
    font-size: 0.83rem;
    margin: 7px 0;
    line-height: 1.55;
}
.info-banner {
    background: #f0f6ff;
    border: 0.5px solid rgba(60,120,220,0.2);
    border-radius: 10px;
    padding: 10px 15px;
    color: #2a5298;
    font-size: 0.82rem;
    margin: 7px 0;
    line-height: 1.6;
}
.danger-banner {
    background: #fff4f4;
    border: 0.5px solid rgba(224,82,82,0.3);
    border-radius: 10px;
    padding: 10px 15px;
    color: #b02020;
    font-size: 0.83rem;
    margin: 7px 0;
    line-height: 1.55;
}

/* ── 섹션 레이블 ── */
.section-label {
    font-size: 0.72rem;
    font-weight: 600;
    color: #7aada8;
    text-transform: uppercase;
    letter-spacing: 0.8px;
    margin: 18px 0 8px 0;
}

/* ── 버튼 ── */
.stButton > button {
    background: #1a9e8f;
    color: #ffffff !important;
    border: none;
    border-radius: 9px;
    font-weight: 500;
    font-size: 0.85rem;
    padding: 8px 18px;
    transition: all 0.18s;
    width: 100%;
    letter-spacing: 0.1px;
}
.stButton > button:hover {
    background: #0d7a6e;
    transform: translateY(-1px);
    box-shadow: 0 3px 10px rgba(26,158,143,0.22);
}
.stButton > button:active { transform: translateY(0); }

/* ── 입력 필드 ── */
.stTextInput input, .stNumberInput input {
    background: rgba(255,255,255,0.9) !important;
    color: #1a2a28 !important;
    border: 0.5px solid rgba(26,158,143,0.2) !important;
    border-radius: 8px !important;
    font-size: 0.88rem !important;
    caret-color: #1a9e8f !important;
}
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #1a9e8f !important;
    box-shadow: 0 0 0 2px rgba(26,158,143,0.12) !important;
}
.stTextInput input::placeholder, .stNumberInput input::placeholder {
    color: #a8c4c1 !important;
}
.stTextInput label, .stNumberInput label, .stSelectbox label,
.stCheckbox label, .stFileUploader label, .stRadio label {
    color: #5a8a85 !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
}

/* ── 셀렉트 박스 ── */
.stSelectbox > div > div {
    background: rgba(255,255,255,0.9) !important;
    color: #1a2a28 !important;
    border: 0.5px solid rgba(26,158,143,0.2) !important;
    border-radius: 8px !important;
}

/* ── 라디오 ── */
.stRadio > div { gap: 6px !important; }
.stRadio [data-testid="stMarkdownContainer"] p { color: #3a6a65 !important; font-size: 0.83rem !important; }

/* ── 데이터프레임 ── */
[data-testid="stDataFrame"] th {
    background: linear-gradient(135deg, #e8f7f5, #eef4fb) !important;
    color: #1a9e8f !important;
    font-weight: 600 !important;
    font-size: 0.78rem !important;
    border-bottom: 0.5px solid rgba(26,158,143,0.15) !important;
}
[data-testid="stDataFrame"] td {
    color: #2a3a38 !important;
    font-size: 0.83rem !important;
}
[data-testid="stDataFrame"] tr:hover td {
    background: rgba(26,158,143,0.04) !important;
}

/* ── 익스팬더 ── */
.stExpander {
    background: rgba(255,255,255,0.7) !important;
    border: 0.5px solid rgba(26,158,143,0.14) !important;
    border-radius: 10px !important;
}
.stExpander summary { color: #3a6a65 !important; font-size: 0.85rem !important; }

/* ── 캡션 ── */
.stCaption, div[data-testid="stCaptionContainer"] {
    color: #8ab4b0 !important;
    font-size: 0.76rem !important;
}

/* ── 토글 ── */
.stToggle > label { color: #5a8a85 !important; font-size: 0.83rem !important; }

/* ── 스피너 ── */
.stSpinner > div { border-top-color: #1a9e8f !important; }

/* ── 파일 업로더 ── */
[data-testid="stFileUploader"] {
    background: rgba(255,255,255,0.7) !important;
    border: 0.5px dashed rgba(26,158,143,0.3) !important;
    border-radius: 10px !important;
}

/* ── 다운로드 버튼 ── */
.stDownloadButton > button {
    background: #0d7a6e !important;
    color: white !important;
    border: none !important;
    border-radius: 9px !important;
}

/* ── 컬럼 레이아웃 정렬 ── */
div[data-testid="column"] { display: flex !important; flex-direction: column !important; }
div[data-testid="column"]:has(.stButton)    { justify-content: flex-end !important; }
div[data-testid="column"]:has(.stCheckbox) { justify-content: center !important; }
div[data-testid="column"] > div {
    height: 100% !important;
    display: flex !important;
    flex-direction: column !important;
}
div[data-testid="column"]:has(.stButton) .stButton { margin-bottom: 0 !important; }

/* ── 상태 필 ── */
.status-pill {
    display: inline-flex;
    align-items: center;
    gap: 5px;
    background: rgba(255,255,255,0.85);
    border: 0.5px solid rgba(26,158,143,0.18);
    border-radius: 20px;
    padding: 5px 11px;
    font-size: 0.75rem;
    color: #5a8a85;
    margin: 3px 3px 3px 0;
}
.status-pill .dot {
    width: 6px; height: 6px; border-radius: 50%; flex-shrink: 0;
}

/* ── 유저 칩 ── */
.user-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    background: rgba(255,255,255,0.75);
    border: 0.5px solid rgba(26,158,143,0.18);
    border-radius: 20px;
    padding: 4px 10px 4px 6px;
    font-size: 0.78rem;
    color: #5a8a85;
}
.user-chip .avatar {
    width: 20px; height: 20px; border-radius: 50%;
    background: #e0f5f2;
    display: flex; align-items: center; justify-content: center;
    font-size: 10px; font-weight: 600; color: #1a9e8f;
}

/* ── 배지 ── */
.badge {
    display: inline-flex; align-items: center; gap: 3px;
    font-size: 0.72rem; font-weight: 500;
    padding: 3px 9px; border-radius: 20px;
}
.badge-bull { background: #e0f5f2; color: #0d7a6e; }
.badge-bear { background: #fdecea; color: #b02020; }
.badge-gold { background: #fdf4e0; color: #8a6a10; border: 0.5px solid rgba(180,140,40,0.25); }
.badge-info { background: #e8f1fd; color: #1a56b0; }

/* ── 숨기기 ── */
#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }
</style>
"""


def inject_css():
    import streamlit as st
    st.markdown(MAIN_CSS, unsafe_allow_html=True)
