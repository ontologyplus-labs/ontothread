"""Isolated extraction adapter with source anchoring and explicit review state."""
from copy import deepcopy
from hashlib import sha256
from fig.evidence_spans import anchor_edge
from fig.expanded_experiment import validate_edge
from fig.followup_schema import canonical_schema_hash
from fig.generic_extraction import ProviderFailure,payload

class AnchoredExperimentalExtractor:
    """Provider returns structured edges; anchoring never approves factual claims."""
    def __init__(self, provider, *, snapshots, semantic_catalog):
        self.provider=provider;self.snapshots=deepcopy(snapshots);self.semantic_catalog=deepcopy(semantic_catalog)
        if set(self.snapshots)!={'baseline','licensing'}:raise ValueError('matched frozen schema pair required')
        for snapshot in self.snapshots.values():
            if canonical_schema_hash(snapshot['definitions'])!=snapshot['schema_hash']:raise ValueError('schema hash mismatch')
        base=self.snapshots['baseline']['definitions'];child=self.snapshots['licensing']['definitions']
        if set(child['predicates'])-set(base['predicates'])!={'LICENSES_TECHNOLOGY_FROM'}:raise ValueError('unexpected schema additions')
        if child['entities']!=base['entities'] or any(child['predicates'].get(k)!=v for k,v in base['predicates'].items()):raise ValueError('existing schema changed')

    def __call__(self,source,condition):
        if condition not in self.snapshots:raise ValueError('unknown condition')
        # Source-only payload validates exact input fields and checksum.
        request=payload(source,{'snapshot':self.snapshots[condition]},self.semantic_catalog,max_output_tokens=2500)
        result=self.provider.call(request)
        return self.process(source,condition,result)

    def process(self,source,condition,result):
        if condition not in self.snapshots:raise ValueError('unknown condition')
        if sha256(source['text'].encode()).hexdigest()!=source['text_hash']:raise ValueError('source hash mismatch')
        if not isinstance(result,dict) or set(result)!={'edges'} or not isinstance(result['edges'],list) or len(result['edges'])>30:raise ProviderFailure('invalid_edge_envelope')
        catalog=self.snapshots[condition]['definitions'];anchored=[];rejected=[]
        for index,raw in enumerate(result['edges']):
            validate_edge(raw);rule=catalog['predicates'].get(raw['predicate'])
            if not rule or raw['subject_kind'] not in rule['subject'] or raw['object_kind'] not in rule['object']:
                rejected.append({'edge_index':index,'raw_edge':deepcopy(raw),'reason':'predicate_or_endpoint_kind_outside_schema'});continue
            evidence=anchor_edge({'text':source['text'],'issuer':source['issuer_name']},raw)
            if evidence['status']=='rejected':
                rejected.append({'edge_index':index,'raw_edge':deepcopy(raw),'reason':evidence['reason']});continue
            anchored.append({'edge_index':index,'raw_edge':deepcopy(raw),'edge':{**raw,'quote':evidence['source_quote']},
                             'evidence':{**evidence,'source_id':source['id'],'source_text_hash':source['text_hash']},
                             'review_state':'awaiting_semantic_review'})
        return {'source_id':source['id'],'condition':condition,'schema_hash':self.snapshots[condition]['schema_hash'],
                'raw_edges':deepcopy(result['edges']),'anchored_edges':anchored,'rejected_edges':rejected,
                'factual_acceptance':'not_performed','production_imports':0}
