"""Build the real demo from a read-only research DB and checksum-verified SEC archive.

Only selected public excerpts and existing development reviews are exported.
No credentials, full filings, private reviewer returns, or model calls are used.
"""
import argparse
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from fig.normalization import normalize_html

# Existing source-reviewed development claims. No sealed/human-return labels.
CLAIMS = [
    '78a2e514-f555-54fa-9608-d78db94f1fcd',  # NVIDIA 2025 -> TSMC
    'ba304302-1f8a-5eb1-a8e5-3e7854c83872',  # NVIDIA 2025 -> Samsung
    '4642b1b8-53fe-5f9f-88e1-301aa52fe7bf',  # AMD 2025 -> TSMC
    '775f35cc-d3e2-5b0e-a453-c2ec9e90e920',  # AMD 2025 -> Samsung
    '00fdcaba-1aee-5166-9bf4-0a412697a802',  # Broadcom 2024 -> TSMC
]
# A later real NVIDIA passage is available for explicit acceptance/rejection.
REVIEW_PASSAGE = '16bd23c8-93af-58f3-8a12-a518accbda0a'


def build(database, archive):
    sources, entities = {}, {}
    with sqlite3.connect(database.resolve().as_uri() + '?mode=ro', uri=True) as db:
        def entity(id):
            value = json.loads(db.execute('SELECT payload FROM entity WHERE id=?', (id,)).fetchone()[0])
            entities[id] = value
            return value

        def source(passage_id):
            if passage_id in sources:
                return sources[passage_id]
            row = db.execute('SELECT p.payload,t.payload,d.payload FROM passage p '
                'JOIN text_version t ON t.id=p.text_version_id JOIN document d ON d.id=t.document_id '
                'WHERE p.id=?', (passage_id,)).fetchone()
            passage, version, document = map(json.loads, row)
            original = (archive / document['content_hash']).read_bytes()
            if sha256(original).hexdigest() != document['content_hash']:
                raise ValueError('Original SEC archive checksum mismatch')
            normalized = normalize_html(original, UUID(document['id']))
            if normalized.text_version.normalized_hash != version['normalized_hash']:
                raise ValueError('Original normalization does not reproduce')
            text = version['normalized_text'][passage['start_offset']:passage['end_offset']]
            if normalized.text_version.normalized_text[passage['start_offset']:passage['end_offset']] != text:
                raise ValueError('Excerpt differs from re-normalized SEC bytes')
            entity(document['issuer_id'])
            record = {'document': document,
                'text_version': {key: version[key] for key in ['id', 'parser_version', 'normalized_hash']},
                'passage': passage, 'text': text, 'text_hash': sha256(text.encode()).hexdigest(),
                'reviews': [], 'review_exercise': passage_id == REVIEW_PASSAGE}
            sources[passage_id] = record
            return record

        for id in CLAIMS:
            claim = json.loads(db.execute('SELECT payload FROM claim_revision WHERE id=?', (id,)).fetchone()[0])
            if not claim['reviewer'].startswith('codex:') or claim['review_state'] != 'accepted':
                raise ValueError('Only existing source-reviewed development claims are allowed')
            entity(claim['subject_id']); entity(claim['object_id'])
            rows = db.execute('SELECT payload FROM evidence WHERE claim_revision_id=?', (id,)).fetchall()
            if len(rows) != 1:
                raise ValueError('Expected one reviewed evidence record')
            evidence = json.loads(rows[0][0]); record = source(evidence['passage_id'])
            if record['text'].count(evidence['quote']) != 1:
                raise ValueError('Reviewed quote is not unique in its source passage')
            record['reviews'].append({'claim': claim, 'evidence': evidence})
        source(REVIEW_PASSAGE)
    snapshot = {'version': 'sec-demo-v1',
        'description': 'Historical SEC filing excerpts for NVIDIA, AMD and Broadcom; TSMC and Samsung counterparties.',
        'review_status': 'Existing Codex source reviews from development; not independent human annotations.',
        'scope': 'Selected excerpts only, not complete filings or a live company model. No financial materiality is asserted.',
        'entities': sorted(entities.values(), key=lambda item: item['id']),
        'sources': list(sources.values())}
    encoded = json.dumps(snapshot, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
    return {'snapshot_sha256': sha256(encoded).hexdigest(), 'snapshot': snapshot}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database', type=Path, required=True)
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--output', type=Path, default=Path('src/fig/resources/sec-demo-v1.json'))
    args = parser.parse_args()
    if args.output.exists():
        parser.error('Output already exists; review changes under a new snapshot version')
    data = build(args.database, args.archive)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(data, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'sources': len(data['snapshot']['sources']), 'claims': len(CLAIMS),
                      'snapshot_sha256': data['snapshot_sha256']}))


if __name__ == '__main__':
    main()
