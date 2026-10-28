"""Approval-gated adapter for the separately frozen prospective configuration."""
from fig.generic_extraction import GenericOpenAIProvider, ProviderFailure


class FollowupOpenAIProvider(GenericOpenAIProvider):
    def __init__(self, cache_dir, semantic_catalog, *, approval, baseline_hash, child_hash,
                 budget_usd=5.0, max_output_tokens=8000, key=None, transport=None):
        if approval.get('status')!='eligible_for_schema_freeze':
            raise ProviderFailure('schema_review_not_approved')
        if approval.get('predicate')!='HAS_CAPACITY_ENTITLEMENT_IN':
            raise ProviderFailure('unexpected_schema_change')
        definition=semantic_catalog.get('predicates',{}).get('HAS_CAPACITY_ENTITLEMENT_IN',{}).get('definition')
        if definition!=approval.get('definition'):
            raise ProviderFailure('approved_definition_differs')
        if not 1<=max_output_tokens<=8000:
            raise ValueError('follow-up output ceiling is 8000')
        if not baseline_hash or not child_hash or baseline_hash==child_hash:
            raise ValueError('distinct frozen baseline and child hashes required')
        # Preserve the original release implementation and its public bounds.
        # The follow-up owns this explicit extension and its own configuration.
        super().__init__(cache_dir, semantic_catalog,budget_usd=budget_usd,
                         max_output_tokens=min(max_output_tokens,3000),key=key,transport=transport)
        self.max_output_tokens=max_output_tokens
        self.allowed_schema_hashes={baseline_hash,child_hash}

    def __call__(self, source, condition, policy):
        snapshot=policy.get('snapshot',{})
        if snapshot.get('schema_hash') not in self.allowed_schema_hashes:
            raise ProviderFailure('schema_outside_frozen_pair')
        return super().__call__(source,condition,policy)
