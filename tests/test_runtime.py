"""Startup and report-read regressions for constrained hosting accounts."""
import json
import os
from pathlib import Path
import subprocess
import sys
from threading import Thread
from unittest.mock import MagicMock

import pytest

from slicing_dashboard.runtime import ReadExecutor


def test_package_sets_numeric_limits_before_importing_numpy():
    environment = dict(os.environ)
    names = ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS', 'NUMEXPR_NUM_THREADS')
    for name in names:
        environment.pop(name, None)
    environment['PYTHONPATH'] = str(Path(__file__).resolve().parents[1] / 'src')
    code = ('import os, sys, json; import slicing_dashboard; '
            f'print(json.dumps([dict((key, os.getenv(key)) for key in {names!r}), "numpy" in sys.modules]))')
    result = subprocess.run([sys.executable, '-c', code], env=environment,
                            capture_output=True, text=True, check=True)
    limits, numpy_loaded = json.loads(result.stdout)
    assert set(limits.values()) == {'1'}
    assert numpy_loaded is False


def test_configured_serial_reads_do_not_construct_a_thread_pool(monkeypatch):
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '1')
    pool = MagicMock()
    monkeypatch.setattr('slicing_dashboard.runtime.ThreadPoolExecutor', pool)
    with ReadExecutor(max_workers=10) as executor:
        assert list(executor.map(lambda number: number * 2, [1, 2, 3])) == [2, 4, 6]
    pool.assert_not_called()


def test_pending_review_remains_complete_without_worker_threads(monkeypatch):
    from slicing_dashboard.processing.pending_review import fetch_items
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '1')
    pool = MagicMock(side_effect=AssertionError('Host has no worker threads available'))
    monkeypatch.setattr('slicing_dashboard.runtime.ThreadPoolExecutor', pool)
    queues = {
        'slice_submitted': [{'id': 1, 'slicer': 'Person', 'slicer_id': 7, 'duration_seconds': 61}],
        'slice_pending_auditor_review': [{'id': 2, 'slicer': 'Person', 'slicer_id': 7, 'duration_seconds': 62}],
        'slice_pending_admin_review': [{'id': 3, 'slicer': 'Person', 'slicer_id': 7, 'duration_seconds': 63}],
    }
    monkeypatch.setattr('slicing_dashboard.processing.current_queue.fetch_queue',
                        lambda scraper, status: queues[status])
    rows = fetch_items(MagicMock(is_authenticated=True), '2026-10-14')
    assert len(rows) == 1
    assert [rows[0][f'{stage}_review_duration_seconds'] for stage in ('leader', 'auditor', 'admin')] == [61, 62, 63]
    pool.assert_not_called()


def test_daily_offset_inventory_remains_complete_without_worker_threads(monkeypatch):
    from slicing_dashboard.processing.daily_work_source import DailyWorkSource
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '1')
    pool = MagicMock(side_effect=AssertionError('Host has no worker threads available'))
    monkeypatch.setattr('slicing_dashboard.runtime.ThreadPoolExecutor', pool)
    source = DailyWorkSource(MagicMock())

    def page(number):
        return {'total': 3, 'items': [{'id': number, 'slice_submitted_at': '2026-10-14T12:00:00'}],
                'meta': {'total_capped': False, 'page': number, 'page_size': 1, 'has_more': number < 3}}

    source.request = lambda path, body: page(body['page'])
    tasks = source._parallel_inventory({'page_size': 1}, page(1))
    assert [task['id'] for task in tasks] == [1, 2, 3]
    pool.assert_not_called()


def test_rejected_thread_start_keeps_every_read_available(monkeypatch):
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '2')
    calls = []

    def denied_start(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(Thread, 'start', denied_start)
    with ReadExecutor(max_workers=8) as executor:
        results = list(executor.map(lambda value: calls.append(value) or value * 2, [1, 2, 3]))
    assert results == [2, 4, 6]
    assert calls == [1, 2, 3]


def test_failed_submission_left_in_queue_cannot_repeat_the_read(monkeypatch):
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '2')
    queued = []
    pool = MagicMock()

    def rejected_submit(run):
        queued.append(run)
        raise RuntimeError("can't start new thread")

    pool.submit.side_effect = rejected_submit
    monkeypatch.setattr('slicing_dashboard.runtime.ThreadPoolExecutor', lambda **kwargs: pool)
    read = MagicMock(return_value='retained history')
    with ReadExecutor(max_workers=3) as executor:
        result = executor.submit(read)
        queued[0]()  # Another existing worker later drains the failed submission.
        assert result.result() == 'retained history'
    read.assert_called_once_with()


def test_read_exception_propagates_in_serial_mode(monkeypatch):
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '1')
    read = MagicMock(side_effect=ValueError('Invalid saved evidence'))
    with ReadExecutor(max_workers=3) as executor:
        result = executor.submit(read)
        with pytest.raises(ValueError, match='Invalid saved evidence'):
            result.result()


def test_unrelated_executor_error_is_not_retried(monkeypatch):
    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '2')
    pool = MagicMock()
    pool.submit.side_effect = RuntimeError('cannot schedule new futures after shutdown')
    monkeypatch.setattr('slicing_dashboard.runtime.ThreadPoolExecutor', lambda **kwargs: pool)
    read = MagicMock()
    with ReadExecutor(max_workers=3) as executor:
        with pytest.raises(RuntimeError, match='after shutdown'):
            executor.submit(read)
    read.assert_not_called()


def test_saved_trend_still_loads_when_thread_creation_is_denied(monkeypatch):
    from slicing_dashboard.reporting.dashboard_trend import saved_trend

    monkeypatch.setenv('DASHBOARD_MAX_WORKERS', '2')
    monkeypatch.setattr('slicing_dashboard.reporting.dashboard_trend.today_iso', lambda: '2026-10-14')
    monkeypatch.setattr('slicing_dashboard.reporting.dashboard_trend.work_records',
                        lambda *args: {'2026-10-14': {'date': '2026-10-14', 'rows': [],
                                                      'metadata': {'available': True}}})

    def denied_start(self):
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(Thread, 'start', denied_start)
    manager = MagicMock(user_mapping={}, user_mapping_full={})
    manager._dashboard_trend_cache = {}
    manager.get_approval_data.return_value = {'rows': [], 'complete': True}
    manager.get_efficiency_history.return_value = []
    payload = saved_trend(manager, '2026-10-14', start_date='2026-10-14')
    assert payload['range_start'] == payload['range_end'] == '2026-10-14'
    assert payload['today']['metadata']['available'] is True
    assert payload['approvals'] == {'rows': [], 'complete': True}
