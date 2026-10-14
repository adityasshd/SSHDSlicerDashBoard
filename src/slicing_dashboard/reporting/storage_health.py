"""Read-only storage diagnostics without exposing credentials or report rows."""
import os
from pathlib import Path

from dotenv import dotenv_values
from pymongo import timeout

COLLECTIONS = ('user_mappings', 'settlement_periods', 'daily_work_reports',
               'workflow_records', 'dashboard_snapshot', 'batches_master')


def safe_error(error):
    result = {'error_class': type(error).__name__}
    code = getattr(error, 'code', None)
    if isinstance(code, int):
        result['error_code'] = code
    # Do not return exception messages: driver errors can contain connection data.
    return result


def storage_health(database, env_path=None):
    settings = database.settings
    mongo_configured = bool(settings.mongo_uri or
                            str(settings.database_url or '').startswith(('mongodb://', 'mongodb+srv://')))
    report = {'ok': False, 'mongo_configured': mongo_configured, 'connected': False,
              'database': getattr(database.mongo_db, 'name', None), 'collections': {}}
    if env_path is not None:
        path = Path(env_path)
        try:
            report['env_file_exists'] = path.is_file()
            file_values = {key.casefold(): value for key, value in dotenv_values(path).items()} if report['env_file_exists'] else {}
            environment = {key.casefold(): value for key, value in os.environ.items()}
            report['mongo_env_differs_from_file'] = bool('mongo_uri' in environment and
                file_values.get('mongo_uri') is not None and
                environment['mongo_uri'] != file_values['mongo_uri'])
        except OSError as error:
            report['env_file_error'] = safe_error(error)
    if not mongo_configured:
        report['state'] = 'mongo_not_configured'
        return report
    if database.mongo_client is None or database.mongo_db is None:
        report['state'] = 'mongo_initialization_failed'
        return report
    phase = 'connection'
    try:
        # This check reuses the app's client and never creates indexes or records.
        with timeout(8):
            database.mongo_client.admin.command('ping')
            report['connected'] = True
            phase = 'reads'
            for name in COLLECTIONS:
                try:
                    count = database.mongo_db[name].estimated_document_count(maxTimeMS=1500)
                    report['collections'][name] = {'documents': count}
                except Exception as error:
                    report['collections'][name] = safe_error(error)
            daily = database.mongo_db['daily_work_reports']
            first = daily.find_one({'date': {'$exists': True}}, {'_id': 0, 'date': 1}, sort=[('date', 1)], max_time_ms=1500)
            last = daily.find_one({'date': {'$exists': True}}, {'_id': 0, 'date': 1}, sort=[('date', -1)], max_time_ms=1500)
            report['daily_date_range'] = {'first': first.get('date') if first else None,
                                          'last': last.get('date') if last else None}
        read_failed = any('error_class' in item for item in report['collections'].values())
        missing = [name for name in ('user_mappings', 'settlement_periods', 'daily_work_reports')
                   if report['collections'].get(name, {}).get('documents') == 0]
        report['missing_collections'] = missing
        report['state'] = 'read_failed' if read_failed else 'missing_saved_data' if missing else 'ready'
        report['ok'] = report['state'] == 'ready'
    except Exception as error:
        report.update(safe_error(error))
        report['state'] = 'connection_failed' if phase == 'connection' else 'read_failed'
    return report
