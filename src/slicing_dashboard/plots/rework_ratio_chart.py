"""Return-weighted rework stacks with tier-specific duration and account evidence."""
from html import escape

import pandas as pd
import plotly.graph_objects as go

from slicing_dashboard.plots.guardrails import safe_chart, checked_frame, finite_number, state_figure
from slicing_dashboard.plots.theme import CHART_HEIGHT, theme_ctx, format_seconds

TIERS = ('No Rework', '1 Rework', '2 Reworks', '3+ Reworks')
LEGACY_UPPER = ('3 Reworks', '4 Reworks', '5+ Reworks')


def _tier_hours(row, sources, count):
    """Older captures lack tier durations; never allocate the person's total by count."""
    if not count:
        return 0.
    durations = row.get('Tier Duration (hrs)')
    if not isinstance(durations, dict):
        return None
    values = [finite_number(durations.get(tier)) for tier in sources if row.get(tier, 0)]
    return sum(values) if values and all(value is not None for value in values) else None


def _tier_ids(row, sources):
    scoped = row.get('Tier IDs')
    if not isinstance(scoped, dict):
        return set()
    return {account.strip() for tier in sources for account in str(scoped.get(tier) or '').split(',')
            if account.strip()}


def _prepare_stacks(frame):
    """Fold legacy six-tier captures and completion states without losing exact return weights."""
    combined = {}
    for row in frame.to_dict('records'):
        counts = [row.get('No Rework', 0), row.get('1 Rework', row.get('Reworked Once', 0)),
                  row.get('2 Reworks', row.get('Reworked Twice+', 0))]
        sources = [[tier] for tier in TIERS[:3]]
        if '3+ Reworks' in row:
            upper = row['3+ Reworks']
            upper_weight = row.get('3+ Return Count', upper * 3)
            sources.append(['3+ Reworks'])
        else:
            upper = sum(row.get(tier, 0) for tier in LEGACY_UPPER)
            five = row.get('5+ Reworks', 0)
            five_weight = row.get('5+ Return Count', five * 5)
            if five_weight < five * 5 or (five == 0 and five_weight != 0):
                raise ValueError('Invalid return count for the legacy 5+ rework tier')
            upper_weight = row.get('3 Reworks', 0) * 3 + row.get('4 Reworks', 0) * 4 + five_weight
            sources.append(list(LEGACY_UPPER))
        counts.append(upper)
        if any(value != int(value) for value in counts) or sum(counts) != row['Total Batches']:
            raise ValueError('Rework tiers do not match submitted batch totals')
        if upper_weight < upper * 3 or (upper == 0 and upper_weight != 0) or upper_weight != int(upper_weight):
            raise ValueError('Invalid return count for the 3+ rework tier')
        weights = [counts[0], counts[1], counts[2] * 2, upper_weight]
        result = combined.setdefault(row['User'], {'counts': [0] * 4, 'weights': [0] * 4,
            'hours': [0.] * 4, 'ids': [set() for _ in TIERS], 'total': 0})
        result['total'] += row['Total Batches']
        for index, (count, weight, scoped) in enumerate(zip(counts, weights, sources)):
            result['counts'][index] += count
            result['weights'][index] += weight
            hours = _tier_hours(row, scoped, count)
            result['hours'][index] = (result['hours'][index] + hours
                                    if result['hours'][index] is not None and hours is not None else None)
            result['ids'][index].update(_tier_ids(row, scoped))
    return combined


@safe_chart
def build_rework_ratio_chart(ratio_df: pd.DataFrame, start_date: str, is_dark: bool,
                             effective_users: list | None = None,
                             is_filtering: bool = False) -> go.Figure:
    """Four weighted tiers; each hover reports only that stack's actual video hours.

    Batch duration counts once in its tier. Return counts still determine the
    percentage weights. Legacy captures without scoped durations show Unavailable.
    """
    theme = theme_ctx(is_dark)
    numeric = ['Total Batches', *TIERS, *LEGACY_UPPER, '3+ Return Count', '5+ Return Count',
               'Reworked Once', 'Reworked Twice+', 'Total Duration (hrs)', 'Avg Batch Duration (hrs)']
    frame = checked_frame(ratio_df, ['User', 'Total Batches'], numeric)
    if frame.empty:
        return state_figure('No submitted batch data available.', is_dark)
    if is_filtering and effective_users:
        frame = frame[frame['User'].isin(effective_users)]
    frame = frame[frame['Total Batches'] > 0]
    if frame.empty:
        return state_figure('No submitted batch data available.', is_dark)
    grouping = ['User', 'Completion State'] if 'Completion State' in frame else ['User']
    if 'Completion State' in frame and not frame['Completion State'].isin(['Completed', 'Pending approvals']).all():
        raise ValueError('Unknown batch completion state')
    if frame.duplicated(grouping).any():
        raise ValueError('Duplicate user batch totals')
    stacks = _prepare_stacks(frame.sort_values(grouping))
    users = list(stacks)
    figure = go.Figure()
    # Keep the established rework severity colors for the remaining tiers.
    colors = (['#10b981', '#facc15', '#f59e0b', '#991b1b'] if is_dark else
              ['#059669', '#eab308', '#d97706', '#7f1d1d'])
    for index, (tier, color) in enumerate(zip(TIERS, colors)):
        values, customdata = [], []
        for user in users:
            stack = stacks[user]
            count, hours = stack['counts'][index], stack['hours'][index]
            weight = stack['weights'][index]
            values.append(weight / sum(stack['weights']) * 100)
            average = hours / count if hours is not None and count else None
            ids = escape(', '.join(sorted(stack['ids'][index])) or 'Unavailable')
            customdata.append([count, stack['total'], count / stack['total'] * 100, weight,
                               hours, average, format_seconds(hours * 3600 if hours is not None else None), ids])
        figure.add_trace(go.Bar(
            name='No recorded rework' if index == 0 else tier, x=users, y=values,
            marker={'color': color, 'line': {'width': 0}}, customdata=customdata,
            textposition='none',
            textfont={'size': 10, 'color': 'white'},
            hovertemplate=(f'<b>%{{x}}</b><br>{tier}<br>Duration: %{{customdata[6]}}'
                           '<br>Return-weighted share: %{y:.1f}%'
                           '<br>Batch count: %{customdata[0]}<br>IDs: %{customdata[7]}<extra></extra>'),
        ))
    figure.update_layout(
        barmode='stack', title='Return-weighted reworks', template=theme['template'],
        paper_bgcolor=theme['bg_color'], plot_bgcolor=theme['bg_color'],
        font={'family': 'Inter, sans-serif', 'size': 12, 'color': theme['font_color']},
        height=CHART_HEIGHT, margin={'l': 45, 'r': 16, 't': 52, 'b': 100},
        hovermode='closest', showlegend=True,
        hoverlabel={'bgcolor': theme['hover_bg'], 'font_color': theme['hover_fg'], 'font_size': 13},
        xaxis={'showgrid': False, 'automargin': True, 'tickfont': {'size': 11}},
        yaxis={'title': '% of Weighted Total', 'range': [0, 100], 'showgrid': True,
               'automargin': True, 'ticksuffix': '%', 'tickfont': {'size': 11}},
    )
    return figure
