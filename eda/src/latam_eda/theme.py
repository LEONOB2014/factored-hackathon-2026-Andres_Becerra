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


# plotly colorscales built from the same ramps (light = low; gray midpoint for correlations)
SEQ_SCALE = [[i / len(SEQ_BLUE), c] for i, c in enumerate(["#f4f8fd", *SEQ_BLUE])]
DIV_SCALE = [[i / (len(DIV) - 1), c] for i, c in enumerate(DIV)]


def register_mpl():
    """matplotlib/seaborn rcParams matching the plotly template (missingno draws with these)."""
    import matplotlib as mpl
    from cycler import cycler

    mpl.rcParams.update(
        {
            "figure.facecolor": SURFACE,
            "axes.facecolor": SURFACE,
            "savefig.facecolor": SURFACE,
            "axes.edgecolor": GRID,
            "axes.labelcolor": INK2,
            "axes.titlecolor": INK,
            "axes.titlesize": 12,
            "axes.titlelocation": "left",
            "axes.grid": True,
            "axes.axisbelow": True,
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.prop_cycle": cycler(color=CATEGORICAL),
            "grid.color": GRID,
            "grid.linewidth": 0.8,
            "text.color": INK,
            "xtick.color": INK2,
            "ytick.color": INK2,
            "legend.frameon": False,
            "font.family": "sans-serif",
            "font.sans-serif": ["Inter", "Helvetica Neue", "Arial", "DejaVu Sans"],
            "font.size": 10,
        }
    )


def cmap_seq():
    """Sequential blue matplotlib colormap (light = low) for counts and rates."""
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("latam_seq", ["#f4f8fd", *SEQ_BLUE])


def cmap_div():
    """Diverging blue <-> red matplotlib colormap with a gray midpoint, for correlations."""
    from matplotlib.colors import LinearSegmentedColormap

    return LinearSegmentedColormap.from_list("latam_div", DIV)
