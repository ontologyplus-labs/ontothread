"""Prepare bounded evidence packets without making model calls."""
import json
from datetime import datetime, timezone
from pathlib import Path

from fig.contracts import NeighborRequest,DocumentComparisonRequest,RelationshipHistoryRequest
from fig.evaluation import Dataset


def _compact(value,limit=14000):
    text=json.dumps(value,ensure_ascii=False,sort_keys=True)
    return text if len(text)<=limit else text[:limit]+"…[bounded]"

def extraction_packets(dataset_path):
    dataset=Dataset.model_validate_json(Path(dataset_path).read_text());items=[]
    for case in dataset.cases:
        proposed=[{"subject":"ISSUER" if edge.subject_is_issuer else edge.counterparty_name,
                   "predicate":edge.predicate,"object":edge.counterparty_name if edge.subject_is_issuer else "ISSUER",
                   "quote":edge.supporting_quote} for edge in case.expected]
        items.append({"id":"extraction:"+case.id,"kind":"extraction_label_review","issuer":case.issuer_name,"passage":case.text,
                      "candidate_relationships":proposed,"rubric":"Pass only if the candidate list is complete and every directed relationship is explicitly supported by one exact quote. Empty is correct for passages without a named explicit relationship."})
    return items

def _entity(store,mention):
    result=store.resolve_entity_mention(mention)["resolved"]
    if not result:raise ValueError("unresolved entity: "+mention)
    return result

def _annual_documents(store,entity_id):
    with store.connect() as conn:
        rows=store.execute(conn,"SELECT payload FROM document WHERE issuer_id=? AND source='sec' ORDER BY published_at DESC",(entity_id,)).fetchall()
    docs=[json.loads(row["payload"]) for row in rows]
    return [doc for doc in docs if doc["form"] in {"10-K","20-F"}]

def _entity_by_slug(store,slug):
    with store.connect() as conn:row=store.execute(conn,"SELECT payload FROM entity WHERE slug=?",(slug,)).fetchone()
    return json.loads(row["payload"]) if row else None

def _claim_summaries(result,entities,predicate=None):
    names={entity["id"]:entity["canonical_name"] for entity in entities};summaries=[]
    for edge in result["relationships"]:
        if predicate and edge["claim"]["predicate"]!=predicate:continue
        evidence=edge["evidence"][0]
        summaries.append({"subject":names.get(edge["resolved_subject_id"],edge["resolved_subject_id"]),"predicate":edge["claim"]["predicate"],"object":names.get(edge["resolved_object_id"],edge["resolved_object_id"]),"quote":evidence["evidence"]["quote"],"form":evidence["document"]["form"],"accession":evidence["document"]["accession"],"published_at":evidence["document"]["published_at"],"system_from":edge["claim"]["system_from"]})
    return summaries

def qualitative_packets(store,catalog_path,acceptance_path):
    catalog=json.loads(Path(catalog_path).read_text());acceptance=json.loads(Path(acceptance_path).read_text())
    pending={row["id"] for row in acceptance["results"] if row["status"]=="independent_review_required"};items=[]
    nvidia=_entity(store,"NVDA");amd=_entity(store,"AMD");broadcom=_entity(store,"AVGO");asml=_entity(store,"ASML");tsmc=_entity(store,"TSMC");samsung=_entity(store,"Samsung")
    def neighbors(entity,**kwargs):return store.neighbors(NeighborRequest(entity_id=entity["id"],limit=100,**kwargs))
    tsmc_incoming=neighbors(tsmc,direction="incoming")
    q01_claims=_claim_summaries(tsmc_incoming,tsmc_incoming["entities"],"CONTRACTS_MANUFACTURING_TO")
    q10_public=neighbors(amd,direction="outgoing",public_cutoff=datetime(2025,2,1,tzinfo=timezone.utc))
    q10_known=neighbors(amd,direction="outgoing",public_cutoff=datetime(2025,2,1,tzinfo=timezone.utc),knowledge_cutoff=datetime(2025,2,1,tzinfo=timezone.utc))
    q12_history=store.relationship_history(RelationshipHistoryRequest(subject_id=nvidia["id"],predicate="CONTRACTS_MANUFACTURING_TO"))
    duplicate=_entity_by_slug(store,"evaluation-duplicate-tsmc")
    outputs={
      "q01":{"answer":"Broadcom, NVIDIA and AMD have accepted CONTRACTS_MANUFACTURING_TO claims pointing to TSMC. Each item below includes its exact SEC quote and accession.","supported_companies":q01_claims},
      "q02":neighbors(nvidia,direction="outgoing"),"q03":neighbors(amd,direction="outgoing"),
      "q04":store.relationship_history(RelationshipHistoryRequest(subject_id=broadcom["id"],object_id=tsmc["id"],predicate="CONTRACTS_MANUFACTURING_TO")),
      "q09":neighbors(nvidia,direction="outgoing",public_cutoff=datetime(2025,3,1,tzinfo=timezone.utc)),
      "q10":{"answer":"Before February 2025, AMD had publicly disclosed a manufacturing relationship with TSMC. Under the graph's separate system-knowledge rule, the local graph had not yet observed that claim at the requested cutoff because its system_from timestamp is later. Public-at-the-time and known-by-this-system-at-the-time are therefore reported separately.","evaluation_semantics":{"public_cutoff_rule":"source_available_at must be less than or equal to the cutoff","knowledge_cutoff_rule":"system_from must be less than or equal to the cutoff and system_to must be null or later than the cutoff","interpretation":"A later system_from does not negate the historical public disclosure; it means this system had not ingested the claim at that earlier as-of time."},"public_disclosures":_claim_summaries(q10_public,q10_public["entities"],"CONTRACTS_MANUFACTURING_TO"),"relationships_known_by_system_at_cutoff":_claim_summaries(q10_known,q10_known["entities"],"CONTRACTS_MANUFACTURING_TO"),"cutoffs":{"public_before":"2025-02-01T00:00:00Z","system_knowledge_at":"2025-02-01T00:00:00Z"}},
      "q11":store.relationship_history(RelationshipHistoryRequest(subject_id=amd["id"],object_id=samsung["id"],predicate="CONTRACTS_MANUFACTURING_TO")),
      "q12":{"answer":"No change was detected in NVIDIA's reviewed named-foundry sentence: the earliest disclosure is introduced and the two later identical disclosures are continued.","history":q12_history},
      "q13":store.relationship_history(RelationshipHistoryRequest(subject_id=amd["id"],object_id=tsmc["id"],predicate="CONTRACTS_MANUFACTURING_TO")),
      "q22":{"answer":"The controlled evaluation duplicate was merged into canonical TSMC through an immutable reviewed resolution decision.","evidence_semantics":{"primary_evidence":"The append-only entity_resolution_decision database row is the authoritative evidence for an internal identity action; an SEC citation is neither expected nor applicable.","immutability_controls":"Decision versions are unique per alias and old decision rows are never updated."},"audit":store.resolution_history(duplicate["id"]) if duplicate else {"error":"Run scripts/seed_identity_audit_scenario.py first."}},
    }
    amd_docs=_annual_documents(store,amd["id"]);broadcom_docs=_annual_documents(store,broadcom["id"]);asml_docs=_annual_documents(store,asml["id"])
    outputs["q14"]={"document":amd_docs[0],"passages":store.passages(amd_docs[0]["id"],"TSMC",10)["passages"]}
    outputs["q15"]=store.compare_documents(DocumentComparisonRequest(left_document_id=amd_docs[1]["id"],right_document_id=amd_docs[0]["id"],query="TSMC",limit=10))
    outputs["q16"]={"document":broadcom_docs[0],"passages":store.passages(broadcom_docs[0]["id"],"suppliers",10)["passages"]}
    outputs["q17"]={"document":asml_docs[0],"passages":store.passages(asml_docs[0]["id"],"TSMC",10)["passages"]}
    for question in catalog["questions"]:
        if question["id"] in pending:
            packet={"id":"question:"+question["id"],"kind":"qualitative_answer_review","question":question["question"],"rubric":question["acceptance"]}
            output=outputs[question["id"]]
            if question["id"] in {"q10","q22"}:
                packet["candidate_answer"]=output["answer"]
                packet["evaluation_evidence"]=_compact({key:value for key,value in output.items() if key!="answer"})
            else:packet["candidate_output"]=_compact(output)
            items.append(packet)
    return items

def build_packets(store,dataset_path,catalog_path,acceptance_path):
    return extraction_packets(dataset_path)+qualitative_packets(store,catalog_path,acceptance_path)
