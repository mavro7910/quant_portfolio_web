"""
utils/styles.py
앱 전체 CSS를 한 곳에서 관리.
"""

MAIN_CSS = """
<style>
.stApp { background-color: #0f1117; color: #e0e0e0; }

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
.main-header p { margin: 4px 0 0 0; font-size: 0.85rem; color: #7986cb; }

.metric-card {
    background: #1a1f2e;
    border: 1px solid #2a3a5c;
    border-radius: 10px;
    padding: 16px 20px;
    text-align: center;
}
.metric-card .label { font-size: 0.78rem; color: #90caf9; margin-bottom: 6px; }
.metric-card .value { font-size: 1.4rem; font-weight: 700; color: #e8eaf6; }

.warn-banner {
    background: #2a1f0e;
    border: 1px solid #e67e22;
    border-radius: 8px;
    padding: 10px 16px;
    color: #f0a862;
    font-size: 0.85rem;
    margin: 8px 0;
}
.success-banner {
    background: #0e2a1a;
    border: 1px solid #27ae60;
    border-radius: 8px;
    padding: 10px 16px;
    color: #6ee89b;
    font-size: 0.85rem;
    margin: 8px 0;
}
.info-banner {
    background: #0e1a2a;
    border: 1px solid #1e88e5;
    border-radius: 8px;
    padding: 10px 16px;
    color: #90caf9;
    font-size: 0.82rem;
    margin: 8px 0;
    line-height: 1.6;
}

.section-label {
    font-size: 0.78rem;
    font-weight: 600;
    color: #90caf9;
    text-transform: uppercase;
    letter-spacing: 1px;
    margin: 20px 0 8px 0;
}

.stTabs [data-baseweb="tab-list"] {
    background: #1a1f2e; border-radius: 10px; padding: 4px; gap: 4px;
}
.stTabs [data-baseweb="tab"] { border-radius: 8px; color: #90caf9; font-weight: 600; }
.stTabs [aria-selected="true"] { background: #283593 !important; color: #e8eaf6 !important; }

.stButton > button {
    background: linear-gradient(135deg, #283593, #1a237e);
    color: #ffffff !important;
    border: none; border-radius: 8px; font-weight: 600;
    padding: 8px 20px; transition: all 0.2s; width: 100%;
}
.stButton > button:hover {
    background: linear-gradient(135deg, #3949ab, #283593);
    transform: translateY(-1px);
}

div[data-testid="column"] { display: flex !important; flex-direction: column !important; }
div[data-testid="column"]:has(.stButton)   { justify-content: flex-end !important; }
div[data-testid="column"]:has(.stCheckbox) { justify-content: center !important; }
div[data-testid="column"]:has(.stSelectbox){ justify-content: flex-end !important; }
div[data-testid="column"] > div {
    height: 100% !important; display: flex !important; flex-direction: column !important;
}
div[data-testid="column"] > div > div[data-testid="stVerticalBlock"] {
    height: 100% !important; display: flex !important;
    flex-direction: column !important; justify-content: inherit !important;
}
div[data-testid="column"]:has(.stButton) .stButton  { margin-bottom: 0 !important; }
div[data-testid="column"]:has(.stCheckbox) .stCheckbox { padding: 0 !important; margin: 0 !important; }

.stTextInput input, .stNumberInput input {
    background-color: #1e2535 !important; color: #e8eaf6 !important;
    border: 1px solid #3a4a6c !important; border-radius: 6px !important;
    caret-color: #90caf9 !important;
}
.stTextInput input::placeholder, .stNumberInput input::placeholder { color: #5c6f99 !important; }
.stTextInput input:focus, .stNumberInput input:focus {
    border-color: #5c7cfa !important;
    box-shadow: 0 0 0 2px rgba(92,124,250,0.2) !important;
}

.stSelectbox > div > div {
    background-color: #1e2535 !important; color: #e8eaf6 !important;
    border: 1px solid #3a4a6c !important; border-radius: 6px !important;
}
.stSelectbox svg { fill: #90caf9 !important; }

.stTextInput label, .stNumberInput label, .stSelectbox label,
.stCheckbox label, .stFileUploader label {
    color: #b0bec5 !important; font-size: 0.85rem !important;
}
.stCheckbox > label > div { color: #b0bec5 !important; }
.stCaption, div[data-testid="stCaptionContainer"] { color: #7986cb !important; }

[data-testid="stDataFrame"] th { background-color: #1a2340 !important; color: #90caf9 !important; }
[data-testid="stDataFrame"] td { color: #d0d8f0 !important; }
.stCode code { color: #90caf9 !important; background: #1a1f2e !important; }

.stDownloadButton > button {
    background: linear-gradient(135deg, #1b5e20, #2e7d32) !important;
    color: #ffffff !important; border: none !important;
    border-radius: 8px !important; font-weight: 600 !important;
}

#MainMenu { visibility: hidden; }
footer    { visibility: hidden; }
header    { visibility: hidden; }
</style>
"""


def inject_css():
    import streamlit as st
    st.markdown(MAIN_CSS, unsafe_allow_html=True)
