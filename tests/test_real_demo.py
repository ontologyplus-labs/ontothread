"""The default demo uses real attributed SEC excerpts, with explicit partial scope."""
from copy import deepcopy
from hashlib import sha256
import json
import socket
import sys

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from fig.api import create_app
from fig.cli import main
from fig.config import Settings
from fig.contracts import Document, PathRequest, ResearchRequest
from fig.demo import load_snapshot, real_demo_records, seed_real_demo
from fig.extraction import Decision, ReviewQueue
from fig.fixture import fixture
from fig.research import ResearchService
from fig.store import ImmutableConflict, Store


@pytest.fixture
def workspace(tmp_path):
    settings = Settings('sqlite:///' + str(tmp_path/'demo.sqlite3'), tmp_path/'archive')
    store = Store(settings.database_url); store.migrate()
    return settings, store


def test_default_cli_demo_is_real_offline_and_idempotent(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError('Real snapshot demo attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('FIG_DATABASE_URL', 'sqlite:///demo.sqlite3')
    monkeypatch.setenv('FIG_ARCHIVE_DIR', 'archive')
    monkeypatch.setattr(sys, 'argv', ['ontothread', 'migrate']); main(); capsys.readouterr()
    monkeypatch.setattr(sys, 'argv', ['ontothread', 'demo']); main()
    first = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, 'argv', ['fig', 'demo']); main()
    assert json.loads(capsys.readouterr().out) == first
    assert first['source'] == 'real_sec_excerpts' and first['reviewed_claims'] == 5
    store = Store('sqlite:///demo.sqlite3')
    assert len(store.entities()['entities']) == 5
    assert len(store.entities(include_synthetic=True)['entities']) == 5
    assert store.health()['pending_projection_events'] == 5
    assert all('Example ' not in entity['canonical_name'] for entity in store.entities()['entities'])
    assert len(store.documents()['documents']) == 4


def test_real_demo_paths_quotes_and_excerpt_provenance(workspace):
    settings, store = workspace; seed_real_demo(store, settings.archive_dir)
    companies = {e['canonical_name']: e['id'] for e in store.entities()['entities']}
    paths = store.paths(PathRequest(source_entity_id=companies['NVIDIA CORP'],
        target_entity_id=companies['Samsung Electronics Co., Ltd.'],
        min_hops=3, max_hops=3, direction='both'))['paths']
    assert len(paths) == 1 and paths[0]['hops'] == 3
    assert len({id for id in paths[0]['entity_ids']}) == 4
    answer = ResearchService(store).ask(ResearchRequest(question='Show paths between NVIDIA and Broadcom'))
    assert answer['verification']['path_count'] == 1 and answer['verification']['citation_count'] == 2
    for document in store.documents()['documents']:
        assert document['source'] == 'sec' and document['content_scope'] == 'excerpt'
        assert document['source_url'].startswith('https://www.sec.gov/Archives/edgar/data/')
        origin = document['excerpt_origin']; assert document['id'] != origin['document_id']
        assert origin['content_hash'] != document['content_hash']
        passage = store.passages(document['id'])['passages'][0]
        raw = (settings.archive_dir/document['content_hash']).read_bytes()
        assert sha256(raw).hexdigest() == document['content_hash']
        assert raw.decode() == passage['text']
        assert len(passage['text']) == origin['end_offset'] - origin['start_offset']
    for edge in paths[0]['edges']:
        for cited in edge['evidence']:
            passage = store.passage(cited['passage']['id'])
            assert cited['evidence']['quote'] in passage['text']
            assert cited['document']['content_scope'] == 'excerpt'
            assert edge['claim']['reviewer'] == 'codex:historical-source-review'
    with TestClient(create_app(settings)) as client:
        data = client.get('/v1/documents').json()
        assert len(data['documents']) == 4
        assert all(document['excerpt_origin'] for document in data['documents'])


def test_real_review_exercise_preserves_decisions_and_identity_on_reseed(workspace):
    settings, store = workspace; result = seed_real_demo(store, settings.archive_dir)
    passage = store.passage(result['review_exercise_passage_ids'][0])
    queue = ReviewQueue(store, settings.archive_dir)
    candidates = queue.list(passage['document']['id'])['candidates']
    assert len(candidates) == 2 and all(row['state'] == 'pending' for row in candidates)
    tsmc = next(e for e in store.entities()['entities'] if e['canonical_name'].startswith('TAIWAN'))
    for candidate in candidates:
        action = 'accept' if candidate['counterparty_name'].startswith('Taiwan') else 'reject'
        queue.decide(candidate['id'], Decision(action=action, expected_version=1,
            reviewer='demo-workflow-test', entity_id=tsmc['id'] if action == 'accept' else None,
            notes='Disposable demo workflow exercise, not a new independent source assessment.'))
    seed_real_demo(store, settings.archive_dir)
    after = queue.list(passage['document']['id'], state='all')['candidates']
    assert {row['state'] for row in after} == {'accepted', 'rejected'}
    assert len(store.entities()['entities']) == 5
    assert store.health()['pending_projection_events'] == 6
    for candidate in after:
        assert len(queue.history(candidate['id'])['decisions']) == 1


def test_corrupt_packet_fails_before_seeding(workspace, tmp_path, monkeypatch):
    import fig.demo as demo
    settings, store = workspace
    fake = tmp_path/'resources'; fake.mkdir()
    packet = {'snapshot_sha256': '0'*64, 'snapshot': load_snapshot()}
    (fake/'sec-demo-v1.json').write_text(json.dumps(packet))
    monkeypatch.setattr(demo, 'files', lambda package: tmp_path)
    with pytest.raises(ValueError, match='checksum'):
        seed_real_demo(store, settings.archive_dir)
    assert store.documents()['documents'] == []


def test_invalid_excerpt_and_quote_are_rejected():
    snapshot = deepcopy(load_snapshot()); snapshot['sources'][0]['text'] += 'invented'
    with pytest.raises(ValueError, match='integrity'):
        real_demo_records(snapshot)
    snapshot = deepcopy(load_snapshot()); snapshot['sources'][0]['reviews'][0]['evidence']['quote'] = 'invented'
    with pytest.raises(ValidationError, match='quote'):
        real_demo_records(snapshot)


def test_excerpt_origin_is_immutable_and_legacy_documents_stay_full(workspace):
    settings, store = workspace
    sources, _, _ = real_demo_records(); source, raw = sources[0]
    store.ingest_source(source, raw, settings.archive_dir)
    origin = source.document.excerpt_origin.model_copy(update={'normalized_hash': '0'*64})
    changed = source.model_copy(update={'document': source.document.model_copy(update={'excerpt_origin': origin})})
    with pytest.raises(ImmutableConflict):
        store.ingest_source(changed, raw, settings.archive_dir)
    bundle, original = fixture(); old = bundle.document.model_dump(mode='json')
    old.pop('content_scope'); old.pop('excerpt_origin')
    document = Document.model_validate(old)
    assert document.content_scope == 'full_document' and document.excerpt_origin is None
    store.ingest(bundle, original, settings.archive_dir)
    assert store.document(bundle.document.id)['content_scope'] == 'full_document'
