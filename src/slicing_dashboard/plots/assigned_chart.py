"""
Assigned videos horizontal stacked bar chart builder segmented by ID.
"""

from datetime import date
import pandas as pd
import plotly.graph_objects as go
from slicing_dashboard.plots.guardrails import safe_chart, checked_frame, add_bar_total_labels
from slicing_dashboard.management.periods import today_iso

from slicing_dashboard.plots.theme import (
    CHART_HEIGHT,
    format_seconds,
    theme_ctx,
)


def _get_assigned_color(days: float) -> str:
    """Return color from light green to forest green to olive green based on assignment age."""
    if days <= 0:
        return "#86efac"  # Vibrant Light Green (Today / Fresh)
    elif days == 1:
        return "#4ade80"  # Fresh Green (1 day ago)
    elif days == 2:
        return "#22c55e"  # Medium Green (2 days ago)
    elif days in (3, 4):
        return "#15803d"  # Forest Green (3-4 days ago)
    else:
        return "#14532d"  # Deep Forest / Olive (5+ days ago)


def _get_rework_color(days: float) -> str:
    """Return color from light red/pink to dark red based on the latest return age."""
    if days <= 0:
        return "#fda4af"  # Light Pink / Rose (Today / Fresh)
    elif days == 1:
        return "#fb7185"  # Soft Rose Red (1 day ago)
    elif days == 2:
        return "#f43f5e"  # Coral Red (2 days ago)
    elif days in (3, 4):
        return "#dc2626"  # Crimson Red (3-4 days ago)
    else:
        return "#991b1b"  # Deep Dark Red (5+ days ago)


@safe_chart
def build_assigned_chart(assigned_df: pd.DataFrame, is_dark: bool) -> go.Figure:
    """Build horizontal stacked bar chart of assigned videos segmented by ID.

    Each slicer's bar is stacked by their assigned accounts/IDs.
    Colors transition:
    - New Assigned: Light Green -> Forest Green -> Olive Green (based on days assigned)
    - Rework Assigned: Light Red/Pink -> Coral Red -> Dark Red (based on days returned)
    """
    t = theme_ctx(is_dark)
    assigned_df = checked_frame(assigned_df, ['User', 'Stage', 'Duration'], ['Duration', 'Count'])
    errors = assigned_df.attrs.get('assignment_errors', [])

    if assigned_df.empty:
        fig = go.Figure()
        fig.add_annotation(
            text="Current assignment data unavailable; refresh to retry" if errors else "No assigned work active",
            showarrow=False,
            font={"size": 14, "color": t["font_color"]},
        )
        fig.update_layout(
            title="Assigned & Rework by ID (Hours)",
            template=t["template"],
            paper_bgcolor=t["bg_color"],
            plot_bgcolor=t["bg_color"],
            font=dict(family="Inter, sans-serif", color=t["font_color"]),
            height=CHART_HEIGHT,
        )
        return fig

    df = assigned_df.copy()
    if "ID" not in df.columns:
        df["ID"] = df.get("IDs", df["User"])
    if "Count" not in df.columns:
        df["Count"] = 0
    today = date.fromisoformat(today_iso())
    def _calc_days(value):
        try:
            return max(0, (today - date.fromisoformat(str(value))).days)
        except (ValueError, TypeError):
            return 0

    for column, age_column in [('AssignedDate', 'DaysAssigned'), ('ReturnedDate', 'DaysReturned')]:
        if column not in df:
            df[column] = ''
        df[column] = df[column].fillna('')
        if age_column not in df:
            df[age_column] = df[column].apply(_calc_days)
        else:
            df[age_column] = df[age_column].fillna(df[column].apply(_calc_days))
    df = checked_frame(df, ['User', 'Stage', 'Duration'], ['DaysAssigned', 'DaysReturned'])
    df['ColorAge'] = df['DaysAssigned'].where(df['Stage'] != 'Rework Assigned', df['DaysReturned'])

    def _date_label(value, days):
        if not value:
            return 'Unknown'
        age = 'Today' if days <= 0 else f'{int(days)}d ago'
        return f'{value} · {age}'

    # Order users by total assigned duration (ascending for horizontal bar chart)
    user_totals = df.groupby("User")["Duration"].sum()
    users_sorted = user_totals.sort_values(ascending=True).index.tolist()
    max_hours = (user_totals.max() / 3600) if not user_totals.empty else 0
    max_range = max_hours * 1.15 if (max_hours and max_hours > 0) else 1

    fig = go.Figure()

    # Pre-add legend guide dummy traces using Scatter markers (avoids null categories in bar traces)
    fig.add_trace(
        go.Scatter(
            name="Assigned (Fresh: Light Green)",
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(size=10, symbol="square", color="#86efac"),
            showlegend=True,
            visible='legendonly',
        )
    )
    fig.add_trace(
        go.Scatter(
            name="Assigned (Aged: Forest -> Olive)",
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(size=10, symbol="square", color="#14532d"),
            showlegend=True,
            visible='legendonly',
        )
    )
    fig.add_trace(
        go.Scatter(
            name="Rework (Returned today: Pink)",
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(size=10, symbol="square", color="#fda4af"),
            showlegend=True,
            visible='legendonly',
        )
    )
    fig.add_trace(
        go.Scatter(
            name="Rework (Returned earlier: Dark Red)",
            x=[None],
            y=[None],
            mode="markers",
            marker=dict(size=10, symbol="square", color="#991b1b"),
            showlegend=True,
            visible='legendonly',
        )
    )

    border_color = "rgba(255,255,255,0.25)" if is_dark else "rgba(0,0,0,0.18)"

    # One trace per segment position shares bar settings across users while
    # keeping the original stacking order and a hover record for every account.
    segments = []
    for user in users_sorted:
        u_df = df[df["User"] == user].copy()
        # Sort user segments: New Assigned first (fresh to older), then Rework Assigned (fresh to older)
        u_df["Stage_Sort"] = u_df["Stage"].apply(lambda s: 0 if s == "New Assigned" else 1)
        u_df = u_df.sort_values(by=["Stage_Sort", "ColorAge", "Duration"], ascending=[True, True, True])

        for segment_index, (_, row) in enumerate(u_df.iterrows()):
            stage = row["Stage"]
            raw_id = str(row["ID"])
            dur_sec = float(row["Duration"])
            dur_hours = dur_sec / 3600.0
            cnt = int(row["Count"])
            days = float(row["DaysAssigned"])
            date_str = str(row["AssignedDate"])
            return_days = float(row['DaysReturned'])
            returned_str = str(row['ReturnedDate'])

            if stage == "Rework Assigned":
                color = _get_rework_color(return_days) if returned_str else '#94a3b8'
            else:
                color = _get_assigned_color(days) if date_str else '#94a3b8'

            fmt_dur = format_seconds(dur_sec)
            date_label = _date_label(date_str, days)
            if date_str and row.get('AssignmentDateBasis') == 'Account batch date':
                date_label += ' (account batch date)'
            return_label = ('<br>Returned on: ' + _date_label(returned_str, return_days)
                            if stage == 'Rework Assigned' else '')
            
            # Show ID on bar if block is wide enough
            in_bar_text = f"{raw_id}" if dur_hours >= 0.7 else (f"{fmt_dur}" if dur_hours >= 0.4 else "")

            # Ensure legible text contrast
            text_color = "#0f172a" if (color in ["#86efac", "#4ade80", "#22c55e", "#fda4af", "#fb7185"]) else "#ffffff"

            if segment_index == len(segments):
                segments.append({"x": [], "y": [], "color": [], "text": [],
                                 "text_color": [], "customdata": []})
            segment = segments[segment_index]
            segment["x"].append(dur_hours)
            segment["y"].append(user)
            segment["color"].append(color)
            segment["text"].append(in_bar_text)
            segment["text_color"].append(text_color)
            segment["customdata"].append([fmt_dur, stage, cnt, raw_id, date_label, dur_hours, return_label])

    for segment in segments:
        fig.add_trace(go.Bar(
            x=segment["x"], y=segment["y"], orientation="h",
            marker=dict(color=segment["color"], line=dict(color=border_color, width=1.5)),
            text=segment["text"], textposition="inside",
            textfont=dict(size=10, weight="bold", color=segment["text_color"]),
            customdata=segment["customdata"],
            hovertemplate=(
                "<b>%{y}</b><br>"
                "%{customdata[1]}<br>"
                "%{customdata[0]}<br>"
                "ID: %{customdata[3]}<br>"
                "Assigned on: %{customdata[4]}%{customdata[6]}<extra></extra>"
            ), showlegend=False,
        ))

    num_users = len(users_sorted)
    # Dynamic height: 38px per user bar + 110px for title, axis, legend, and margins
    dynamic_height = max(260, num_users * 38 + 110)

    fig.update_layout(
        barmode="stack",
        template=t["template"],
        plot_bgcolor=t["bg_color"],
        paper_bgcolor=t["bg_color"],
        font=dict(family="Inter, sans-serif", size=12, color=t["font_color"]),
        title=dict(text="Assigned & Rework by ID (Hours)", font=dict(size=15, weight="bold")),
        height=dynamic_height,
        margin=dict(l=10, r=30, t=45, b=65),
        bargap=0.3,
        showlegend=True,
        legend=dict(
            orientation="h",
            yanchor="top",
            y=-0.19,
            xanchor="center",
            x=0.5,
            font=dict(size=10, color=t["font_color"]),
            bgcolor="rgba(0,0,0,0)",
        ),
        hoverlabel=dict(
            bgcolor=t["hover_bg"],
            font_color=t["hover_fg"],
            font_size=13,
        ),
        xaxis_title="Hours",
        xaxis=dict(
            type='linear',
            range=[0, max_range],
            automargin=True,
            tickfont=dict(size=11),
            showgrid=True,
            gridcolor="rgba(128,128,128,0.2)",
            zeroline=False,
        ),
        yaxis_title="",
        yaxis=dict(
            type='category',
            categoryorder="array",
            categoryarray=users_sorted,
            automargin=True,
            tickfont=dict(size=12, weight="bold"),
        ),
    )

    if errors:
        fig.add_annotation(text="Current assignment data incomplete; refresh to retry",
                           x=.5, y=1.1, xref='paper', yref='paper', showarrow=False)
    return add_bar_total_labels(fig, 'h')
