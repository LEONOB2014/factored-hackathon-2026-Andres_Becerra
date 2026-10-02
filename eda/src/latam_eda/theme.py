"""Chart theme: validated categorical palette from the dataviz reference instance.

Slots are used in fixed order, never cycled. Light surface values; text stays in ink
tokens, never in the series colour.
"""

import plotly.graph_objects as go
import plotly.io as pio

SURFACE = "#fcfcfb"
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e6e5e1"

# categorical, fixed order (light mode)
BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED = (
    "#2a78d6",
    "#eb6834",
    "#1baf7a",
    "#eda100",
    "#e87ba4",
    "#008300",
    "#4a3aa7",
    "#e34948",
)
CATEGORICAL = [BLUE, ORANGE, AQUA, YELLOW, MAGENTA, GREEN, VIOLET, RED]
MAIN_C, BACKUP_C = BLUE, ORANGE  # the two datasets keep these colours everywhere

SEQ_BLUE = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]
DIV = [
    "#184f95",
    "#3987e5",
    "#9ec5f4",
    "#f0efec",
    "#f2a6a5",
    "#e34948",
    "#a62b2b",
]  # blue <-> red, gray mid

STATUS = {"good": "#0ca30c", "warning": "#fab219", "serious": "#ec835a", "critical": "#d03b3b"}


def register():
    pio.templates["latam"] = go.layout.Template(
        layout=dict(
            paper_bgcolor=SURFACE,
            plot_bgcolor=SURFACE,
            font=dict(family="Inter, -apple-system, Segoe UI, sans-serif", color=INK, size=13),
            colorway=CATEGORICAL,
            xaxis=dict(gridcolor=GRID, linecolor=GRID, zeroline=False, tickfont=dict(color=INK2)),
            yaxis=dict(gridcolor=GRID, linecolor=GRID, zeroline=False, tickfont=dict(color=INK2)),
            legend=dict(font=dict(color=INK2), orientation="h", y=1.08, x=0),
            title=dict(font=dict(size=16), x=0, xanchor="left"),
            margin=dict(l=60, r=24, t=70, b=50),
            hoverlabel=dict(bgcolor="white", font_color=INK),
        )
    )
    pio.templates.default = "latam"
    pio.renderers.default = "plotly_mimetype+notebook_connected"
