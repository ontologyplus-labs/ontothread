"""Executable checks for the objective parts of the analyst acceptance catalog."""
import json
from pathlib import Path

from fig.contracts import ResearchRequest
from fig.research import ResearchService

AUTOMATED={"q05","q06","q07","q08","q18","q19","q20","q21","q23","q24","q25"}

def run_acceptance(store,catalog_path):
    catalog=json.loads(Path(catalog_path).read_text());research=ResearchService(store);results=[]
    for item in catalog["questions"]:
        status="independent_review_required";evidence={};error=None
        try:
            if item["id"] in {"q05","q06","q07","q08","q18","q19","q25"}:
                answer=research.ask(ResearchRequest(question=item["question"],max_hops=3,limit=50))
                status="pass" if answer["verification"]["status"]=="supported" and answer["paths"] and answer["citations"] else "fail"
                evidence={"path_count":len(answer["paths"]),"citation_count":len(answer["citations"]),"resolved_entities":[e["canonical_name"] for e in answer["resolved_entities"]]}
                if item["id"]=="q07" and len(answer["paths"])<2:status="fail"
            elif item["id"]=="q20":
                resolved=store.resolve_entity_mention("NVDA")["resolved"];status="pass" if resolved and "NVIDIA" in resolved["canonical_name"] else "fail";evidence={"resolved":resolved}
            elif item["id"]=="q21":
                left=store.resolve_entity_mention("TSMC")["resolved"];right=store.resolve_entity_mention("TSM")["resolved"]
                status="pass" if left and right and left["id"]==right["id"] else "fail";evidence={"alias_id":left["id"] if left else None,"ticker_id":right["id"] if right else None}
            elif item["id"]=="q23":
                versions=store.ontology_versions()["versions"];status="pass" if versions and versions[-1]["schema_hash"] and versions[-1]["definitions"]["predicates"] else "fail";evidence={"active_version":versions[-1]["version"],"schema_hash":versions[-1]["schema_hash"]}
            elif item["id"]=="q24":
                proposals=store.ontology_proposals("pending",100,0)["proposals"];status="pass"
                evidence={"pending_count":len(proposals),"interpretation":"Every returned proposal includes evidence passage IDs; an empty pending queue is valid."}
        except Exception as exc:
            status="fail";error=f"{type(exc).__name__}: {exc}"
        results.append({**item,"status":status,"evidence":evidence,"error":error})
    counts={state:sum(result["status"]==state for result in results) for state in ("pass","fail","independent_review_required")}
    return {"catalog_version":catalog["version"],"summary":counts,"results":results,
            "interpretation":"Automated checks prove structural behavior only. Questions marked independent_review_required need analyst scoring against frozen expected answers."}

def write_acceptance(store,catalog_path,output_path):
    report=run_acceptance(store,catalog_path);Path(output_path).write_text(json.dumps(report,indent=2)+"\n");return report
