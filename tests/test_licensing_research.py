from datetime import datetime,timezone
from hashlib import sha256
from fig.contracts import ResearchRequest
from fig.licensing_experimental_graph import ExperimentalGraph,ExperimentalResearchService
from fig.research import ResearchService
P='LICENSES_TECHNOLOGY_FROM'

def setup(tmp_path):
    g=ExperimentalGraph(tmp_path/'isolated.sqlite3','child',{'entities':{'Company':{}},'predicates':{P:{}}});cases=[]
    for index,(s,o) in enumerate([('Buyer','Owner'),('Other','Owner'),('Other','Further')]):
        text=f'{s} licenses software from {o}.'
        cases.append({'issuer':s,'passage_id':str(index),'case_id':str(index),'accession':str(index),'source_url':'https://www.sec.gov/example','form':'10-K','filing_date':'2025-01-01','text':text,'text_hash':sha256(text.encode()).hexdigest(),'expected_edges':[{'subject_name':s,'object_name':o,'predicate':P,'quote':text,'start':0,'end':len(text)}]})
    g.add_cases(cases);return ExperimentalResearchService(g)

def test_intent_precedence_over_manufacturing():
    p=ResearchService.plan(None,ResearchRequest(question='Which companies license technology from Owner, the manufacturer?'),[{}]);assert p['intent']=='licensing_neighbors' and p['direction']=='incoming'

def test_one_hop_evidence_and_shared_licensor_no_direct_edge(tmp_path):
    service=setup(tmp_path)
    result=service.ask(ResearchRequest(question='Which technology licensors does Buyer license from?'))
    assert result['verification']['status']=='supported' and len(result['findings'])==1 and result['citations'][0]['quote']=='Buyer licenses software from Owner.'
    shared=service.ask(ResearchRequest(question='Which shared technology licensors connect Buyer and Other?'))
    assert len(shared['paths'])==1 and shared['paths'][0]['derived_direct_edge'] is False and len(shared['citations'])==2

def test_three_hops_and_unsupported_cutoffs(tmp_path):
    s=setup(tmp_path);p=s.ask(ResearchRequest(question='Show three-hop licensing paths between Buyer and Further.'))
    assert len(p['paths'])==1 and len(p['paths'][0]['edges'])==3
    early=s.ask(ResearchRequest(question='Which technology licensors does Buyer license from?',public_cutoff=datetime(2024,1,1,tzinfo=timezone.utc)))
    assert early['verification']['status']=='no_supported_path'
    # No current validity is inferred from publication alone.
    effective=s.ask(ResearchRequest(question='Which technology licensors does Buyer license from?',effective_at=datetime(2026,1,1,tzinfo=timezone.utc)))
    assert effective['verification']['status']=='no_supported_path'

def test_reference_graph_baseline_and_child_isolation(tmp_path):
    s=setup(tmp_path)
    r=s.ask(ResearchRequest(question='Which technology licensors does Buyer license from?',ontology_version='different'))
    assert not r['findings'] and r['query_plan']['ontology_version']=='child'
    assert not (tmp_path/'development.sqlite3').exists()
