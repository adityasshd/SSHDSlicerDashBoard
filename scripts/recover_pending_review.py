"""Save current task-level review evidence without changing upstream/shared data."""
import argparse
import csv
from datetime import datetime, timezone
import json
from pathlib import Path
from zoneinfo import ZoneInfo

from slicing_dashboard.processing.pending_review import current_review_end, fetch_items
from slicing_dashboard.runtime import viewer_mode
from slicing_dashboard.scraper.http_scraper import HTTPScraper


FIELDS = ('id', 'slicer_id', 'slicer', 'status', 'queue_duration_seconds',
          'duration_seconds', 'duration_source', 'duration_start', 'duration_end')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, help='Directory for the JSON and CSV capture')
    args = parser.parse_args()
    if viewer_mode():
        raise SystemExit('Run recovery on the collector/local dashboard, outside viewer mode.')
    began = datetime.now(timezone.utc).isoformat()
    output = args.output or Path('data/reports') / (
        'pending-review-recovery-' + datetime.now(ZoneInfo('Asia/Kolkata')).strftime('%Y-%m-%d-%H%M%S'))
    records = []
    scraper = HTTPScraper()
    try:
        accounts = fetch_items(scraper, current_review_end(), task_records=records)
    finally:
        scraper.close()
    records = [{field: row.get(field) for field in FIELDS} for row in records]
    stages = {}
    for row in records:
        stage = stages.setdefault(row['status'], {'tasks': 0, 'seconds': 0.,
                                                 'recovered_tasks': 0, 'recovered_seconds': 0.})
        stage['tasks'] += 1
        stage['seconds'] += row['duration_seconds']
        if row['duration_source'] != '/api/slice/tasks':
            stage['recovered_tasks'] += 1
            stage['recovered_seconds'] += row['duration_seconds']
    capture = {'started_at': began, 'captured_at': datetime.now(timezone.utc).isoformat(),
               'scope': 'Current slicing review queues; exact task IDs, owner and stage verified',
               'stages': stages, 'accounts': accounts, 'tasks': records}
    output.mkdir(parents=True, exist_ok=True)
    (output / 'recovered-review-tasks.json').write_text(json.dumps(capture, indent=2), encoding='utf-8')
    with (output / 'recovered-review-tasks.csv').open('w', newline='', encoding='utf-8-sig') as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(records)
    print(json.dumps({'captured_at': capture['captured_at'], 'stages': stages,
                      'json': str(output / 'recovered-review-tasks.json'),
                      'csv': str(output / 'recovered-review-tasks.csv')}), flush=True)


if __name__ == '__main__':
    main()
