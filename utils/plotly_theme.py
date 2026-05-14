"""
utils/plotly_theme.py — QPM Alpha 공통 Plotly 테마
파스텔 틸 팔레트 기반 차트 스타일
"""

TEAL       = "#0F6E56"
BLUE       = "#4a90d9"
AMBER      = "#c9873a"
RED        = "#e05252"
PURPLE     = "#8b72c8"
GREEN      = "#5ab87a"
GRAY       = "#a0b4b2"

BG_PAPER   = "rgba(244,251,250,0)"   # transparent — 앱 배경과 자연스럽게 합성
BG_PLOT    = "rgba(255,255,255,0.7)"
GRID_COLOR = "rgba(15,110,86,0.08)"
TICK_COLOR = "#7aada8"
FONT_COLOR = "#2a3a38"
LEGEND_BG  = "rgba(255,255,255,0.85)"

LINE_COLORS = [TEAL, BLUE, AMBER, RED, PURPLE, GREEN]


def base_layout(title: str = "", height: int = 480) -> dict:
    return dict(
        title=dict(
            text=title,
            font=dict(color=FONT_COLOR, size=13, family="sans-serif"),
            x=0,
            pad=dict(l=4),
        ),
        paper_bgcolor=BG_PAPER,
        plot_bgcolor=BG_PLOT,
        font=dict(color=FONT_COLOR, size=11, family="sans-serif"),
        height=height,
        margin=dict(t=44, b=50, l=58, r=16),
        hovermode="x unified",
        hoverlabel=dict(
            bgcolor="rgba(255,255,255,0.95)",
            font_color=FONT_COLOR,
            font_size=11,
            bordercolor=TEAL,
        ),
        xaxis=dict(
            gridcolor=GRID_COLOR,
            tickfont=dict(color=TICK_COLOR, size=10),
            tickangle=-25,
            showgrid=False,
            zeroline=False,
        ),
        yaxis=dict(
            gridcolor=GRID_COLOR,
            tickfont=dict(color=TICK_COLOR, size=10),
            showgrid=True,
            zeroline=False,
        ),
        legend=dict(
            orientation="h",
            yanchor="top", y=-0.16,
            xanchor="center", x=0.5,
            bgcolor=LEGEND_BG,
            bordercolor="rgba(15,110,86,0.15)",
            borderwidth=0.5,
            font=dict(color=FONT_COLOR, size=11),
        ),
    )
