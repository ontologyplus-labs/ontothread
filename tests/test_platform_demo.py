"""The distributable walkthrough must stay offline, auditable, and repeatable."""
import socket
import sys

from fastapi.testclient import TestClient

from fig.api import create_app
from fig.cli import main
from fig.config import Settings
from fig.contracts import NeighborRequest, PathRequest, ResearchRequest
from fig.extraction import Decision, ExtractRequest, ReviewQueue
from fig.fixture import demo_bundles
from fig.research import ResearchService
from fig.store import Store


def test_demo_cli_is_offline_and_repeatable(tmp_path, monkeypatch, capsys):
    def no_network(*args, **kwargs):
        raise AssertionError('Offline demo attempted a network connection')
    monkeypatch.setattr(socket.socket, 'connect', no_network)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('FIG_DATABASE_URL', 'sqlite:///demo.sqlite3')
    monkeypatch.setenv('FIG_ARCHIVE_DIR', 'archive')
    monkeypatch.setattr(sys, 'argv', ['fig', 'migrate'])
    main()
    monkeypatch.setattr(sys, 'argv', ['fig', 'demo'])
    main(); main()
    capsys.readouterr()
    store = Store('sqlite:///demo.sqlite3')
    entities = store.entities(include_synthetic=True)['entities']
    assert len(entities) == 4
    assert store.entities()['entities'] == []
    assert len(store.documents()['documents']) == 3
    assert store.health()['pending_projection_events'] == 3
    for bundle, original in demo_bundles():
        assert (tmp_path / 'archive' / bundle.document.content_hash).read_bytes() == original


def test_demo_paths_evidence_and_review_survive_reseeding(tmp_path, monkeypatch):
    monkeypatch.delenv('OPENAI_API_KEY', raising=False)
    monkeypatch.delenv('FIG_LLM_MODEL', raising=False)
    settings = Settings('sqlite:///' + str(tmp_path / 'demo.sqlite3'), tmp_path / 'archive')
    store = Store(settings.database_url); store.migrate()
    bundles = list(demo_bundles())
    for bundle, original in bundles:
        store.ingest(bundle, original, settings.archive_dir)
    first, last = bundles[0][0], bundles[-1][0]
    request = PathRequest(source_entity_id=first.claim.subject_id,
        target_entity_id=last.claim.object_id, min_hops=3, max_hops=3, direction='both')
    paths = store.paths(request)['paths']
    assert len(paths) == 1 and paths[0]['hops'] == 3
    answer = ResearchService(store).ask(ResearchRequest(question='Show paths between Example Designer and Example Customer'))
    assert answer['verification']['path_count'] == 1
    assert answer['verification']['citation_count'] == 3
    with TestClient(create_app(settings)) as client:
        assert client.get('/v1/extraction/configuration').json()['openai_configured'] is False
        for asset in ('/', '/assets/styles.css', '/assets/app.js'):
            assert client.get(asset).status_code == 200
    passage = store.passages(first.document.id, 'foundries')['passages'][0]
    queue = ReviewQueue(store, settings.archive_dir)
    queue.extract(ExtractRequest(passage_ids=[passage['id']]))
    candidates = queue.list(first.document.id)['candidates']
    assert len(candidates) == 2
    assert all(candidate['state'] == 'pending' for candidate in candidates)
    for candidate, action in zip(candidates, ('accept', 'reject')):
        queue.decide(candidate['id'], Decision(action=action, expected_version=1,
            reviewer='synthetic-platform-test', canonical_name=candidate['counterparty_name']))
    for bundle, original in demo_bundles():
        store.ingest(bundle, original, settings.archive_dir)
    queue.extract(ExtractRequest(passage_ids=[passage['id']]))
    after = queue.list(first.document.id, state='all')['candidates']
    assert {candidate['state'] for candidate in after} == {'accepted', 'rejected'}
    assert len(store.neighbors(NeighborRequest(entity_id=first.claim.subject_id))['relationships']) == 2
    for candidate in after:
        decisions = queue.history(candidate['id'])['decisions']
        assert len(decisions) == 1 and decisions[0]['reviewer'] == 'synthetic-platform-test'
