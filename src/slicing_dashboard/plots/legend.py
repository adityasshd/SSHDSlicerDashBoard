"""
Universal user legend (clickable filter) builder.
"""

import plotly.graph_objects as go
from textwrap import wrap
from html import escape

from slicing_dashboard.plots.theme import CHART_HEIGHT, user_color, theme_ctx


def build_legend_figure(
    available_users: list,
    current_selection: list,
    is_dark: bool,
) -> go.Figure:
    """Build a figure that serves as a clickable user-filter legend.

    Parameters
    ----------
    available_users : list of all user names
    current_selection : list of currently selected user names
    is_dark : bool
    """
    t = theme_ctx(is_dark)
    fig = go.Figure()

    for u in dict.fromkeys(available_users or []):
        is_visible = u in current_selection
        fig.add_trace(
            go.Scatter(
                x=[None],
                y=[None],
                name='<br>'.join(escape(part) for part in wrap(str(u), 20)),
                mode="markers",
                marker=dict(color=user_color(u), size=10),
                showlegend=True,
                visible=True if is_visible else "legendonly",
            )
        )

    fig.update_layout(
        template=t["template"],
        font={'color': t['font_color'], 'family': 'Inter, sans-serif'},
        title={'text': 'Team members', 'font': {'size': 14}, 'x': .08, 'y': .94},
        showlegend=True,
        legend=dict(
            orientation="v",
            yanchor="top",
            y=1,
            xanchor="left",
            x=0,
            font=dict(color=t["font_color"], size=11),
            maxheight=.95,
        ),
        height=CHART_HEIGHT,
        margin=dict(l=16, r=12, t=48, b=16),
        plot_bgcolor=t["bg_color"],
        paper_bgcolor=t["bg_color"],
        xaxis=dict(visible=False),
        yaxis=dict(visible=False),
        hovermode=False,
        # Change revision when a dashboard-wide selection changes so the
        # legend cannot preserve a stale local visibility state.
        uirevision=('user-filter-legend', tuple(
            u for u in dict.fromkeys(available_users or []) if u in current_selection)),
    )
    return fig
