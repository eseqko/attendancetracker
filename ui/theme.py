"""Global look & feel: one CSS injection, called once per page render.

Minimalist light theme — white cards on Apple's soft gray, the system SF
font stack, a single blue accent, hairline borders, and no Streamlit chrome.
"""

from __future__ import annotations

import streamlit as st

FONT_STACK = (
    '-apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", Roboto, '
    '"Helvetica Neue", Arial, sans-serif'
)

_CSS = f"""
<style>
/* ---- type ---------------------------------------------------------- */
html, body, [class*="css"], .stApp {{
    font-family: {FONT_STACK};
    color: #1d1d1f;
    -webkit-font-smoothing: antialiased;
}}
h1 {{
    font-weight: 700 !important;
    letter-spacing: -0.02em !important;
    font-size: 2.1rem !important;
    padding-bottom: 0 !important;
}}
h2, h3 {{
    font-weight: 600 !important;
    letter-spacing: -0.01em !important;
    color: #1d1d1f !important;
}}
h3 {{
    font-size: 1.25rem !important;
    margin-top: 1.2rem !important;
}}
[data-testid="stCaptionContainer"] p {{
    color: #6e6e73;
    font-size: 0.86rem;
}}

/* ---- hide Streamlit chrome (all menu positions) -------------------- */
#MainMenu, footer, .stDeployButton, [data-testid="stDecoration"],
[data-testid="stStatusWidget"], [data-testid="stAppDeployButton"],
[data-testid="stMainMenu"], [data-testid="stToolbarActions"] {{
    display: none !important;
    visibility: hidden !important;
}}
.block-container {{ padding-top: 2.4rem; max-width: 62rem; }}

/* ---- sidebar ------------------------------------------------------- */
[data-testid="stSidebar"] {{
    background: #f5f5f7;
    border-right: 1px solid #e8e8ed;
}}
[data-testid="stSidebar"] [data-testid="stSidebarNav"] a {{
    border-radius: 10px;
    font-weight: 500;
}}
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] p {{
    color: #86868b;
    font-size: 0.78rem;
}}

/* ---- metrics as stat tiles ----------------------------------------- */
[data-testid="stMetric"] {{
    background: #ffffff;
    border: 1px solid #e8e8ed;
    border-radius: 14px;
    padding: 0.9rem 1.1rem;
}}
[data-testid="stMetricLabel"] p {{
    color: #6e6e73 !important;
    font-size: 0.8rem !important;
    font-weight: 500 !important;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}}
[data-testid="stMetricValue"] {{
    font-weight: 600;
    letter-spacing: -0.02em;
    font-size: 2rem;
}}
[data-testid="stMetricDelta"] {{ font-size: 0.82rem; }}

/* ---- buttons ------------------------------------------------------- */
.stButton > button, .stDownloadButton > button {{
    border-radius: 980px;
    border: 1px solid #d2d2d7;
    background: #ffffff;
    color: #1d1d1f;
    font-weight: 500;
    padding: 0.35rem 1.1rem;
    transition: background 0.15s ease, border-color 0.15s ease;
}}
.stButton > button:hover, .stDownloadButton > button:hover {{
    border-color: #0071e3;
    color: #0071e3;
    background: #ffffff;
}}
.stButton > button[kind="primary"] {{
    background: #0071e3;
    border-color: #0071e3;
    color: #ffffff;
}}
.stButton > button[kind="primary"]:hover {{
    background: #0077ed;
    color: #ffffff;
}}

/* ---- inputs, pickers, expanders ------------------------------------ */
[data-testid="stFileUploaderDropzone"] {{
    background: #f5f5f7;
    border: 1.5px dashed #d2d2d7;
    border-radius: 14px;
}}
[data-testid="stExpander"] {{
    border: 1px solid #e8e8ed;
    border-radius: 14px;
}}
[data-testid="stExpander"] summary {{ font-weight: 500; }}

/* ---- alerts (info/success/warning) --------------------------------- */
[data-testid="stAlert"] {{
    border-radius: 14px;
    border: 1px solid #e8e8ed;
}}

/* ---- tables -------------------------------------------------------- */
[data-testid="stDataFrame"] {{
    border: 1px solid #e8e8ed;
    border-radius: 14px;
    overflow: hidden;
}}

/* ---- misc ---------------------------------------------------------- */
hr {{ border-color: #e8e8ed; margin: 1.6rem 0; }}
[data-testid="stWidgetLabel"] p {{ color: #494949; font-size: 0.86rem; }}
</style>
"""

#: Sidebar menu (left/right): no visible header, and the menu is pinned —
#: the collapse chevron is removed so the menu can't disappear. If Streamlit
#: still auto-collapses it (narrow window), the reopen button is forced
#: visible and floated so there is always a way back.
_SIDEBAR_MODE_CSS = """
<style>
[data-testid="stToolbar"] { display: none !important; }
.stApp > header { background: transparent; height: 0; }
[data-testid="stSidebarCollapseButton"] { display: none !important; }
[data-testid="stExpandSidebarButton"] {
    display: flex !important;
    opacity: 1 !important;
    visibility: visible !important;
    position: fixed;
    top: 0.7rem;
    left: 0.7rem;
    z-index: 9999;
    background: #ffffff;
    border: 1px solid #e8e8ed;
    border-radius: 10px;
    padding: 0.25rem;
}
</style>
"""

_RIGHT_MODE_CSS = """
<style>
[data-testid="stAppViewContainer"] { flex-direction: row-reverse; }
[data-testid="stSidebar"] {
    border-right: none;
    border-left: 1px solid #e8e8ed;
}
[data-testid="stExpandSidebarButton"] { left: auto; right: 0.7rem; }
</style>
"""

#: Top-bar menu: the nav links render inside the header toolbar, so the
#: toolbar must stay visible (its buttons are hidden individually above).
_TOP_MODE_CSS = """
<style>
[data-testid="stHeader"] {
    background: #ffffff;
    border-bottom: 1px solid #e8e8ed;
}
[data-testid="stTopNavLink"] { border-radius: 10px; }
[data-testid="stTopNavLink"] span { font-weight: 500; }
.block-container { padding-top: 4.8rem; }
</style>
"""

_BOTTOM_MODE_CSS = """
<style>
[data-testid="stHeader"] {
    top: auto !important;
    bottom: 0 !important;
    border-top: 1px solid #e8e8ed;
    border-bottom: none;
}
.block-container { padding-top: 2.4rem; padding-bottom: 6rem; }
</style>
"""

MENU_POSITIONS = ("left", "top", "bottom", "right")


def inject(menu_position: str = "left") -> None:
    st.markdown(_CSS, unsafe_allow_html=True)
    if menu_position in ("top", "bottom"):
        st.markdown(_TOP_MODE_CSS, unsafe_allow_html=True)
        if menu_position == "bottom":
            st.markdown(_BOTTOM_MODE_CSS, unsafe_allow_html=True)
    else:
        st.markdown(_SIDEBAR_MODE_CSS, unsafe_allow_html=True)
        if menu_position == "right":
            st.markdown(_RIGHT_MODE_CSS, unsafe_allow_html=True)
