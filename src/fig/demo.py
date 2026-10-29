"""Reproducible real SEC demo; selected historical excerpts, never invented facts."""
from hashlib import sha256
from importlib.resources import files
import json
from uuid import NAMESPACE_URL, uuid5

from fig.contracts import (Document, Entity, ExcerptOrigin, Passage, ReviewedBundle,
                           SourceBundle, TextVersion)
from fig.extraction import ExtractRequest, ReviewQueue


def load_snapshot():
    packet = json.loads(files('fig').joinpath('resources/sec-demo-v1.json').read_text())
    snapshot = packet['snapshot']
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    if sha256(encoded).hexdigest() != packet['snapshot_sha256']:
        raise ValueError('SEC demo snapshot checksum mismatch')
    if snapshot['version'] != 'sec-demo-v1':
        raise ValueError('Unsupported SEC demo snapshot')
    return snapshot


def real_demo_records(snapshot=None):
    """Validate the entire packet before seeding; IDs coexist with full SEC ingestion."""
    from fig.sec import SecClient
    snapshot = load_snapshot() if snapshot is None else snapshot
    entities = {item['id']: Entity.model_validate(item) for item in snapshot['entities']}
    sources, reviews, exercises = [], [], []
    def uid(name):
        return uuid5(NAMESPACE_URL, 'ontothread:sec-demo:v1:' + name)

    for item in snapshot['sources']:
        original = Document.model_validate(item['document'])
        SecClient.validate_url(original.source_url)
        if original.source != 'sec' or original.content_scope != 'full_document':
            raise ValueError('Real demo requires original SEC filing provenance')
        text, passage = item['text'], item['passage']
        digest = sha256(text.encode()).hexdigest()
        if digest != item['text_hash'] or len(text) != passage['end_offset'] - passage['start_offset']:
            raise ValueError('SEC demo excerpt integrity mismatch')
        origin = ExcerptOrigin(document_id=original.id, text_version_id=item['text_version']['id'],
            content_hash=original.content_hash, normalized_hash=item['text_version']['normalized_hash'],
            parser_version=item['text_version']['parser_version'],
            start_offset=passage['start_offset'], end_offset=passage['end_offset'])
        key = str(original.id) + ':' + passage['id'] + ':' + digest
        document = original.model_copy(update={'id': uid('document:' + key),
            'content_hash': digest, 'content_scope': 'excerpt', 'excerpt_origin': origin})
        version = TextVersion(id=uid('text:' + key), document_id=document.id,
            parser_version='sec-demo-excerpt-v1', normalized_hash=digest, normalized_text=text)
        selected = Passage(id=uid('passage:' + key), text_version_id=version.id,
            section_path=passage['section_path'], start_offset=0, end_offset=len(text))
        source = SourceBundle(issuer=entities[str(original.issuer_id)], document=document,
            text_version=version, passages=[selected],
            quality_flags=['selected_sec_excerpt', 'not_complete_filing',
                           'historical_demo_snapshot', 'development_source_reviews'])
        sources.append((source, text.encode()))
        if item['review_exercise']:
            exercises.append(selected.id)
        for retained in item['reviews']:
            claim = dict(retained['claim']); evidence = dict(retained['evidence'])
            if not claim.get('reviewer', '').startswith('codex:') or claim['review_state'] != 'accepted':
                raise ValueError('Demo claims must retain their development source reviewer')
            claim['id'] = str(uid('claim-revision:' + claim['id'] + ':' + key))
            claim['claim_id'] = str(uid('claim:' + claim['claim_id'] + ':' + key))
            evidence.update(id=str(uid('evidence:' + evidence['id'] + ':' + key)),
                claim_revision_id=claim['id'], passage_id=str(selected.id),
                start_offset=evidence['start_offset'] - passage['start_offset'],
                end_offset=evidence['end_offset'] - passage['start_offset'])
            ids = dict.fromkeys([str(original.issuer_id), claim['subject_id'], claim['object_id']])
            reviews.append(ReviewedBundle(entities=[entities[id] for id in ids], document=document,
                text_version=version, passage=selected, claim=claim, evidence=evidence))
    if not sources or not reviews or not exercises:
        raise ValueError('SEC demo snapshot is incomplete')
    return sources, reviews, exercises


def seed_real_demo(store, archive_dir):
    snapshot = load_snapshot()
    sources, reviews, exercises = real_demo_records(snapshot)
    for source, original in sources:
        store.ingest_source(source, original, archive_dir)
    for bundle in reviews:
        # The archive explicitly contains the selected excerpt, not the full HTML.
        store.ingest(bundle, bundle.text_version.normalized_text.encode(), archive_dir)
    store.seed_core_registry()
    ReviewQueue(store, archive_dir).extract(ExtractRequest(passage_ids=exercises))
    return {'dataset': 'sec-demo-v1', 'source': 'real_sec_excerpts',
        'documents': len(sources), 'reviewed_claims': len(reviews),
        'review_exercise_passage_ids': [str(id) for id in exercises],
        'review_status': snapshot['review_status'],
        'scope': snapshot['scope']}
