"""Retained-storage diagnostics remain read-only, protected and secret-free."""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

from flask import Flask
from pymongo.errors import OperationFailure, ServerSelectionTimeoutError
import pytest

from slicing_dashboard.reporting.data_health import register_data_health_routes
from slicing_dashboard.reporting.storage_health import COLLECTIONS, storage_health


def database():
    collections = {name: MagicMock() for name in COLLECTIONS}
    for collection in collections.values():
        collection.estimated_document_count.return_value = 10
    collections['daily_work_reports'].find_one.side_effect = [
        {'date': '2026-10-05'}, {'date': '2026-10-13'}]
    saved = MagicMock()
    saved.name = 'slicing_dashboard'
    saved.__getitem__.side_effect = collections.__getitem__
    return SimpleNamespace(settings=SimpleNamespace(mongo_uri='mongodb://private', database_url=None),
                           mongo_client=MagicMock(), mongo_db=saved), collections


def test_ready_counts_and_dates_do_not_mutate_the_saved_store():
    db, collections = database()
    result = storage_health(db)
    assert result['ok'] and result['connected']
    assert result['database'] == 'slicing_dashboard'
    assert result['daily_date_range'] == {'first': '2026-10-05', 'last': '2026-10-13'}
    assert set(result['collections']) == set(COLLECTIONS)
    assert 'private' not in json.dumps(result)
    db.mongo_client.admin.command.assert_called_once_with('ping')
    for collection in collections.values():
        assert all(call[0] in ('estimated_document_count', 'find_one') for call in collection.mock_calls)


def test_missing_configuration_is_distinct_from_failed_connection():
    db, _ = database()
    db.settings.mongo_uri = None
    assert storage_health(db)['state'] == 'mongo_not_configured'
    db.mongo_client.admin.command.assert_not_called()
    db.settings.mongo_uri = 'mongodb://private'
    db.mongo_client.admin.command.side_effect = ServerSelectionTimeoutError('secret connection string')
    result = storage_health(db)
    assert result['state'] == 'connection_failed' and not result['connected']
    assert result['error_class'] == 'ServerSelectionTimeoutError'
    assert 'secret' not in json.dumps(result)


def test_empty_configuration_collections_are_reported():
    db, collections = database()
    collections['settlement_periods'].estimated_document_count.return_value = 0
    result = storage_health(db)
    assert result['connected'] and not result['ok']
    assert result['state'] == 'missing_saved_data'
    assert result['missing_collections'] == ['settlement_periods']


def test_read_permissions_failure_is_distinct_from_connection_failure():
    db, collections = database()
    collections['user_mappings'].estimated_document_count.side_effect = OperationFailure('secret URI', code=13)
    result = storage_health(db)
    assert result['connected'] and result['state'] == 'read_failed'
    assert result['collections']['user_mappings'] == {'error_class': 'OperationFailure', 'error_code': 13}
    assert 'secret' not in json.dumps(result)


def test_environment_override_detected_without_returning_either_uri(tmp_path, monkeypatch):
    path = tmp_path / '.env'
    path.write_text('MONGO_URI=mongodb://file-private\n')
    monkeypatch.setenv('MONGO_URI', 'mongodb://environment-private')
    db, _ = database()
    result = storage_health(db, path)
    assert result['env_file_exists'] and result['mongo_env_differs_from_file']
    assert 'private' not in json.dumps(result)


@pytest.mark.parametrize('secret, header', [('', ''), ('expected', ''), ('expected', 'Bearer incorrect')])
def test_endpoint_fails_closed_without_diagnostic_reads(monkeypatch, secret, header):
    monkeypatch.setenv('CRON_SECRET', secret)
    probe = MagicMock()
    monkeypatch.setattr('slicing_dashboard.reporting.storage_health.storage_health', probe)
    server = Flask(__name__)
    register_data_health_routes(server, SimpleNamespace(db=None))
    result = server.test_client().get('/api/storage-health', headers={'Authorization': header})
    assert result.status_code == 401
    assert result.headers['Cache-Control'] == 'no-store'
    probe.assert_not_called()


@pytest.mark.parametrize('ready, status', [(True, 200), (False, 503)])
def test_authorized_endpoint_avoids_capture_service_and_preserves_status(monkeypatch, ready, status):
    monkeypatch.setenv('CRON_SECRET', 'expected')
    monkeypatch.setattr('slicing_dashboard.reporting.storage_health.storage_health',
                        MagicMock(return_value={'ok': ready, 'state': 'ready' if ready else 'connection_failed'}))
    capture = MagicMock(side_effect=AssertionError('Must not initialize workflow store or indexes'))
    monkeypatch.setattr('slicing_dashboard.reporting.data_health.DataHealth', capture)
    server = Flask(__name__)
    register_data_health_routes(server, SimpleNamespace(db=None))
    result = server.test_client().get('/api/storage-health', headers={'Authorization': 'Bearer expected'})
    assert result.status_code == status
    assert result.json['ok'] is ready
    assert result.headers['Cache-Control'] == 'no-store'
    capture.assert_not_called()
