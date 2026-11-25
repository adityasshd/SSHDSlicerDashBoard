"""Capture forward-only submissions once, or keep polling without web traffic."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
from datetime import datetime, timezone
import io
import json
from pathlib import Path
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from slicing_dashboard.config import get_settings, DATA_DIR
from slicing_dashboard.db import DatabaseManager
from slicing_dashboard.scraper.http_scraper import HTTPScraper
from slicing_dashboard.reporting.submission_tracking import capture_submissions


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--watch', action='store_true')
    parser.add_argument('--interval', type=int, default=60)
    args = parser.parse_args()
    if args.interval < 30:
        parser.error('Polling interval must be at least 30 seconds')
    settings = get_settings()
    manager = SimpleNamespace(settings=settings, db=DatabaseManager(), scraper=HTTPScraper(settings))
    status = DATA_DIR / 'reports/submission-tracking-status.json'
    status.parent.mkdir(parents=True, exist_ok=True)
    try:
        while True:
            try:
                with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                    result = {'ok': True, **capture_submissions(manager)}
            except Exception as error:
                result = {'ok': False, 'error': type(error).__name__,
                          'attempted_at': datetime.now(timezone.utc).isoformat()}
            temp = status.with_suffix('.tmp')
            temp.write_text(json.dumps(result, indent=2), encoding='utf8')
            temp.replace(status)
            print(json.dumps(result), flush=True)
            if not args.watch:
                return 0 if result['ok'] else 1
            time.sleep(args.interval)
    finally:
        manager.scraper.close()
        if manager.db.mongo_client is not None:
            manager.db.mongo_client.close()


if __name__ == '__main__':
    raise SystemExit(main())
