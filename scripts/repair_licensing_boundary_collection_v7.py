"""Validate an exact SEC search hit without fetching any documents."""
import re

def exact_hit(hit, metadata):
    accession, filename = hit['_id'].split(':', 1)
    if accession != metadata['accession'] or hit['_source'].get('adsh', accession) != accession:
        raise ValueError('accession mismatch')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*\.html?', filename) or '..' in filename:
        raise ValueError('unsafe or non-HTML document filename')
    cik = str(int(metadata['cik']))
    return {**metadata, 'matching_document': filename, 'matching_document_type': hit['_source']['file_type'],
            'hit_id': hit['_id'], 'source_url': f'https://www.sec.gov/Archives/edgar/data/{cik}/{accession.replace("-", "")}/{filename}'}
