import importlib.util
from pathlib import Path
import pytest
spec=importlib.util.spec_from_file_location('repair',Path(__file__).parents[1]/'scripts/repair_licensing_boundary_collection_v7.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
META={'accession':'0001193125-20-272580','cik':'0000050863','primary_document':'parent8k.htm','source_url':'https://www.sec.gov/parent8k.htm'}
def hit(filename='agreement.htm', accession=META['accession']):
    return {'_id':accession+':'+filename,'_source':{'adsh':accession,'file_type':'EX-2.1'}}
def test_exact_exhibit_is_not_parent():
    result=m.exact_hit(hit(),META)
    assert result['source_url']=='https://www.sec.gov/Archives/edgar/data/50863/000119312520272580/agreement.htm'
    assert result['primary_document']=='parent8k.htm'
@pytest.mark.parametrize('filename',['../secret.htm','a/b.htm','evil?x.htm','%2e%2e.htm','document.pdf'])
def test_invalid_filename(filename):
    with pytest.raises(ValueError):m.exact_hit(hit(filename),META)
def test_accession_mismatch():
    with pytest.raises(ValueError):m.exact_hit(hit(accession='0001193125-20-999999'),META)
def test_two_exhibits_have_distinct_identity():
    assert m.exact_hit(hit('one.htm'),META)['source_url']!=m.exact_hit(hit('two.htm'),META)['source_url']
