"""Effective work uses only verified completed duration and current review inventory."""
import pandas as pd
import pytest

from slicing_dashboard.pages.dashboard_panels import render_panel
from slicing_dashboard.plots.individual_chart import build_individual_chart
from slicing_dashboard.plots.pending_chart import build_pending_chart
from slicing_dashboard.reporting.dashboard_panels import frame_payload


def test_completed_and_pending_are_combined_once_per_person():
    complete = pd.DataFrame([
        {'User': 'Priya', 'Completed Duration': 7200},
        {'User': 'Riya', 'Completed Duration': 3600},
    ])
    pending = pd.DataFrame([
        {'User': 'Priya', 'Stage': 'Pending Leader', 'Duration': 1800, 'Count': 1},
        {'User': 'Priya', 'Stage': 'Pending Admin', 'Duration': 900, 'Count': 1},
        {'User': 'Akash', 'Stage': 'Pending Auditor', 'Duration': 3600, 'Count': 1},
    ])
    chart = build_individual_chart(complete, '2026-11-01', '2026-11-20', True,
                                   pending_df=pending, pending_available=True)
    meta = chart.layout.meta
    assert meta['completed_seconds'] == pytest.approx(10800)
    assert meta['pending_seconds'] == pytest.approx(6300)
    assert meta['effective_seconds'] == pytest.approx(17100)
    assert meta['completed_scope'] == 'selected_period'
    assert meta['pending_scope'] == 'current_inventory'
    assert chart.layout.xaxis.categoryarray[0] == 'Priya'
    by_name = {trace.name: trace for trace in chart.data}
    assert by_name['Priya'].y[0] == pytest.approx(2)
    assert by_name['Priya effective work'].y[0] == pytest.approx(2.75)
    assert by_name['Priya effective work'].marker.symbol == 'diamond'
    assert by_name['Priya effective work'].marker.color == by_name['Priya'].marker.color
    dashed = next(shape for shape in chart.layout.shapes
                  if shape.x0 == 'Priya' and shape.line.dash == 'dot')
    assert dashed.line.color == by_name['Priya'].marker.color
    assert by_name['Akash effective work'].marker.color == by_name['Akash'].marker.color
    assert by_name['Priya'].textposition == 'middle left'
    assert by_name['Priya effective work'].textposition == 'middle right'
    assert chart.layout.xaxis.range == pytest.approx([-.85, len(chart.layout.xaxis.categoryarray) - .15])
    assert by_name['Akash'].y[0] == 0
    assert by_name['Akash effective work'].y[0] == pytest.approx(1)
    assert 'Riya effective work' not in by_name  # zero pending adds no duplicate marker
    chart.to_json()


def test_pending_unavailable_never_becomes_fabricated_zero():
    completed = pd.DataFrame([{'User': 'Riya', 'Completed Duration': 3600}])
    chart = build_individual_chart(completed, '2026-11-01', '2026-11-20', False)
    assert chart.layout.meta['pending_available'] is False
    assert chart.layout.meta['pending_seconds'] is None
    assert chart.layout.meta['effective_seconds'] is None
    assert len(chart.data) == 1
    assert chart.data[0].textposition == 'middle right'
    assert chart.layout.title.subtitle is None
    assert chart.layout.title.text == 'Completed duration and effective work'


def test_pending_heatmap_row_column_and_grand_totals_are_not_double_counted():
    pending = pd.DataFrame([
        {'User': 'Riya', 'Stage': 'Pending Leader', 'Duration': 3600, 'Count': 2},
        {'User': 'Riya', 'Stage': 'Pending Admin', 'Duration': 1800, 'Count': 1},
        {'User': 'Priya', 'Stage': 'Pending Auditor', 'Duration': 7200, 'Count': 3},
    ])
    fig = build_pending_chart(pending, True)
    trace = fig.data[0]
    assert list(trace.x) == ['Leader', 'Auditor', 'Admin', '<b>Total</b>']
    assert list(trace.y) == ['Priya', 'Riya', '<b>Total</b>']
    assert fig.layout.meta['row_totals'] == pytest.approx([2, 1.5])
    assert fig.layout.meta['grand_total'] == pytest.approx(3.5)
    assert fig.layout.meta['column_totals'] == pytest.approx([1, 2, .5, 3.5])
    assert [row[-1] for row in trace.z] == [-1, -1, -1]
    assert [row[-1] for row in trace.customdata][-1][-1] == pytest.approx(3.5)
    assert fig.layout.meta['total_column'] is True
    fig.to_json()


def test_effective_lollipop_only_uses_same_period_current_pending_packet():
    request = {'id': 'same', 'start': '2026-11-01', 'end': '2026-11-20'}
    completed_packet = {'available': True, 'request_id': 'same', 'captured_at': 'now',
                        'data': frame_payload(pd.DataFrame([
                            {'User': 'Riya', 'Completed Duration': 3600}]), 'completion')}
    pending_packet = {'available': True, 'request_id': 'pending', 'captured_at': 'now',
                      'data': frame_payload(pd.DataFrame([
                          {'User': 'Riya', 'Stage': 'Pending Leader', 'Duration': 1800,
                           'Count': 1}]), 'pending')}
    pending_request = {**request, 'id': 'pending'}
    chart, _ = render_panel('completion', request, completed_packet, None,
                            ['Riya'], 0, ['Riya'],
                            pending_request=pending_request, pending_saved=pending_packet)
    assert chart.layout.meta['effective_seconds'] == pytest.approx(5400)
    stale_request = {**pending_request, 'end': '2026-11-19'}
    stale, _ = render_panel('completion', request, completed_packet, None,
                            ['Riya'], 0, ['Riya'],
                            pending_request=stale_request, pending_saved=pending_packet)
    assert stale.layout.meta['effective_seconds'] is None
    closed, _ = render_panel('completion', {**request, 'frozen': True},
                             completed_packet, None, ['Riya'], 0, ['Riya'],
                             pending_request=pending_request, pending_saved=pending_packet)
    assert closed.layout.meta['effective_seconds'] is None


@pytest.mark.parametrize('dark', [True, False])
def test_zero_settlement_contributors_are_hidden_but_pending_only_people_remain(dark):
    completed = pd.DataFrame([
        {'User': 'No work', 'Completed Duration': 0},
        {'User': 'Completed person', 'Completed Duration': 3600},
        {'User': 'Pending-only person', 'Completed Duration': 0},
        {'User': 'Both zero', 'Completed Duration': 0},
    ])
    pending = pd.DataFrame([
        {'User': 'Pending-only person', 'Stage': 'Pending Admin',
         'Duration': 7200, 'Count': 2},
        {'User': 'Both zero', 'Stage': 'Pending Leader',
         'Duration': 0, 'Count': 1},
        {'User': 'Queue-only zero', 'Stage': 'Pending Auditor',
         'Duration': 0, 'Count': 1},
    ])
    chart = build_individual_chart(completed, '2026-11-01', '2026-11-20', dark,
                                   pending_df=pending, pending_available=True)
    users = list(chart.layout.xaxis.categoryarray)
    assert users == ['Pending-only person', 'Completed person']
    assert chart.layout.meta['completed_seconds'] == pytest.approx(3600)
    assert chart.layout.meta['pending_seconds'] == pytest.approx(7200)
    assert chart.layout.meta['effective_seconds'] == pytest.approx(10800)
    assert 'Pending-only person effective work' in [t.name.replace('<br>', ' ') for t in chart.data]
    assert all(t.textposition in ('middle left', 'middle right') for t in chart.data)
    assert all(not t.name.startswith(('No work', 'Both zero', 'Queue-only zero'))
               for t in chart.data)
    chart.to_json()


def test_settlement_with_only_zero_duration_is_an_explicit_empty_chart():
    complete = pd.DataFrame([{'User': 'No work', 'Completed Duration': 0}])
    chart = build_individual_chart(complete, '2026-11-01', '2026-11-20', True)
    assert len(chart.data) == 0
    assert 'No completed or pending-review' in chart.layout.annotations[0].text
