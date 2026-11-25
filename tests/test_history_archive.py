import gzip
import importlib.util
from pathlib import Path

from bson import BSON, ObjectId
import pytest

spec = importlib.util.spec_from_file_location('archive_history', Path(__file__).parents[1] / 'scripts/archive_history.py')
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)


def test_bson_archive_roundtrip_preserves_types_and_detects_truncation(tmp_path):
    docs = [{'_id': ObjectId(), 'amount': 1.25}, {'_id': 'two', 'payload': b'bytes'}]
    path = tmp_path / 'records.bson.gz'
    raw = b''.join(BSON.encode(doc) for doc in docs)
    with gzip.open(path, 'wb') as stream:
        stream.write(raw)
    assert [doc for doc, _ in archive.bson_documents(path)] == docs
    with gzip.open(path, 'wb') as stream:
        stream.write(raw[:-1])
    with pytest.raises(ValueError, match='Truncated'):
        list(archive.bson_documents(path))


def test_cleanup_identity_preserves_distinct_real_event_ids():
    import json
    one = {'kind': 'observation', 'payload': json.dumps({'event_key': 'source:real-event-1', 'observed_at': '2026-11-24T01:00:00Z'})}
    two = {**one, 'payload': json.dumps({'event_key': 'source:real-event-2', 'observed_at': '2026-11-24T01:00:00Z'})}
    assert archive.version_identity(one)[0] != archive.version_identity(two)[0]
    assert archive.version_identity({'kind': 'event'}) is None
    assert archive.version_identity({'kind': 'observation', 'payload': '{}'}) is None


@pytest.mark.parametrize('apply', [False, True])
def test_prune_only_superseded_archived_versions_preserves_references_and_ties(tmp_path, apply):
    import json
    from types import SimpleNamespace
    def observation(tid, event, time):
        return {'_id': tid, 'kind': 'observation',
                'payload': json.dumps({'event_key': event, 'observed_at': time})}
    docs = [observation('old', 'event-a', '2026-11-23T01:00:00Z'),
            observation('latest', 'event-a', '2026-11-24T01:00:00Z'),
            observation('tied', 'event-a', '2026-11-24T01:00:00Z'),
            observation('referenced', 'event-b', '2026-11-23T01:00:00Z'),
            observation('latest-b', 'event-b', '2026-11-24T01:00:00Z'),
            observation('independent-event', 'event-c', '2026-11-23T01:00:00Z'),
            {'_id': 'current-event', 'kind': 'event', 'payload': json.dumps({'source_reference': 'referenced'})}]
    root = tmp_path / 'testdb'
    root.mkdir()
    with gzip.open(root / 'workflow_records.bson.gz', 'wb') as stream:
        for doc in docs:
            stream.write(BSON.encode(doc))
    class Collection:
        def __init__(self):
            self.docs = {doc['_id']: doc for doc in docs}
        def count_documents(self, query):
            return sum(tid in self.docs for tid in query['_id']['$in'])
        def bulk_write(self, requests, ordered=False):
            deleted = 0
            for request in requests:
                predicate = request._filter
                doc = self.docs.get(predicate['_id'])
                if doc and all(doc.get(k) == v for k, v in predicate.items()):
                    del self.docs[predicate['_id']]
                    deleted += 1
            return SimpleNamespace(deleted_count=deleted)
    collection = Collection()
    result = archive.prune_versions(SimpleNamespace(name='testdb', workflow_records=collection),
                                    tmp_path, '2026-11-25', apply=apply)
    assert result['eligible_superseded_versions'] == 1
    assert result['deleted_versions'] == (1 if apply else 0)
    assert {'latest', 'tied', 'referenced', 'latest-b', 'independent-event', 'current-event'} <= set(collection.docs)
