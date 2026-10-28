"""Fixed evidence-key schema; preserves the initial attempted-review module."""
from copy import deepcopy
from fig.automated_schema_review import review_request as original_request
from fig.automated_schema_review import validate_review_result, automated_capacity_gate, ROLES


def review_request(*args,**kwargs):
    request=original_request(*args,**kwargs)
    schema=request['text']['format']['schema']
    item=schema['properties']['examples']['items']
    ids=item['properties']['passage_id']['enum']
    properties={}
    for pid in ids:
        entry=deepcopy(item);entry['properties']['passage_id']['enum']=[pid];properties[pid]=entry
    schema['properties']['examples']={'type':'object','properties':properties,'required':ids,'additionalProperties':False}
    request['input'][0]['content']+='\nThe examples object must assess every required passage key. Do not omit or abbreviate assessments.'
    return request


def normalize_result(result):
    result=deepcopy(result)
    result['examples']=list(result['examples'].values())
    return result
