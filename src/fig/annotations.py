"""Strict, non-mutating validation and agreement for independent review CSVs."""
import csv
import json
from pathlib import Path

VERDICTS={"agree","correct","uncertain"}
RELATION_VERDICTS={"supported","unsupported","ambiguous"}
QA_STATUSES={"supported","unsupported","ambiguous","incomplete"}
ONTOLOGY_DISPOSITIONS={"existing_concept","synonym_merge","subtype","qualifier","new_predicate","new_entity_kind","unsupported","defer"}

def _rows(path):
    with Path(path).open(newline="",encoding="utf-8") as handle:return list(csv.DictReader(handle))


def load_review(path):
    rows=_rows(path)
    if not rows:raise ValueError("review file is empty")
    if len({row["case_id"] for row in rows})!=len(rows):raise ValueError("review case IDs must be unique")
    errors=[];completed=0
    for row in rows:
        verdict=row.get("independent_verdict","").strip()
        if not verdict:continue
        completed+=1
        if verdict not in VERDICTS:errors.append({"case_id":row["case_id"],"error":"invalid verdict"});continue
        correction=row.get("corrected_relationships","").strip()
        if verdict=="correct":
            try:
                parsed=json.loads(correction)
                if not isinstance(parsed,list):raise ValueError
            except (json.JSONDecodeError,ValueError):errors.append({"case_id":row["case_id"],"error":"correct verdict requires a JSON relationship list"})
        elif correction:errors.append({"case_id":row["case_id"],"error":"corrected relationships are only allowed for correct verdicts"})
    return {"rows":rows,"case_count":len(rows),"completed_count":completed,"complete":completed==len(rows) and not errors,"errors":errors}

def load_prospective_relation_review(path):
    rows=_rows(path);errors=[];completed=0
    if not rows:raise ValueError("relation review file is empty")
    for row in rows:
        verdict=row.get("relation_verdict","").strip();disposition=row.get("ontology_disposition","").strip()
        if not verdict:continue
        completed+=1
        if verdict not in RELATION_VERDICTS:errors.append({"packet_id":row["packet_id"],"error":"invalid relation verdict"})
        try:relationships=json.loads(row.get("relationships_json","") or "[]")
        except json.JSONDecodeError:relationships=None;errors.append({"packet_id":row["packet_id"],"error":"relationships_json is invalid"})
        if verdict=="supported" and (not isinstance(relationships,list) or not relationships):errors.append({"packet_id":row["packet_id"],"error":"supported verdict requires a nonempty JSON relationship list"})
        if verdict=="unsupported" and relationships:errors.append({"packet_id":row["packet_id"],"error":"unsupported verdict must have no relationships"})
        if disposition and disposition not in ONTOLOGY_DISPOSITIONS:errors.append({"packet_id":row["packet_id"],"error":"invalid ontology disposition"})
    return {"rows":rows,"case_count":len(rows),"completed_count":completed,"complete":completed==len(rows) and not errors,"errors":errors}

def load_prospective_qa_review(path):
    rows=_rows(path);errors=[];completed=0
    if not rows:raise ValueError("QA review file is empty")
    for row in rows:
        status=row.get("answer_status","").strip()
        if not status:continue
        completed+=1
        if status not in QA_STATUSES:errors.append({"question_id":row["question_id"],"error":"invalid answer status"})
        for field in ("answer_claims_json","valid_paths_json","citation_passage_ids_json"):
            try:value=json.loads(row.get(field,"") or "[]")
            except json.JSONDecodeError:value=None;errors.append({"question_id":row["question_id"],"error":field+" is invalid"})
            if value is not None and not isinstance(value,list):errors.append({"question_id":row["question_id"],"error":field+" must be a JSON list"})
    return {"rows":rows,"case_count":len(rows),"completed_count":completed,"complete":completed==len(rows) and not errors,"errors":errors}


def agreement(first_path,second_path):
    first=load_review(first_path);second=load_review(second_path)
    a={row["case_id"]:row["independent_verdict"].strip() for row in first["rows"] if row["independent_verdict"].strip()}
    b={row["case_id"]:row["independent_verdict"].strip() for row in second["rows"] if row["independent_verdict"].strip()}
    common=sorted(set(a)&set(b));labels=sorted(VERDICTS)
    if not common:return {"double_annotated":0,"percent_agreement":None,"cohen_kappa":None}
    observed=sum(a[key]==b[key] for key in common)/len(common)
    expected=sum((sum(a[key]==label for key in common)/len(common))*(sum(b[key]==label for key in common)/len(common)) for label in labels)
    kappa=(observed-expected)/(1-expected) if expected<1 else (1.0 if observed==1 else None)
    return {"double_annotated":len(common),"percent_agreement":observed,"cohen_kappa":kappa,
            "disagreements":[key for key in common if a[key]!=b[key]],"labels":labels}
