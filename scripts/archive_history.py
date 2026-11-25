"""Archive all retained evidence, then optionally prune superseded old versions.

The export is a mongorestore-compatible directory of BSON gzip files plus index
metadata. Every BSON document is decoded and re-encoded before deletion is
allowed. Latest event/batch versions and every source referenced by a current
event survive. Core reports, events, returns, mappings and settings are retained.
"""
import argparse
from collections import defaultdict
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import struct
import sys

from bson import BSON, json_util
from pymongo import DeleteOne

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from slicing_dashboard.db import DatabaseManager

VERSION_KINDS = {'observation', 'projection-history', 'batch-observation'}


def bson_documents(path):
    with gzip.open(path, 'rb') as stream:
        while prefix := stream.read(4):
            if len(prefix) != 4:
                raise ValueError('Truncated BSON size')
            length = struct.unpack('<i', prefix)[0]
            if length < 5 or length > 16 * 1024 * 1024:
                raise ValueError('Invalid BSON size')
            raw = prefix + stream.read(length - 4)
            if len(raw) != length:
                raise ValueError('Truncated BSON document')
            doc = BSON(raw).decode()
            if BSON.encode(doc) != raw:
                raise ValueError('BSON round-trip verification failed')
            yield doc, raw


def version_identity(doc):
    kind = doc.get('kind')
    if kind not in VERSION_KINDS:
        return None
    payload = json.loads(doc['payload'])
    if kind == 'observation':
        identity = payload.get('event_key')
    elif kind == 'projection-history':
        identity = payload.get('event_id')
    else:
        batch = payload.get('batch', {})
        identity = (payload.get('instance'), batch.get('batch_id'))
        if not all(identity):
            return None
    if not identity:
        return None
    stamp = payload.get('observed_at') or payload.get('projection', {}).get('observed_at')
    if not stamp:
        return None
    return (kind, str(identity)), stamp


def export_database(db, destination):
    destination.mkdir(parents=True, exist_ok=False)
    archive = destination / db.name
    archive.mkdir()
    manifest = {'schema_version': 1, 'database': db.name,
                'captured_at': datetime.now(timezone.utc).isoformat(),
                'atomic_point_in_time': False, 'collections': {},
                'coverage': 'All stored documents observed during export; not final settlement certification'}
    for name in sorted(db.list_collection_names()):
        if name.startswith('system.'):
            continue
        path = archive / (name + '.bson.gz')
        count, digest = 0, hashlib.sha256()
        with gzip.open(path, 'wb', compresslevel=6) as stream:
            for doc in db[name].find().batch_size(500):
                raw = BSON.encode(doc)
                stream.write(raw)
                digest.update(raw)
                count += 1
        metadata = {'options': db[name].options(),
                    'indexes': [{k: v for k, v in index.items() if k != 'ns'}
                                for index in db[name].list_indexes()],
                    'collectionName': name, 'type': 'collection'}
        (archive / (name + '.metadata.json')).write_text(json_util.dumps(metadata), encoding='utf8')
        verify_count, verify_digest = 0, hashlib.sha256()
        for _, raw in bson_documents(path):
            verify_count += 1
            verify_digest.update(raw)
        if (verify_count, verify_digest.hexdigest()) != (count, digest.hexdigest()):
            raise ValueError('Archive verification failed: ' + name)
        manifest['collections'][name] = {'documents': count, 'bson_sha256': digest.hexdigest(),
                                        'compressed_bytes': path.stat().st_size,
                                        'bson_roundtrip_verified': True}
        print(json.dumps({'archived': name, 'documents': count, 'verified': True}), flush=True)
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf8')
    return manifest


def period_summaries(db, cutoff, archive=None):
    def records(name):
        return ([doc for doc, _ in bson_documents(archive / (name + '.bson.gz'))]
                if archive else list(db[name].find()))
    batches = records('batches_master')
    daily = records('daily_work_reports')
    periods = [{'kind': 'cycle', **{k: v for k, v in p.items() if k != '_id'}}
               for p in records('settlement_periods') if p.get('start_date', '') < cutoff]
    months = sorted({str(b.get('batch_date') or '')[:7] for b in batches
                     if len(str(b.get('batch_date') or '')) >= 10 and b['batch_date'] < cutoff})
    import calendar
    for month in months:
        year, number = map(int, month.split('-'))
        periods.append({'kind': 'month', 'start_date': month + '-01',
                        'end_date': f'{month}-{calendar.monthrange(year, number)[1]:02}'})
    result = []
    for period in periods:
        first, last = period['start_date'], min(period['end_date'], cutoff)
        totals = defaultdict(lambda: {'batches': 0, 'video_seconds': 0., 'tasks': 0})
        for batch in batches:
            if first <= str(batch.get('batch_date') or '') <= last:
                key = (str(batch.get('canonical_user') or batch.get('username') or 'Unknown'),
                       str(batch.get('status') or 'Unknown'))
                totals[key]['batches'] += 1
                totals[key]['video_seconds'] += float(batch.get('total_duration_seconds') or 0)
                totals[key]['tasks'] += int(batch.get('task_count') or 0)
        result.append({'period': period, 'as_of': datetime.now(timezone.utc).isoformat(),
                       'basis': 'Retained batch status as of archive, not status at cycle closure',
                       'final_settlement_certified': False,
                       'daily_capture_dates': [r['date'] for r in daily if first <= r['date'] <= last],
                       'by_user_status': [{'user': key[0], 'status': key[1], **values}
                                          for key, values in sorted(totals.items())]})
    return result


def prune_versions(db, destination, cutoff, apply=False):
    path = destination / db.name / 'workflow_records.bson.gz'
    latest, protected, tied_latest = {}, set(), {}
    for doc, _ in bson_documents(path):
        if doc.get('kind') == 'event':
            p = json.loads(doc['payload'])
            protected.add(p.get('source_reference'))
            protected.update(p.get('source_references') or [])
        identity = version_identity(doc)
        if identity:
            key, stamp = identity
            if key not in latest or stamp > latest[key][0]:
                latest[key] = (stamp, str(doc['_id']), doc['_id'])
                tied_latest[key] = {doc['_id']}
            elif stamp == latest[key][0]:
                tied_latest[key].add(doc['_id'])
    keep = protected | set().union(*tied_latest.values()) if tied_latest else protected
    count, deleted, candidates, checksums = 0, 0, [], hashlib.sha256()
    def flush():
        nonlocal deleted
        if apply and candidates:
            deleted += db.workflow_records.bulk_write(candidates, ordered=False).deleted_count
        candidates.clear()
    # Exact _id+payload predicates exclude any changed or newly-created record.
    # Only strict superseded versions from before the cutoff can be removed.
    with gzip.open(destination / 'pruned-version-ids.jsonl.gz', 'wt', encoding='utf8') as audit:
        for doc, _ in bson_documents(path):
            identity = version_identity(doc)
            if not identity or doc['_id'] in keep:
                continue
            _, stamp = identity
            try:
                old = datetime.fromisoformat(stamp.replace('Z', '+00:00'))
                eligible = old.tzinfo is not None and old < datetime.fromisoformat(cutoff + 'T00:00:00+05:30')
            except (TypeError, ValueError):
                eligible = False
            if not eligible:
                continue
            count += 1
            audit.write(json_util.dumps({'_id': doc['_id'], 'kind': doc['kind']}) + '\n')
            checksums.update(BSON.encode({'_id': doc['_id']}))
            candidates.append(DeleteOne({'_id': doc['_id'], 'kind': doc['kind'], 'payload': doc['payload']}))
            if len(candidates) == 300:
                flush()
        flush()
    retained_ids = list(set().union(*tied_latest.values())) if tied_latest else []
    for offset in range(0, len(retained_ids), 500):
        chunk = retained_ids[offset:offset + 500]
        if db.workflow_records.count_documents({'_id': {'$in': chunk}}) != len(chunk):
            raise ValueError('A retained latest version is missing')
    return {'applied': apply, 'eligible_superseded_versions': count, 'deleted_versions': deleted,
            'latest_identities_retained': len(latest), 'referenced_ids_protected': len(protected),
            'candidate_ids_sha256': checksums.hexdigest()}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--before', default='2026-11-25')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--reuse-verified-export', action='store_true')
    args = parser.parse_args()
    datetime.fromisoformat(args.before)
    dbm = DatabaseManager()
    try:
        if dbm.mongo_db is None:
            raise ValueError('A configured MongoDB database is required')
        db = dbm.mongo_db
        if args.reuse_verified_export:
            manifest = json.loads((args.output / 'manifest.json').read_text(encoding='utf8'))
            if manifest['database'] != db.name:
                raise ValueError('Archive database mismatch')
            for name, record in manifest['collections'].items():
                count, digest = 0, hashlib.sha256()
                for _, raw in bson_documents(args.output / db.name / (name + '.bson.gz')):
                    count += 1
                    digest.update(raw)
                if (count, digest.hexdigest()) != (record['documents'], record['bson_sha256']):
                    raise ValueError('Reused archive verification failed')
        else:
            manifest = export_database(db, args.output)
        summaries = period_summaries(db, args.before, args.output / db.name)
        (args.output / 'period-snapshots.json').write_text(json.dumps(summaries, indent=2), encoding='utf8')
        # Stored summaries point to the verified raw archive; no legacy report
        # or synthetic final-settlement payload is substituted for source data.
        archive_id = args.output.name
        if args.apply:
            db.history_archives.insert_one({'_id': archive_id, 'kind': 'verified_history_archive',
                'before_date': args.before, 'captured_at': manifest['captured_at'],
                'manifest': manifest, 'periods': summaries,
                'local_archive_path': str(args.output.resolve()),
                'final_settlement_certified': False})
        outcome = prune_versions(db, args.output, args.before, args.apply)
        (args.output / 'cleanup-result.json').write_text(json.dumps(outcome, indent=2), encoding='utf8')
        print(json.dumps(outcome), flush=True)
    finally:
        if dbm.mongo_client is not None:
            dbm.mongo_client.close()


if __name__ == '__main__':
    main()
