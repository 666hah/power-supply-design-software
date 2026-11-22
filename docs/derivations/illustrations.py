"""Print palette and canvas for the derivation textbook."""

from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure


BLUE = '#185077'
ORANGE = '#a74816'
TEAL = '#087369'
INK = '#233545'
MUTED = '#596c78'

PRINT_STYLE = {
    'font.family': ['Microsoft YaHei', 'DejaVu Sans'],
    'font.size': 9.5,
    'axes.titlesize': 10.5,
    'axes.titleweight': 'bold',
    'axes.labelsize': 9,
    'axes.edgecolor': MUTED,
    'axes.labelcolor': INK,
    'text.color': INK,
    'xtick.color': MUTED,
    'ytick.color': MUTED,
    'axes.spines.top': False,
    'axes.spines.right': False,
    'axes.unicode_minus': False,
    'lines.linewidth': 1.8,
    'legend.frameon': False,
    'legend.fontsize': 8,
    'figure.facecolor': 'white',
    'savefig.facecolor': 'white',
}


def figure(width=7.1, height=2.7):
    fig = Figure(figsize=(width, height), layout='constrained')
    FigureCanvasAgg(fig)
    return fig


def panel_label(ax, text):
    ax.set_title(text, loc='left', pad=6)
