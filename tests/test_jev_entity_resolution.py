from fig.config import Settings
from fig.fixture import fixture
from fig.jev_entity_resolution import JevEntityResolver,rank_entity_mentions
from fig.jev_shadow import JevAnswer
from fig.store import Store


class RecordedClient:
    model="recorded-jev";endpoint="recorded://jev"
    def ask(self,state,questions):
        selection=state["candidate_entities"][0]["id"]
        return {
            "canonical_entity":JevAnswer(choice=selection,probabilities={selection:.95,"new_entity":.03,"insufficient_information":.02},confidence=.9),
            "same_entity":JevAnswer(noul=.96),
            "requires_human_review":JevAnswer(noul=.08),
        },{"usage":{"input_tokens":10,"output_tokens":3}}


def setup_store(tmp_path):
    settings=Settings("sqlite:///"+str(tmp_path/"entities.sqlite3"),tmp_path/"archive");store=Store(settings.database_url);store.migrate()
    bundle,original=fixture();store.ingest(bundle,original,settings.archive_dir);store.seed_core_registry();return store,bundle


def test_entity_shadow_ranks_only_supplied_candidates_and_caches(tmp_path):
    store,_=setup_store(tmp_path);expected=store.entity_resolution_candidates("NVIDA")["candidates"][0]["entity"]["id"]
    cases=[{"id":"typo","mention":"NVIDA","context":"chip designer","expected_entity_id":expected}]
    report=rank_entity_mentions(store,cases,tmp_path/"cache",resolver=JevEntityResolver(RecordedClient()))
    assert report["labelled_accuracy"]==1 and report["automatic_merge_allowed"] is False
    assert report["results"][0]["decision"]["shadow_only"] is True
    replay=rank_entity_mentions(store,cases,tmp_path/"cache",resolver=JevEntityResolver(RecordedClient()))
    assert replay["request_count"]==0


def test_entity_shadow_rejects_choice_outside_shortlist(tmp_path):
    store,_=setup_store(tmp_path)
    class Invalid(RecordedClient):
        def ask(self,state,questions):
            answers,meta=super().ask(state,questions);answers["canonical_entity"].choice="invented-id";return answers,meta
    try:JevEntityResolver(Invalid()).rank("NVIDA","",store.entity_resolution_candidates("NVIDA"))
    except RuntimeError as exc:
        assert "outside" in str(exc);return
    raise AssertionError("out-of-shortlist entity was accepted")
