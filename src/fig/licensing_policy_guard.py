"""Narrow deterministic enforcement of the frozen agreement-title exclusion."""
from copy import deepcopy
import re
from fig.anchored_extraction import AnchoredExperimentalExtractor
from fig.licensing_review import PREDICATE
TITLE=re.compile(r'(?is)^\s*(?:(?:amendment(?:\s+\w+){0,4}\s+to\s+)?(?:semiconductor\s+)?(?:patent\s+|technology\s+|intellectual\s+property\s+)?(?:cross[ -])?licen[cs]e\s+agreement)\s*,\s*dated\b')
ASSERTION=re.compile(r'(?i)\b(?:grants?|granted|obtained|receives?|received|licenses|licensed|entered|holds?|held)\b')
def excluded_agreement_title(text):
    """Only a short dated title with no assertion verb; not a general entailment oracle."""
    return len(text)<=1000 and bool(TITLE.search(text)) and not ASSERTION.search(text)

class GuardedLicensingExtractor(AnchoredExperimentalExtractor):
    def process(self,source,condition,result):
        output=super().process(source,condition,result)
        if excluded_agreement_title(source['text']):
            kept=[]
            for item in output['anchored_edges']:
                if item['edge']['predicate']==PREDICATE:
                    output['rejected_edges'].append({'edge_index':item['edge_index'],'raw_edge':deepcopy(item['raw_edge']),'reason':'frozen_policy_excludes_agreement_title_without_asserted_grant'})
                else:kept.append(item)
            output['anchored_edges']=kept
        output['policy_guard']='agreement-title-v1; other semantic failures require review'
        return output

def guard_references(references,rows):
    corrected=deepcopy(references);changes=[]
    for row in rows:
        if not excluded_agreement_title(row['text']):continue
        for role,reference in corrected.items():
            answer=reference['assessments'][row['passage_id']]
            if answer['verdict']!='unsupported' or answer['edges']:
                changes.append({'passage_id':row['passage_id'],'role':role,'original':deepcopy(answer),'rule':'frozen_definition_excludes_titles_without_grant_or_direction'})
                reference['assessments'][row['passage_id']]={'verdict':'unsupported','edges':[],'rationale':'Deterministic enforcement of the previously frozen agreement-title exclusion; original reference judgment is retained separately.'}
    return corrected,changes
