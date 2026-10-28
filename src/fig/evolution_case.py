"""Reproducible development case proving one complete ontology-evolution loop."""
import json
from datetime import datetime,timezone
from uuid import NAMESPACE_URL,uuid5

from fig.contracts import (ClaimRevision,Document,Entity,Evidence,NeighborRequest,
                           OntologyProposalCreate,OntologyProposalDecision,Passage,
                           ReviewedBundle,TextVersion)
from fig.ontology_runtime import RuntimeOntology


PREDICATE="PROVIDES_ADVANCED_PACKAGING"
SOURCE_ACCESSION="0001193125-24-099840"
SOURCE_QUOTE="We also offer design, mask making, TSMC 3DFabricTM advanced packaging and silicon stacking technologies and testing services."
EVIDENCE_PASSAGE_IDS=(
    "63d3dc2b-fed1-5d49-9bb9-e43ce05c0620",
    "d9b80181-27a5-597a-86fd-2a24979125da",
    "e2e27b83-4617-5f85-b8a8-1715b4d80865",
)


def _source_records(store):
    with store.connect() as conn:
        row=store.execute(conn,"""SELECT p.payload AS passage,t.payload AS text_version,d.payload AS document,e.payload AS issuer
            FROM passage p JOIN text_version t ON t.id=p.text_version_id JOIN document d ON d.id=t.document_id
            JOIN entity e ON e.id=d.issuer_id WHERE d.accession=? ORDER BY p.start_offset""",(SOURCE_ACCESSION,)).fetchall()
    for item in row:
        passage=Passage.model_validate_json(item["passage"]);version=TextVersion.model_validate_json(item["text_version"])
        text=version.normalized_text[passage.start_offset:passage.end_offset]
        if text.count(SOURCE_QUOTE)==1:
            return Entity.model_validate_json(item["issuer"]),Document.model_validate_json(item["document"]),version,passage,text
    raise KeyError("the reviewed advanced-packaging source passage is not present")


def _proposal(store,passage_ids):
    with store.connect() as conn:
        row=store.execute(conn,"SELECT payload FROM ontology_change_proposal WHERE concept_name=? ORDER BY created_at LIMIT 1",(PREDICATE,)).fetchone()
    if row:return json.loads(row["payload"])
    return store.create_ontology_proposal(OntologyProposalCreate(
        change_type="add_predicate",concept_name=PREDICATE,
        definition="The subject company explicitly provides advanced semiconductor packaging technology or services represented by the object technology.",
        rationale="Reviewed TSMC filings explicitly state that the issuer offers advanced packaging technologies and services, which finance-v2 cannot encode as a Company-to-Technology fact.",
        proposed_schema={"subject":["Company"],"object":["Technology"]},evidence_passage_ids=passage_ids,
        recurrence_count=len(passage_ids),base_ontology_version="finance-v2",proposer="development:schema-discovery"))


def _publish(store,proposal):
    if proposal["state"]=="accepted":
        history=store.ontology_proposal(proposal["id"]);return history["migration"]["to_version"],history
    result=store.decide_ontology_proposal(proposal["id"],OntologyProposalDecision(
        action="accept",expected_version=proposal["version"],reviewer="development:codex-source-review",
        notes="Development-only source review confirmed a Company-to-Technology provider relation. This is not independent human annotation.",
        migration_notes="Add PROVIDES_ADVANCED_PACKAGING without rewriting claims validated under earlier ontology versions."))
    return result["migration"]["to_version"],result


def run_advanced_packaging_case(store):
    store.migrate();issuer,document,text_version,passage,passage_text=_source_records(store)
    v2=RuntimeOntology.from_store(store,"finance-v2")
    old_errors=v2.relationship_errors("Company",PREDICATE,"Technology")
    if not old_errors:raise RuntimeError("development case is no longer unrepresentable under finance-v2")
    discovery=store.create_schema_discovery(passage_id=passage.id,failure_type="missing_predicate",concept_name=PREDICATE,
        proposed_change_type="add_predicate",exact_quote=SOURCE_QUOTE,
        rationale="The source explicitly describes a provided advanced-packaging technology/service, but finance-v2 has no suitable predicate.",
        proposed_schema={"subject":["Company"],"object":["Technology"]})
    evidence_ids=[value for value in EVIDENCE_PASSAGE_IDS if _passage_exists(store,value)]
    if str(passage.id) not in evidence_ids:evidence_ids.insert(0,str(passage.id))
    proposal=_proposal(store,evidence_ids);new_version,decision=_publish(store,proposal);vnext=RuntimeOntology.from_store(store,new_version)
    vnext.validate_relationship("Company",PREDICATE,"Technology")
    technology=Entity(id=uuid5(NAMESPACE_URL,"fig:technology:advanced-packaging-services"),kind="Technology",
                      canonical_name="Advanced Packaging Services",slug="advanced-packaging-services",status="reviewed")
    before=store.neighbors(NeighborRequest(entity_id=issuer.id,direction="outgoing",ontology_version="finance-v2",limit=100))
    job=store.create_reprocessing_job(proposal["id"],"finance-v2",new_version,evidence_ids);store.update_reprocessing_job(job["id"],"running")
    key=f"fig:evolution:{passage.id}:{issuer.id}:{PREDICATE}:{technology.id}"
    claim_id=uuid5(NAMESPACE_URL,key);revision_id=uuid5(NAMESPACE_URL,key+":revision:1")
    with store.connect() as conn:existing=store.execute(conn,"SELECT id FROM claim_revision WHERE id=?",(str(revision_id),)).fetchone()
    created=not bool(existing)
    if created:
        now=datetime.now(timezone.utc)
        claim=ClaimRevision(id=revision_id,claim_id=claim_id,subject_id=issuer.id,object_id=technology.id,predicate=PREDICATE,
            assertion_class="normalized_explicit",review_state="accepted",reviewer="development:codex-source-review",
            source_available_at=document.published_at,system_from=max(now,document.acquired_at))
        start=passage.start_offset+passage_text.index(SOURCE_QUOTE)
        evidence=Evidence(id=uuid5(NAMESPACE_URL,key+":evidence"),claim_revision_id=revision_id,passage_id=passage.id,
                          quote=SOURCE_QUOTE,start_offset=start,end_offset=start+len(SOURCE_QUOTE),assessment="supported")
        bundle=ReviewedBundle(ontology_version=new_version,ontology_schema_hash=vnext.schema_hash,entities=[issuer,technology],
                              document=document,text_version=text_version,passage=passage,claim=claim,evidence=evidence)
        with store.connect() as conn:store.persist_reviewed(conn,bundle)
    after=store.neighbors(NeighborRequest(entity_id=issuer.id,direction="outgoing",ontology_version=new_version,limit=100))
    before_hits=[r for r in before["relationships"] if r["claim"]["predicate"]==PREDICATE]
    after_hits=[r for r in after["relationships"] if r["claim"]["predicate"]==PREDICATE]
    result={"recovered_claim_revision_id":str(revision_id),"created":created,"before_count":len(before_hits),"after_count":len(after_hits),
            "competency_question":"Which reviewed company explicitly provides advanced-packaging technology or services?",
            "old_answer":{"ontology_version":"finance-v2","status":"unsupported_by_ontology","validation_errors":old_errors,"relationships":before_hits},
            "new_answer":{"ontology_version":new_version,"status":"supported" if after_hits else "missing","relationships":after_hits},
            "source":{"accession":document.accession,"document_id":str(document.id),"passage_id":str(passage.id),"quote":SOURCE_QUOTE,"url":document.source_url}}
    store.update_reprocessing_job(job["id"],"completed",result=result)
    current_proposal=decision.get("proposal",proposal)
    return {"case":"advanced-packaging-provider-development-v1","development_only":True,"independent_human_review":False,
            "discovery":discovery,"proposal":current_proposal,"ontology_decision":decision,"reprocessing_job_id":job["id"],**result}


def _passage_exists(store,passage_id):
    try:store.passage(passage_id);return True
    except KeyError:return False
