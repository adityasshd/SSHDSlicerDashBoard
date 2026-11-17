"""Saved-first month-to-date rework history for the Workflow page.

No upstream network reads and no database writes in rendering callbacks.
"""
from datetime import date

import dash
from dash import Input, Output, html

from slicing_dashboard.management.periods import today_iso
from slicing_dashboard.plots.guardrails import state_figure
from slicing_dashboard.plots.monthly_return_chart import build_monthly_returns_chart
from slicing_dashboard.reporting.monthly_returns import monthly_return_history


TABLE_FIELDS = (
    'Batch', 'Member', 'Latest Status', 'Returns This Month',
    'Total Observed Returns Through End', 'First Return This Month',
    'Latest Return This Month', 'Ledger Linked',
)


def render_monthly_return_history(manager, selected=None, theme=0, today=None):
    """Render month activity from the very same persisted ledger+return cache."""
    dark = (theme or 0) % 2 == 0
    end = today or today_iso()
    start = date.fromisoformat(end).replace(day=1).isoformat()
    batches = getattr(manager, '_batches_master_cache', {}) or {}
    returns = getattr(manager, '_batch_returns_cache', []) or []
    if not returns:
        return (
            state_figure('No saved return history available. Cannot infer zero returns.', dark, 355),
            html.P('Return-event capture unavailable or empty. A zero-count history is not verified.',
                   className='text-secondary small'),
            [],
        )
    report = monthly_return_history(
        batches.values() if isinstance(batches, dict) else batches,
        returns, start, end, resolve=manager._batch_canonical_name,
        selected_users=selected,
    )
    figure = build_monthly_returns_chart(report, dark)
    summary = report['summary']
    date_label = date.fromisoformat(end).strftime('%d %b %Y')
    message = html.Div([
        html.Strong(f"{summary['observed_returns']} observed returns"),
        html.Span(f" · {summary['affected_batches']} affected batches"
                  f" · {summary['repeat_return_batches_this_month']} returned more than once"
                  f" · {summary['completed_state_returns']} currently completed"
                  f" · {summary['pending_review_state_returns']} currently pending review"
                  f" · {summary['other_or_unlinked_returns']} other/unlinked"),
        html.Div(
            f"Month to {date_label} · saved capture only · observed history may be incomplete"
            " · statuses are latest saved states, not state on return date.",
            className='text-secondary small',
        ),
    ])
    return figure, message, [
        {key: row.get(key) for key in TABLE_FIELDS} for row in report['batches']
    ]


def register_monthly_returns(app, manager, roster=()):
    @app.callback(
        Output('workflow-monthly-return-chart', 'figure'),
        Output('workflow-monthly-return-summary', 'children'),
        Output('workflow-monthly-return-table', 'data'),
        Input('report-location', 'pathname'),
        Input('selected-users-store', 'data'),
        Input('theme-toggle', 'n_clicks'),
        Input('refresh-btn', 'n_clicks'),
    )
    def paint_monthly_returns(pathname, users, theme, _refresh):
        if pathname != '/workflow':
            raise dash.exceptions.PreventUpdate
        # The global default selects the entire roster; treat it as no
        # user filter so orphan return events remain visible in the audit.
        selected = (None if users is None or (roster and set(users) >= set(roster))
                    else users)
        try:
            return render_monthly_return_history(manager, selected, theme)
        except (ValueError, TypeError, KeyError):
            dark = (theme or 0) % 2 == 0
            return (state_figure('Saved return history could not be reconciled.', dark, 355),
                    html.P('Saved return-history evidence is inconsistent; no count inferred.',
                           className='text-secondary small'), [])
