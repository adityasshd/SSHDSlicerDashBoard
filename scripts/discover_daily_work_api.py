"""Read-only API discovery. Store response bodies locally, never session cookies."""
import argparse
import json
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from pathlib import Path

from slicing_dashboard.scraper.http_scraper import HTTPScraper


def shape(value, depth=0):
    if isinstance(value, dict):
        return {key: shape(item, depth + 1) for key, item in value.items()} if depth < 3 else list(value)
    if isinstance(value, list):
        return {'count': len(value), 'first_shape': shape(value[0], depth + 1) if value else None}
    return type(value).__name__


def save_schema(output, schema):
    (output / 'openapi.json').write_text(json.dumps(schema, indent=2, ensure_ascii=False), encoding='utf-8')
    operations = []
    lines = ['# Live FastAPI endpoint inventory', '',
             'Fetched at ' + datetime.now(timezone.utc).isoformat(), '',
             '| Method | Path | Summary |', '| --- | --- | --- |']
    for path, methods in sorted(schema['paths'].items()):
        for method, operation in methods.items():
            if method not in {'get', 'post', 'put', 'patch', 'delete', 'head', 'options', 'trace'}:
                continue
            operations.append({'method': method.upper(), 'path': path, **operation})
            summary = operation.get('summary', '').replace('|', '/')
            lines.append(f'| {method.upper()} | `{path}` | {summary} |')
    (output / 'endpoints.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    (output / 'endpoints.json').write_text(json.dumps(operations, indent=2, ensure_ascii=False), encoding='utf-8')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--date', required=True)
    parser.add_argument('--details', action='store_true')
    args = parser.parse_args()
    date.fromisoformat(args.date)
    output = Path('data/reports') / f'api-discovery-{args.date}'
    output.mkdir(parents=True, exist_ok=True)
    scraper = HTTPScraper()
    if not scraper.login():
        raise RuntimeError('Configured API login failed')
    day = {'start_date': args.date, 'end_date': args.date}
    scoped = {**day, 'role': 2, 'leader_id': scraper.settings.efficiency_leader_id, 'page': 1, 'page_size': 200}
    queries = [
        ('me', 'GET', '/api/auth/me', {}),
        ('groups', 'GET', '/api/user-groups', {}),
        ('batches', 'GET', '/api/dashboard/batches', {**day, 'workflow_type': 'slice'}),
        ('slice_tasks', 'GET', '/api/slice/tasks', {'page_size': 5}),
        ('overview_denial', 'POST', '/api/tasks/overview', {'page_size': 1}),
        ('efficiency', 'POST', '/api/dashboard/annotator-efficiency', scoped),
        ('enhanced', 'POST', '/api/dashboard/user-efficiency-enhanced', scoped),
        ('activity', 'POST', '/api/dashboard/user-activity', {**day, 'role': 2}),
        ('user_data', 'POST', '/api/dashboard/user-data', day),
        ('statistics', 'POST', '/api/dashboard/statistics', day),
        ('slice_dashboard', 'GET', '/api/dashboard/slice', {**day, 'workflow_type': 'slice'}),
        ('reviewed_tasks', 'GET', '/api/review/reviewed-tasks', {**day, 'workflow_type': 'slice', 'page_size': 5}),
    ]
    if args.details:
        scope = json.loads((output / 'batches.json').read_text(encoding='utf-8'))['scope']
        tasks = json.loads((output / 'slice_tasks.json').read_text(encoding='utf-8'))['data']
        groups = json.loads((output / 'groups.json').read_text(encoding='utf-8'))['items']
        matches = [group for group in groups if group.get('root_leader_id') == scope['actor_id']]
        if len(matches) != 1:
            raise ValueError('Cannot identify one authorized organization for this Leader')
        organization_id = matches[0]['id']
        uid = tasks[0]['slicer_id']
        filters = {**day, 'workflow_type': 'slice', 'group_id': scope['group_id'], 'include_benchmark': False}
        queries = [
            ('drilldown_task_list', 'POST', '/api/dashboard/drilldown', {'metric_key': 'task_list', 'filters': filters, 'limit': 3}),
            ('drilldown_batches', 'POST', '/api/dashboard/drilldown', {'metric_key': 'assignment_batches', 'filters': filters, 'limit': 3}),
            ('efficiency_v2_group', 'POST', '/api/v2/dashboard/annotator-efficiency', {**day, 'role': 2, 'group_id': organization_id, 'page_size': 200}),
            ('enhanced_v2_group', 'POST', '/api/v2/dashboard/user-efficiency-enhanced', {**day, 'role': 2, 'group_id': organization_id, 'page_size': 200}),
            ('activity_member', 'POST', '/api/dashboard/user-activity', {**day, 'role': 2, 'user_id': uid}),
        ]
    evidence = []

    def fetch(query):
        name, method, path, payload = query
        entry = {'name': name, 'method': method, 'path': path, 'request': payload,
                 'captured_at': datetime.now(timezone.utc).isoformat()}
        try:
            response = scraper._client.request(method, scraper._base_url + path,
                **({'json': payload} if method == 'POST' else {'params': payload}), timeout=20)
            entry['status'] = response.status_code
            try:
                body = response.json()
            except ValueError:
                body = {'non_json_response': True}
            if name == 'me' and isinstance(body, dict):
                body = {key: body.get(key) for key in ('id', 'role', 'capabilities')}
            (output / f'{name}.json').write_text(json.dumps(body, indent=2, ensure_ascii=False), encoding='utf-8')
            entry['shape'] = shape(body)
        except Exception as error:
            entry['error'] = type(error).__name__
        print(json.dumps(entry, ensure_ascii=True), flush=True)
        return entry

    try:
        if not args.details:
            response = scraper._client.get(scraper._base_url + '/openapi.json', timeout=20)
            response.raise_for_status()
            save_schema(output, response.json())
        with ThreadPoolExecutor(max_workers=3) as pool:
            evidence.extend(pool.map(fetch, queries))
    finally:
        scraper.close()
    (output / ('detail-summary.json' if args.details else 'probe-summary.json')).write_text(json.dumps(evidence, indent=2), encoding='utf-8')


if __name__ == '__main__':
    sys.stdout.reconfigure(errors='backslashreplace')
    main()
