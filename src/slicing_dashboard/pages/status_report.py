"""Shared Daily/User status panel and isolated saved-first refresh callbacks."""
import dash
from dash import Input, Output, State, dcc, html
import dash_bootstrap_components as dbc
import pandas as pd
import plotly.graph_objects as go
from uuid import uuid4

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.pages.components import chart_graph, report_section
from slicing_dashboard.plots.tables import create_table
from slicing_dashboard.plots.theme import theme_ctx, format_seconds
from slicing_dashboard.reporting.status_reports import (
    STATUS_METRICS, capture_stale, get_status_report_data, refresh_status_report, summarize_status,
)


def status_stores():
    return [dcc.Store(id='report-status-store'), dcc.Store(id='report-status-request'),
            dcc.Store(id='report-status-live'), dcc.Store(id='report-status-painted')]


def status_slot(kind):
    return html.Div(id=f'{kind}-status-content', children=html.P('Loading available status metrics…',
        className='text-secondary'), **{'aria-live': 'polite'})


def _trend(history, user, is_dark):
    rows = [summarize_status(day, user) for day in history]
    figure = go.Figure()
    for metric, label, color in STATUS_METRICS:
        field = metric + '_duration_seconds'
        values = [row[field] for row in rows]
        figure.add_trace(go.Scatter(name=label, x=[row['date'] for row in rows],
            y=[v / 3600 if v is not None else None for v in values], mode='lines+markers',
            connectgaps=False, line={'color': color, 'width': 2, 'shape': 'spline', 'smoothing': .65}, marker={'size': 4},
            customdata=[format_seconds(v) for v in values],
            hovertemplate='%{x}<br>%{customdata}<extra>%{fullData.name}</extra>'))
    theme = theme_ctx(is_dark)
    figure.update_layout(template=theme['template'], paper_bgcolor=theme['bg_color'],
        plot_bgcolor=theme['bg_color'], font={'color': theme['font_color']}, height=360,
        xaxis={'title': 'Source date (UTC+08)', 'type': 'date', 'tickformat': '%d %b', 'nticks': 6},
        yaxis={'title': 'Video hours', 'rangemode': 'tozero'}, hovermode='x unified',
        legend={'orientation': 'h', 'y': -.3, 'x': 0}, margin={'l': 50, 'r': 15, 't': 15, 'b': 110},
        uirevision=f"status:{history[-1]['date']}:{user}")
    return figure


def build_status_report(data, user=None, is_dark=True, kind='daily'):
    from slicing_dashboard.pages.daily_report import _metric_card
    if not data:
        return html.P('Loading available status metrics…', className='text-secondary')
    if data.get('validation_error'):
        return dbc.Alert(data['validation_error'], color='warning')
    if kind == 'user' and not user:
        return dbc.Alert('Choose a team member to view available status metrics.', color='info')
    history = data['history']
    selected = summarize_status(history[-1], user)
    previous = summarize_status(history[-2], user)
    cards = []
    for metric, label, color in STATUS_METRICS:
        seconds = selected[metric + '_duration_seconds']
        count = selected[metric + '_count']
        before = previous[metric + '_duration_seconds']
        note = f'{int(count)} tasks' if count is not None else 'Status unavailable'
        if seconds is not None and before is not None:
            difference = seconds - before
            note += f" · {'+' if difference >= 0 else '−'}{format_seconds(abs(difference))} vs previous source day"
        cards.append(_metric_card(label, '—' if seconds is None else format_seconds(seconds),
                                  note, color, 'bi-film'))
    work = selected['work_duration_seconds']
    cards.append(_metric_card('Recorded work time', '—' if work is None else format_seconds(work),
        'Activity time reported by the source', '#a78bfa', 'bi-clock'))
    metadata = selected['metadata']
    captured = metadata.get('captured_at')
    notice = f"Captured {captured}." if captured else 'No saved status capture for this date.'
    if not selected['available'] and metadata.get('available'):
        notice = 'This person has no account rows in the selected status capture.'
    if metadata.get('error') or data.get('read_error'):
        notice += ' Latest check failed; retained values are shown where available. Refresh to retry.'
    elif capture_stale(metadata) and selected['available']:
        notice += ' Saved status; it may have changed since capture.'
    if data.get('refresh_pending'):
        notice += ' Checking the selected and previous day…'
    coverage = sum(summarize_status(day, user)['available'] for day in history)
    children = [html.P(f"{data['report_date']} · {user or 'Team'} · Source date: UTC+08",
                          className='fw-semibold small'),
        html.Div(cards, className='user-report-kpis'),
        html.P(notice, className='small text-secondary'),
        html.P('These values show current statuses for source-dated records. Pending review may include '
               'reported error videos. Rework can overlap other statuses; do not add these cards together. '
               'Fresh work and same-day rework cannot be determined from this source.', className='small text-secondary'),
        html.P(f'{coverage} of {len(history)} source days captured. Missing dates remain gaps; '
               'older statuses can change after later reviews.', className='small text-secondary'),
        chart_graph(id=f'{kind}-status-trend', figure=_trend(history, user, is_dark),
                    config={'displayModeBar': False, 'responsive': True})]
    if kind == 'daily' and metadata.get('available'):
        rows = []
        for row in history[-1].get('rows', []):
            values = summarize_status(history[-1], row['User'])
            rows.append({'User': row['User'], **{label: ('—' if values[metric + '_duration_seconds'] is None
                else format_seconds(values[metric + '_duration_seconds'])) for metric, label, _ in STATUS_METRICS},
                'Recorded work time': ('—' if values['work_duration_seconds'] is None
                                      else format_seconds(values['work_duration_seconds']))})
        if rows:
            durations = [label for _, label, _ in STATUS_METRICS] + ['Recorded work time']
            columns = [{'name': 'User', 'id': 'User'}] + [
                {'name': label + ' (HH:MM:SS)', 'id': label, 'type': 'text'} for label in durations]
            children.append(create_table(pd.DataFrame(rows), is_dark, table_id='daily-status-table',
                columns=columns, duration_columns=durations, max_height='400px'))
    return report_section('Available daily status', children,
        'The source day runs from 21:30 India time on the previous date to 21:30 on the selected date. '
        'Recorded submissions below use India calendar days.')


def _matching(value, saved):
    return bool(value and saved and all(value.get(key) == saved.get(key)
                                       for key in ('request_id', 'report_date', 'pathname')))


def register_status_reports(app, manager):
    @app.callback(Output('report-status-store', 'data'),
        Input('report-location', 'pathname'), Input('refresh-btn', 'n_clicks'),
        Input('auto-refresh-interval', 'n_intervals'), Input('daily-report-date', 'value'),
        Input('user-report-date', 'value'))
    def load_report_status(pathname, clicks, intervals, daily_date, user_date):
        if pathname not in ('/reports/daily', '/reports/user'):
            raise dash.exceptions.PreventUpdate
        trigger = dash.ctx.triggered_id
        if (pathname == '/reports/daily' and trigger == 'user-report-date'
                or pathname == '/reports/user' and trigger == 'daily-report-date'):
            raise dash.exceptions.PreventUpdate
        selected = daily_date if pathname == '/reports/daily' else user_date
        try:
            data = get_status_report_data(manager, selected or today_iso(),
                force_refresh=trigger in ('refresh-btn', 'auto-refresh-interval'))
        except (ValueError, TypeError):
            data = {'validation_error': 'Choose a valid report date on or before today.'}
        return {**data, 'pathname': pathname, 'request_id': uuid4().hex}

    @app.callback(Output('daily-status-content', 'children'), Output('user-status-content', 'children'),
        Output('report-status-request', 'data'), Output('report-status-painted', 'data'),
        Input('report-status-store', 'data'),
        State('report-status-live', 'data'), Input('theme-toggle', 'n_clicks'),
        State('user-report-person', 'value'), Input('report-location', 'pathname'),
        State('report-status-request', 'data'))
    def render_report_status(saved, live, clicks, user, pathname, requested):
        if not saved or pathname != saved.get('pathname'):
            raise dash.exceptions.PreventUpdate
        display = live if _matching(live, saved) else saved
        request = saved if (saved.get('refresh_pending') and not _matching(requested, saved)) else dash.no_update
        kind = 'daily' if pathname == '/reports/daily' else 'user'
        panel = build_status_report(display, None if kind == 'daily' else user, (clicks or 0) % 2 == 0, kind)
        painted = {key: saved.get(key) for key in ('request_id', 'report_date', 'pathname')}
        painted['paint_id'] = uuid4().hex
        return ((panel, dash.no_update, request, painted) if kind == 'daily'
                else (dash.no_update, panel, request, painted))

    @app.callback(Output('report-status-live', 'data'), Input('report-status-request', 'data'),
        State('report-location', 'pathname'), prevent_initial_call=True)
    def load_live_report_status(request, pathname):
        if not request or not request.get('refresh_pending') or pathname != request.get('pathname'):
            raise dash.exceptions.PreventUpdate
        return refresh_status_report(manager, request)

    # Live data also changes the person selector. Neither may trigger the
    # callback that starts the live read, or Dash detects a dependency cycle.
    # Repaint after the first response as well, so a slow saved paint cannot
    # overwrite a newer live result or person selection.
    @app.callback(Output('daily-status-content', 'children', allow_duplicate=True),
        Output('user-status-content', 'children', allow_duplicate=True),
        Input('report-status-live', 'data'), Input('user-report-person', 'value'),
        Input('report-status-painted', 'data'), State('report-status-store', 'data'),
        State('theme-toggle', 'n_clicks'), State('report-location', 'pathname'),
        prevent_initial_call=True)
    def render_live_report_status(live, user, painted, saved, clicks, pathname):
        if not saved or pathname != saved.get('pathname') or not _matching(painted, saved):
            raise dash.exceptions.PreventUpdate
        display = live if _matching(live, saved) else saved
        kind = 'daily' if pathname == '/reports/daily' else 'user'
        panel = build_status_report(display, None if kind == 'daily' else user, (clicks or 0) % 2 == 0, kind)
        return (panel, dash.no_update) if kind == 'daily' else (dash.no_update, panel)

    return load_report_status, render_report_status, load_live_report_status, render_live_report_status
