"""November rework history: event dates, repeated returns, latest status and UI."""
from types import SimpleNamespace

import pytest

from slicing_dashboard.pages.monthly_returns import render_monthly_return_history
from slicing_dashboard.plots.monthly_return_chart import build_monthly_returns_chart
from slicing_dashboard.reporting.monthly_returns import monthly_return_history


def batch(batch_id, user, status, day='2026-11-04'):
    return {
        'batch_id': batch_id, 'canonical_user': user,
        'batch_date': day, 'status': status,
    }


def returned(batch_id, stamp, viewer=10, source=None):
    return {
        'batch_id': batch_id, 'returned_at': stamp, 'user_id': viewer,
        'event_id': source or f'{viewer}_{batch_id}_{stamp}',
    }


def fixture():
    batches = [
        batch('completed', 'Komal', 'batch_completed'),
        batch('pending', 'Priya', 'batch_pending_auditor_review'),
        batch('other', 'Rajni', 'batch_member_assigned'),
        batch('untouched', 'Komal', 'batch_completed'),
    ]
    events = [
        returned('completed', '2026-10-30T14:00:00Z'),
        returned('completed', '2026-11-04T08:00:00+05:30'),
        returned('completed', '2026-11-04T02:30:00Z', viewer=20),  # same observed event
        returned('completed', '2026-11-05T08:00:00+05:30'),
        returned('pending', '2026-11-07T08:00:00+05:30'),
        returned('other', '2026-11-05T08:00:00+05:30'),
        returned('missing-ledger', '2026-11-06T08:00:00+05:30'),
        returned('completed', '2026-11-17T18:40:00Z'),  # November 18, IST; outside range
        {'batch_id': 'bad', 'returned_at': 'not a date'},
    ]
    return batches, events


def build(selected=None):
    batches, events = fixture()
    return monthly_return_history(
        batches, events, '2026-11-01', '2026-11-17',
        resolve=lambda row: row['canonical_user'],
        selected_users=selected,
    )


def test_month_is_event_dated_with_repeat_and_orphan_events_preserved():
    report = build()
    result = report['summary']
    assert result['observed_returns'] == 5
    assert result['affected_batches'] == 4
    assert result['repeat_return_batches_this_month'] == 1
    assert result['completed_state_returns'] == 2
    assert result['pending_review_state_returns'] == 1
    assert result['other_or_unlinked_returns'] == 2
    assert result['unlinked_batches'] == 1
    assert result['duplicate_documents_ignored'] == 1
    assert result['unusable_documents_ignored'] == 1
    assert report['coverage'] == 'observed_return_events_only'
    assert report['complete_lifetime_history'] is False
    assert report['status_basis'] == 'latest_batch_status'
    assert len(report['daily']) == 17
    nov4 = next(row for row in report['daily'] if row['date'] == '2026-11-04')
    assert nov4['Completed'] == 1 and nov4['total'] == 1
    completed = next(row for row in report['batches'] if row['Batch'] == 'completed')
    assert completed['Returns This Month'] == 2
    assert completed['Total Observed Returns Through End'] == 3
    assert completed['Latest Status'] == 'Completed'
    assert completed['First Return This Month'].startswith('2026-11-04')
    assert sum(row['total'] for row in report['daily']) == result['observed_returns']


def test_monthly_history_user_filter_does_not_reassign_orphan_events():
    report = build(['Komal'])
    assert report['summary']['observed_returns'] == 2
    assert report['summary']['affected_batches'] == 1
    assert report['summary']['other_or_unlinked_returns'] == 0
    assert not build([])['summary']['observed_returns']


@pytest.mark.parametrize('dark', [True, False])
def test_monthly_chart_preserves_exact_daily_counts_and_coverage(dark):
    report = build()
    figure = build_monthly_returns_chart(report, dark)
    assert len(figure.data) == 3
    assert figure.layout.meta['total_observed'] == 5
    assert figure.layout.meta['metric'] == 'observed_return_event_count'
    assert figure.layout.meta['coverage'] == 'observed_return_events_only'
    assert figure.layout.meta['completed_state_returns'] == 2
    assert figure.layout.meta['pending_review_state_returns'] == 1
    assert figure.layout.barmode == 'stack'
    assert sum(sum(int(v) for v in trace.y) for trace in figure.data) == 5
    assert 'latest batch state' in figure.layout.title.subtitle.text
    figure.to_json()


def test_workflow_page_uses_saved_caches_and_leaves_them_unchanged():
    batches, events = fixture()
    manager = SimpleNamespace(
        _batches_master_cache={item['batch_id']: item for item in batches},
        _batch_returns_cache=events,
        _batch_canonical_name=lambda row: row['canonical_user'],
    )
    before = list(manager._batch_returns_cache)
    chart, summary, rows = render_monthly_return_history(
        manager, None, 0, today='2026-11-17',
    )
    assert chart.layout.meta['total_observed'] == 5
    assert len(rows) == 4
    assert '5 observed returns' in str(summary)
    assert manager._batch_returns_cache == before
    empty = SimpleNamespace(_batches_master_cache={}, _batch_returns_cache=[],
                            _batch_canonical_name=lambda row: row.get('canonical_user'))
    figure, message, rows = render_monthly_return_history(
        empty, None, 0, today='2026-11-17',
    )
    assert not figure.data
    assert 'Cannot infer zero returns' in str(figure.layout.annotations[0].text)
    assert not rows


def _walk(node):
    if isinstance(node, (list, tuple)):
        for item in node:
            yield from _walk(item)
    elif hasattr(node, 'children'):
        yield node
        yield from _walk(node.children)


def test_intensity_ui_has_exactly_two_status_modes_and_default_completed():
    from slicing_dashboard.pages.components import chart_graph
    control = chart_graph(id='rework-ratio-chart')
    radios = [node for node in _walk(control)
              if getattr(node, 'id', None) == 'rework-completion-state']
    assert len(radios) == 1
    assert [(entry['label'], entry['value']) for entry in radios[0].options] == [
        ('Completed', 'Completed'),
        ('Pending Review', 'Pending approvals'),
    ]
    assert radios[0].value == 'Completed'


def test_no_bad_month_scope_or_ambiguous_batch_identity():
    batches, events = fixture()
    with pytest.raises(ValueError, match='at most 32 days'):
        monthly_return_history(batches, events, '2026-10-01', '2026-11-17')
    with pytest.raises(ValueError, match='Duplicate batch identity'):
        monthly_return_history([batches[0], batches[0]], events,
                               '2026-11-01', '2026-11-17')
