"""Synchronous recorded Responses calls with a cumulative reservation ledger."""
from hashlib import sha256
import json
import os
from pathlib import Path
import httpx
from fig.generic_extraction import PRICES, ProviderFailure, usage_cost


class BoundedResponses:
    def __init__(self,folder,*,budget_usd=1.0,key=None,transport=None):
        if not 0<budget_usd<=5:raise ValueError('budget must be positive and at most $5')
        self.folder=Path(folder);self.folder.mkdir(parents=True,exist_ok=True)
        self.budget=budget_usd;self.key=key or os.getenv('OPENAI_API_KEY');self.transport=transport
        self.ledger_path=self.folder/'api-usage.json'
        self.state=json.loads(self.ledger_path.read_text()) if self.ledger_path.exists() else {'requests':0,'known_cost_usd':0.0,'uncertain_failure_cost_upper_bound_usd':0.0,'budget_usd':budget_usd,'model':'gpt-5.4-mini-2026-03-17'}
        if self.state['budget_usd']!=budget_usd:raise ValueError('cannot change a ledger budget on resume')

    def call(self,request):
        if request['model']!=self.state['model']:raise ValueError('model snapshot differs')
        encoded=json.dumps(request,sort_keys=True,separators=(',',':')).encode();h=sha256(encoded).hexdigest();path=self.folder/(h+'.json')
        if path.exists():
            r=json.loads(path.read_text())
            if r['request_sha256']!=h:raise ValueError('cache hash differs')
            return r['output']
        if not self.key:raise ProviderFailure('OPENAI_API_KEY_not_configured')
        reserve=((len(encoded)+8192)*PRICES['input_per_million']+request['max_output_tokens']*PRICES['output_per_million'])/1e6
        if self.state['known_cost_usd']+self.state['uncertain_failure_cost_upper_bound_usd']+reserve>self.budget:raise ProviderFailure('spend_limit_reached')
        self.state['requests']+=1
        self.state['uncertain_failure_cost_upper_bound_usd']+=reserve
        self._save()
        with httpx.Client(timeout=90,trust_env=False,transport=self.transport) as c:
            response=c.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+self.key},json=request)
        if response.status_code!=200:raise ProviderFailure(f'provider_http_{response.status_code}')
        r=response.json();cost=usage_cost(r.get('usage'))
        self.state['known_cost_usd']+=cost;self.state['uncertain_failure_cost_upper_bound_usd']-=reserve;self._save()
        if r.get('status')!='completed':raise ProviderFailure('provider_incomplete')
        parts=[p for o in r.get('output',[]) if o.get('type')=='message' for p in o.get('content',[]) if p.get('type')=='output_text']
        if len(parts)!=1:raise ProviderFailure('provider_structured_output_missing')
        output=json.loads(parts[0]['text'])
        path.write_text(json.dumps({'request_sha256':h,'output':output,'usage':r['usage'],'cost_usd':cost,'response_id':r.get('id')},indent=2)+'\n')
        return output

    def _save(self):
        temp=self.ledger_path.with_suffix('.tmp');temp.write_text(json.dumps(self.state,indent=2)+'\n');temp.replace(self.ledger_path)
