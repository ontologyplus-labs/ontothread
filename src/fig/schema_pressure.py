"""Detect recurring corpus concepts that the active ontology cannot represent directly."""
import json
import re

PATTERNS=(
    {"concept_name":"PROVIDES_ADVANCED_PACKAGING","change_type":"add_predicate","phrases":("advanced packaging","packaging services"),"definition":"A company explicitly provides advanced semiconductor packaging technology or services."},
    {"concept_name":"CAPACITY_CONSTRAINT","change_type":"add_qualifier","phrases":("capacity constraint","capacity constraints","capacity limitation"),"definition":"A source-stated capacity limitation qualifying a relationship or event."},
    {"concept_name":"CHIPLET","change_type":"add_entity_kind","phrases":("chiplet","chiplets"),"definition":"A modular semiconductor die combined with other dies in an integrated package."},
    {"concept_name":"HIGH_NA_EUV","change_type":"add_entity_kind","phrases":("High NA EUV","High-NA EUV"),"definition":"High numerical-aperture extreme-ultraviolet lithography technology or systems."},
)

def detect_schema_pressure(store,min_documents=2,example_limit=5):
    versions=store.ontology_versions()["versions"];active=versions[-1]["definitions"];known=set(active.get("entities",[]))|set(active.get("predicates",{}))|set(active.get("qualifiers",{}))
    documents=[];offset=0
    while True:
        page=store.documents(100,offset);documents.extend(page["documents"])
        if not page["truncated"]:break
        offset=page["next_offset"]
    results=[]
    for pattern in PATTERNS:
        examples=[];matched_documents=set();issuers=set();periods=set();source_families=set();signatures=set()
        for document in documents:
            for phrase in pattern["phrases"]:
                for passage in store.passages(document["id"],phrase,example_limit)["passages"]:
                    matched_documents.add(document["id"])
                    issuers.add(document["issuer_id"]);periods.add(document.get("reporting_period") or document["published_at"][:4]);source_families.add(document["source"])
                    signatures.add(re.sub(r"\s+"," ",passage["text"]).strip().casefold())
                    if len(examples)<example_limit:
                        examples.append({"passage_id":passage["id"],"document_id":document["id"],"issuer_id":document["issuer_id"],"form":document["form"],"published_at":document["published_at"],"phrase":phrase,"text":passage["text"]})
                if document["id"] in matched_documents:break
        count=len(matched_documents)
        if count>=min_documents:
            results.append({**pattern,"document_recurrence":count,"issuer_recurrence":len(issuers),"reporting_period_recurrence":len(periods),
                            "source_family_recurrence":len(source_families),"distinct_text_signatures":len(signatures),"evidence_examples":examples,"already_represented":pattern["concept_name"] in known,
                            "recommendation":"review_existing" if pattern["concept_name"] in known else "propose_for_review","detection_sources":["curated_phrase_baseline"]})
    # Extraction/schema failures are first-class pressure observations. They avoid the
    # circular failure mode where an ontology-bounded extractor silently drops facts.
    grouped={}
    for discovery in store.schema_discoveries("all")["discoveries"]:
        if not discovery.get("concept_name") or not discovery.get("proposed_change_type"):continue
        passage=store.passage(discovery["passage_id"]);document=passage["document"]
        key=(discovery["concept_name"],discovery["proposed_change_type"]);item=grouped.setdefault(key,{"documents":set(),"issuers":set(),"periods":set(),"families":set(),"signatures":set(),"examples":[],"schemas":[]})
        item["documents"].add(document["id"]);item["issuers"].add(document["issuer_id"]);item["periods"].add(document.get("reporting_period") or document["published_at"][:4]);item["families"].add(document["source"])
        item["signatures"].add(re.sub(r"\s+"," ",discovery["exact_quote"]).strip().casefold());item["schemas"].append(discovery.get("proposed_schema",{}))
        if len(item["examples"])<example_limit:item["examples"].append({"passage_id":discovery["passage_id"],"document_id":document["id"],"issuer_id":document["issuer_id"],"form":document["form"],"published_at":document["published_at"],"phrase":None,"text":discovery["exact_quote"],"discovery_id":discovery["id"]})
    by_concept={item["concept_name"]:item for item in results}
    for (concept,change_type),item in grouped.items():
        count=len(item["documents"])
        if count<min_documents:continue
        existing=by_concept.get(concept)
        if existing:
            existing["detection_sources"].append("schema_discovery")
            existing["discovery_document_recurrence"]=count
            existing["discovery_examples"]=item["examples"]
        else:
            schemas={json.dumps(value,sort_keys=True) for value in item["schemas"]}
            candidate={"concept_name":concept,"change_type":change_type,"phrases":[],"definition":"Definition requires ontology review of the preserved schema discoveries.",
                "document_recurrence":count,"issuer_recurrence":len(item["issuers"]),"reporting_period_recurrence":len(item["periods"]),"source_family_recurrence":len(item["families"]),
                "distinct_text_signatures":len(item["signatures"]),"evidence_examples":item["examples"],"already_represented":concept in known,
                "recommendation":"review_existing" if concept in known else "propose_for_review","detection_sources":["schema_discovery"],"schema_variant_count":len(schemas)}
            results.append(candidate);by_concept[concept]=candidate
    return {"active_ontology_version":versions[-1]["version"],"minimum_documents":min_documents,"signals":sorted(results,key=lambda item:(-item["document_recurrence"],item["concept_name"])),
            "documents_examined":len(documents),"corpus_truncated":False,
            "method":"preserved extraction/schema failures plus a curated phrase baseline across the complete local manifest; recurrence dimensions expose repeated boilerplate","automatic_mutation":False}
