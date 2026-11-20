"""Major return reasons categorized and segmented by user."""
from __future__ import annotations
from collections import Counter, defaultdict
from html import escape
from typing import Any
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart
from slicing_dashboard.plots.theme import theme_ctx
from slicing_dashboard.processing.daily_work import instant

REASON_CATEGORIES = [
    'Combined Actions',
    'Missing Action',
    'Hand Visibility Issue',
    'No Hand Action',
    'Over-Segmentation',
    'Error Task / Defect',
    'Prohibited Subject',
    'Guidelines / Other',
    'No reviewer note',
]

REASON_COLORS = {
    'Combined Actions': '#636EFA',            # Indigo / Blue
    'Missing Action': '#EF553B',              # Coral / Red
    'Hand Visibility Issue': '#FFA15A',       # Orange
    'No Hand Action': '#FECB52',              # Amber / Gold
    'Over-Segmentation': '#AB63FA',           # Purple
    'Error Task / Defect': '#19D3F3',          # Cyan / Teal
    'Prohibited Subject': '#FF6692',          # Pink
    'Guidelines / Other': '#94A3B8',          # Slate Gray
    'No reviewer note': '#64748B',
}


def classify_return_reason(text: str) -> list[str]:
    """Extract distinct quality issue categories from reviewer notes."""
    if not text or not text.strip():
        return ['No reviewer note']

    t = text.lower()
    categories = []

    # Combined / merged actions
    if any(k in t for k in [
        'combined into a single', 'multiple actions', 'merge of 2 actions',
        'separate clip', 'placing it down', 'each action should be',
    ]):
        categories.append('Combined Actions')

    # Missing action
    if any(k in t for k in [
        'missing action', 'action missing', 'valid action missing', 'actions missing',
        'points missing', 'missing some points',
    ]):
        categories.append('Missing Action')

    # Idle / No hand action
    if any(k in t for k in [
        'no hand action', 'dont need to clip', 'dont need to segment',
        "don't need to segment", 'empty handed', 'only touch is not a valid',
        'no action performed',
    ]):
        categories.append('No Hand Action')

    # Acting hand visibility (start, end, 90% threshold)
    if any(k in t for k in [
        'acting hand must be visible', 'hand visibility', 'hand vsisbility',
        'hand must appear', 'hand is not visible', 'no hand visible',
        'hands must be visible', 'insufficient hand visibility',
    ]):
        categories.append('Hand Visibility Issue')

    # Over-segmentation / unnecessary fragmentation
    if any(k in t for k in [
        'unnecessarily split', 'fragmented unnecessarily', 'unnecessarily fragmented',
        'keep one meaningful action', 'continuous action has been fragmented',
        'combine these actions',
    ]):
        categories.append('Over-Segmentation')

    # Error task / video defects (flicker, flashing, wrong error flag)
    if any(k in t for k in [
        'flicker', 'flashing', 'error task', 'error video', 'marked as an error',
        'mark as error', 'green/black',
    ]):
        categories.append('Error Task / Defect')

    # Prohibited subjects (eating, drinking, phone, laptop)
    if any(k in t for k in [
        'phone', 'laptop', 'eating', 'drinking',
    ]):
        categories.append('Prohibited Subject')

    if not categories:
        categories.append('Guidelines / Other')

    return categories


@safe_chart(height=380)
def build_return_reasons_chart(
    records: list[dict[str, Any]],
    is_dark: bool = True,
    selected_users: list[str] | None = None,
    start: str | None = None,
    end: str | None = None,
    canonical_map: dict[str, str] | None = None,
) -> go.Figure:
    """Build a horizontal stacked bar chart of major return reasons by user."""
    figure = go.Figure()
    theme = theme_ctx(is_dark)

    # Use the same India-time day boundaries as the submission reports.
    filtered_records = []
    seen = set()
    for r in records or []:
        event_id = r.get('event_id')
        if event_id and event_id in seen:
            continue
        if event_id:
            seen.add(event_id)
        stamp = instant(r.get('returned_at'))
        ret_date = stamp.date().isoformat() if stamp else None
        if (start or end) and not ret_date:
            continue
        if start and ret_date < start:
            continue
        if end and ret_date > end:
            continue

        raw_user = r.get('username') or ''
        canon = r.get('canonical_user') or ''
        if canonical_map and str(r.get('user_id')) in canonical_map:
            user = canonical_map[str(r['user_id'])]
        elif canonical_map and raw_user in canonical_map:
            user = canonical_map[raw_user]
        elif canon:
            user = canon
        else:
            user = raw_user or 'Unknown'

        if selected_users is not None and user not in selected_users:
            continue

        filtered_records.append((user, r.get('reason') or ''))

    # If no records in range, show an informative placeholder
    if not filtered_records:
        range_label = f" between {start} and {end}" if start and end else ""
        figure.add_annotation(
            text=f"No batch return feedback recorded{range_label}.",
            x=0.5, y=0.5, xref='paper', yref='paper', showarrow=False,
            font={"size": 13, "color": theme["font_color"]},
        )
        figure.update_layout(
            template=theme["template"],
            paper_bgcolor=theme["bg_color"],
            plot_bgcolor=theme["bg_color"],
            height=360,
            xaxis=dict(visible=False),
            yaxis=dict(visible=False),
            margin=dict(l=40, r=40, t=50, b=40),
            title={"text": "Major Return Reasons by User", "font": {"size": 14}},
        )
        return figure

    # 2. Aggregate category counts per user
    user_counts: dict[str, Counter] = defaultdict(Counter)
    user_totals: Counter = Counter()
    return_totals: Counter = Counter()

    for user, reason_text in filtered_records:
        return_totals[user] += 1
        cats = classify_return_reason(reason_text)
        for cat in cats:
            user_counts[user][cat] += 1
            user_totals[user] += 1

    # Rank by actual return events, independent of how many issues each note lists.
    sorted_users = sorted(user_totals, key=lambda user: (-return_totals[user], user.casefold()))

    # 3. Add stacked bar traces for each category
    for cat in REASON_CATEGORIES:
        x_vals = []
        custom_data = []
        for user in sorted_users:
            c = user_counts[user][cat]
            total = return_totals[user]
            pct = (c / total * 100) if total else 0.0
            x_vals.append(c)
            custom_data.append([pct, total])

        # Only add trace if there is at least one non-zero count
        if any(v > 0 for v in x_vals):
            figure.add_trace(go.Bar(
                name=cat,
                y=sorted_users,
                x=x_vals,
                orientation='h',
                marker_color=REASON_COLORS.get(cat, '#888888'),
                customdata=custom_data,
                text=[str(value) if value else '' for value in x_vals],
                textposition='inside',
                hovertemplate=(
                    "<b>%{y}</b><br>"
                    f"Reason: {cat}<br>"
                    "Returns mentioning this reason: %{x}<br>"
                    "%{customdata[0]:.1f}% of %{customdata[1]} returns<br>"
                    "One return may mention several reasons."
                    "<extra></extra>"
                ),
            ))

    date_suffix = f"{start} to {end} · " if start and end else ""
    figure.add_annotation(
        text=f"{date_suffix}{len(filtered_records)} returns · {sum(user_totals.values())} reason mentions",
        x=0, y=1.04, xref='paper', yref='paper', xanchor='left', yanchor='bottom',
        showarrow=False, font={'size': 11, 'color': theme['font_color']},
    )
    figure.update_layout(
        title={"text": "Return reasons by user", "font": {"size": 14, "color": theme["font_color"]}},
        barmode='stack',
        template=theme["template"],
        paper_bgcolor=theme["bg_color"],
        plot_bgcolor=theme["bg_color"],
        font={"family": "Inter, sans-serif", "size": 12, "color": theme["font_color"]},
        hoverlabel={"bgcolor": theme["hover_bg"], "font": {"color": theme["hover_fg"]}},
        height=max(420, 220 + len(sorted_users) * 34),
        margin={"l": 90, "r": 25, "t": 100, "b": 130},
        xaxis={
            "title": {"text": "Reason mentions (a return can count in several categories)", "font": {"size": 11}},
            "rangemode": "tozero",
            "tickformat": ",d",
            "dtick": 1 if max(user_totals.values()) <= 10 else None,
            "showgrid": True,
            "gridcolor": "rgba(128,128,128,.15)",
            "zeroline": True,
            "zerolinecolor": "rgba(128,128,128,.2)",
        },
        yaxis={
            "title": None,
            "automargin": True,
            "showgrid": False,
            "categoryorder": "array",
            "categoryarray": sorted_users,
            "autorange": "reversed",
            "tickvals": sorted_users,
            "ticktext": [f"{escape(user)} ({return_totals[user]} returns)" for user in sorted_users],
        },
        legend={
            "orientation": "h",
            "x": 0,
            "xanchor": "left",
            "y": 1.15,
            "yanchor": "bottom",
            "font": {"size": 11},
            "entrywidth": 160,
        },
    )

    return figure

