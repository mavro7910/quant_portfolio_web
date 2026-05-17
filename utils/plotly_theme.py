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

BG_PAPER   = "rgba(0,0,0,0)"         # 완전 투명 — 다크/라이트 모드 자동 적응
BG_PLOT    = "rgba(0,0,0,0)"         # 완전 투명 — 흰 박스 간섭 제거
GRID_COLOR = "rgba(15,110,86,0.15)"
TICK_COLOR = "#7aada8"               # 틸트 중간색 — 다크/라이트 모두 가독성 OK
FONT_COLOR = "#9cb8b4"               # 연한 틸트 — 다크모드 배경에서도 보임
LEGEND_BG  = "rgba(0,0,0,0)"

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
            bgcolor="rgba(15,110,86,0.9)",
            font_color="#ffffff",
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
            yanchor="bottom", y=1.02,
            xanchor="right", x=1,
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            borderwidth=0,
            font=dict(color=FONT_COLOR, size=11),
        ),
    )
