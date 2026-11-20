"""Completed video duration and effective (completed + pending review) work per user."""
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import checked_frame, pad_hour_axis, safe_chart, state_figure, hour_total_label
from slicing_dashboard.plots.theme import format_seconds, theme_ctx, user_color


@safe_chart
def build_individual_chart(breakdown_df, start_date: str, end_date: str, is_dark: bool,
                           pending_df=None, pending_available=False) -> go.Figure:
    """Draw completed lollipops and a separate effective-work diamond.

    Completed is source-dated output in the selected period. Pending Review is
    current queue inventory; only show their sum when that capture is available.
    One pending video belongs to exactly one review stage in the source panel.
    """
    theme = theme_ctx(is_dark)
    frame = checked_frame(breakdown_df, ['User', 'Completed Duration'], ['Completed Duration'])
    completed = (frame.groupby('User')['Completed Duration'].sum(min_count=1).to_dict()
                 if not frame.empty else {})
    pending = {}
    if pending_available:
        if pending_df is None:
            raise ValueError('Pending review capture marked available without a frame')
        queue = checked_frame(pending_df, ['User', 'Stage', 'Duration'], ['Duration'])
        if not queue.empty:
            from slicing_dashboard.plots.pending_chart import STAGES
            if not queue['Stage'].isin(STAGES).all():
                raise ValueError('Invalid pending review stages')
            pending = queue.groupby('User')['Duration'].sum(min_count=1).to_dict()

    # A user with zero completed AND zero pending duration has contributed no
    # paid video duration in this view. Pending-only contributors remain visible.
    users = sorted(
        (user for user in set(completed) | set(pending)
         if completed.get(user, 0) + pending.get(user, 0) > 0),
        key=lambda user: (-(completed.get(user, 0) + pending.get(user, 0)),
                          str(user).casefold()))
    if not users:
        return state_figure('No completed or pending-review work available for this selection.', is_dark)

    figure = go.Figure()
    marker_color = '#c2fd75' if is_dark else '#0d9488'
    for user in users:
        seconds = float(completed.get(user, 0))
        queue_seconds = float(pending.get(user, 0)) if pending_available else 0.0
        total = seconds + queue_seconds
        hours, effective_hours = seconds / 3600, total / 3600
        color = user_color(user)
        figure.add_shape(type='line', x0=user, x1=user, y0=0, y1=hours,
                         line={'color': color, 'width': 3}, layer='below')
        if pending_available and queue_seconds > 0:
            figure.add_shape(type='line', x0=user, x1=user, y0=hours, y1=effective_hours,
                             line={'color': marker_color, 'width': 2, 'dash': 'dot'}, layer='below')
        figure.add_trace(go.Scatter(
            name=user, x=[user], y=[hours], mode='markers+text',
            marker={'color': color, 'size': 13, 'symbol': 'circle',
                    'line': {'color': color, 'width': 2}},
            text=[hour_total_label(hours)],
            # Opposite-side labels keep values clear of both the stem and
            # nearby endpoint markers, even for a small pending increment.
            textposition='middle left' if pending_available and queue_seconds > 0 else 'middle right',
            cliponaxis=False, textfont={'size': 10},
            customdata=[[format_seconds(seconds), format_seconds(queue_seconds),
                         format_seconds(total)]],
            hovertemplate=('<b>%{x}</b><br>Completed: %{customdata[0]}'
                           '<br>Pending review: %{customdata[1]}'
                           '<br>Effective work: %{customdata[2]}<extra></extra>'),
            showlegend=False,
        ))
        if pending_available and queue_seconds > 0:
            figure.add_trace(go.Scatter(
                name=user + ' effective work', x=[user], y=[effective_hours],
                mode='markers+text', marker={'color': marker_color, 'size': 13,
                                              'symbol': 'diamond',
                                              'line': {'color': theme['bg_color'], 'width': 1}},
                text=[hour_total_label(effective_hours)], textposition='middle right',
                cliponaxis=False, textfont={'size': 10},
                customdata=[[format_seconds(seconds), format_seconds(queue_seconds),
                             format_seconds(total)]],
                hovertemplate=('<b>%{x}</b><br>Completed: %{customdata[0]}'
                               '<br>Pending review: %{customdata[1]}'
                               '<br>Combined effective work: %{customdata[2]}<extra></extra>'),
                showlegend=False,
            ))
    subtitle = ('Circle: completed · Diamond: completed + current pending review ·'
                ' pending inventory is live, not period-dated' if pending_available else
                'Completed only · current pending-review evidence unavailable')
    figure.update_layout(
        title={'text': 'Completed duration and effective work',
               'subtitle': {'text': subtitle, 'font': {'size': 10}}},
        template=theme['template'],
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=420, margin={'l': 55, 'r': 24, 't': 85, 'b': 48},
        xaxis={'title': '', 'showgrid': False,
               'categoryorder': 'array', 'categoryarray': users,
               'range': [-0.85, len(users) - 0.15]},
        yaxis={'title': 'Video hours', 'showgrid': True},
        clickmode='event+select', hovermode='closest', showlegend=False,
        meta={'chart_role': 'effective-work-duration',
              'pending_available': bool(pending_available),
              'completed_seconds': sum(completed.values()),
              'pending_seconds': sum(pending.values()) if pending_available else None,
              'effective_seconds': (sum(completed.values()) + sum(pending.values())
                                    if pending_available else None),
              'completed_scope': 'selected_period',
              'pending_scope': 'current_inventory' if pending_available else 'unavailable'},
    )
    return pad_hour_axis(figure)
