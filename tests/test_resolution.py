from pathlib import Path
from uuid import uuid4
from datetime import datetime,timedelta

import pytest
from fastapi.testclient import TestClient

from fig.api import create_app
from fig.config import Settings
from fig.contracts import Entity,EntityResolutionDecision,NeighborRequest
from fig.fixture import fixture
from fig.store import Store,ResolutionConflict

@pytest.fixture
def setup(tmp_path):
    settings=Settings('sqlite:///'+str(tmp_path/'resolution.sqlite3'),tmp_path/'archive')
    store=Store(settings.database_url);store.migrate()
    bundle,original=fixture();store.ingest(bundle,original,settings.archive_dir)
    alias=next(entity for entity in bundle.entities if entity.id==bundle.claim.object_id)
    canonical=Entity(id=uuid4(),kind='Company',canonical_name='Canonical Foundry Holdings',slug='canonical-foundry')
    with store.connect() as conn:store.insert_immutable(conn,'entity',canonical,['kind','canonical_name','slug','status'])
    return settings,store,bundle,alias,canonical

def merge(canonical,version=0):
    return EntityResolutionDecision(action='merge',canonical_entity_id=canonical.id,
                                    expected_version=version,reviewer='identity-reviewer',
                                    notes='Verified against an authoritative company identifier.')

def test_reviewed_merge_canonicalizes_queries_and_is_reversible(setup):
    settings,store,bundle,alias,canonical=setup
    with store.connect() as conn:
        store.execute(conn,"UPDATE projection_outbox SET state='delivered'")
    result=store.resolve_entity(alias.id,merge(canonical))
    assert result['state']=='merged' and result['version']==1
    outgoing=store.neighbors(NeighborRequest(entity_id=bundle.claim.subject_id))
    relation=outgoing['relationships'][0]
    assert relation['claim']['object_id']==str(alias.id)  # immutable source assertion
    assert relation['resolved_object_id']==str(canonical.id)
    incoming=store.neighbors(NeighborRequest(entity_id=canonical.id,direction='incoming'))
    assert len(incoming['relationships'])==1
    assert incoming['canonical_entity_id']==str(canonical.id)
    assert str(alias.id) not in {e['id'] for e in store.entities(include_synthetic=True)['entities']}
    with store.connect() as conn:
        assert store.execute(conn,"SELECT state FROM projection_outbox").fetchone()['state']=='pending'
    history=store.resolution_history(alias.id)
    assert history['canonical_entity_id']==str(canonical.id) and len(history['decisions'])==1
    decided=datetime.fromisoformat(result['decided_at'].replace('Z','+00:00'))
    before=decided-timedelta(microseconds=1)
    assert store.neighbors(NeighborRequest(entity_id=alias.id,direction='incoming',identity_cutoff=before))['relationships']
    assert not store.neighbors(NeighborRequest(entity_id=canonical.id,direction='incoming',identity_cutoff=before))['relationships']
    assert store.neighbors(NeighborRequest(entity_id=canonical.id,direction='incoming',identity_cutoff=decided))['relationships']

    split=EntityResolutionDecision(action='split',expected_version=1,reviewer='identity-reviewer',
                                   notes='Reversed during a controlled resolution test.')
    assert store.resolve_entity(alias.id,split)['state']=='split'
    assert not store.neighbors(NeighborRequest(entity_id=canonical.id,direction='incoming'))['relationships']
    assert store.neighbors(NeighborRequest(entity_id=alias.id,direction='incoming'))['relationships']
    assert len(store.resolution_history(alias.id)['decisions'])==2

def test_merge_guards_cycles_types_and_stale_decisions(setup):
    settings,store,bundle,alias,canonical=setup
    store.resolve_entity(alias.id,merge(canonical))
    with pytest.raises(ResolutionConflict):store.resolve_entity(alias.id,merge(canonical,0))
    with pytest.raises(ValueError,match='canonical target'):
        store.resolve_entity(bundle.claim.subject_id,merge(alias))
    product=Entity(id=uuid4(),kind='Product',canonical_name='A Product',slug='product')
    with store.connect() as conn:store.insert_immutable(conn,'entity',product,['kind','canonical_name','slug','status'])
    with pytest.raises(ValueError,match='kinds'):
        store.resolve_entity(product.id,merge(canonical))

def test_resolution_api_audit_and_origin_guard(setup):
    settings,store,bundle,alias,canonical=setup
    body=merge(canonical).model_dump(mode='json')
    with TestClient(create_app(settings)) as client:
        blocked=client.post(f'/v1/entities/{alias.id}/resolution-decisions',json=body,
                            headers={'Origin':'https://unrelated.test'})
        assert blocked.status_code==403
        accepted=client.post(f'/v1/entities/{alias.id}/resolution-decisions',json=body)
        assert accepted.status_code==200 and accepted.json()['version']==1
        history=client.get(f'/v1/entities/{alias.id}/resolution').json()
        assert history['decisions'][0]['reviewer']=='identity-reviewer'
        assert client.post(f'/v1/entities/{alias.id}/resolution-decisions',json=body).status_code==409

def test_resolution_migration_packaged_identically():
    root=Path(__file__).resolve().parents[1]
    assert (root/'migrations/004_entity_resolution.sql').read_bytes()==(root/'src/fig/resources/004_entity_resolution.sql').read_bytes()
