"""Jev shadow triage for schema-pressure signals and ontology proposals."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Literal

from pydantic import BaseModel

from fig.jev_shadow import JevDecisionClient


POLICY_VERSION = "ontology-triage-shadow-v1"
DISPOSITIONS = {
    "existing_concept": "The active ontology already represents the concept.",
    "synonym_or_merge": "The proposal duplicates or aliases an existing concept.",
    "subtype": "The concept is best represented as a subtype of an existing entity or relation.",
    "qualifier": "The concept should qualify another fact rather than become a standalone predicate or entity kind.",
    "new_predicate": "The evidence supports a distinct relationship type.",
    "new_entity_kind": "The evidence supports a distinct entity category.",
    "unsupported": "The evidence does not support an ontology change.",
    "defer": "More recurrence, evidence, or clarification is needed.",
}


QUESTIONS = {
    "disposition": {
        "type":"choice",
        "instructions":"Classify the proposed concept using the evidence, active ontology and proposed change. Do not approve or mutate the ontology.",
        "criteria":DISPOSITIONS,
    },
    "evidence_quality": {
        "type":"score",
        "instructions":"Score how directly and consistently the supplied examples support a reusable ontology concept.",
        "criteria":["insufficient","weak","mixed","strong","direct and recurrent"],
    },
    "redundant_with_existing": {
        "type":"noul",
        "instructions":"Is this concept semantically redundant with the supplied active ontology?",
        "criteria":{"true":"An existing concept already covers it.","false":"It appears meaningfully distinct."},
    },
    "requires_human_review": {
        "type":"noul",
        "instructions":"Should an ontology reviewer inspect this proposal before any decision?",
        "criteria":{"true":"Human ontology review is required.","false":"The shadow classification is clear, while still non-authoritative."},
    },
}


class OntologyTriageDecision(BaseModel):
    disposition: Literal["existing_concept","synonym_or_merge","subtype","qualifier","new_predicate","new_entity_kind","unsupported","defer"]
    disposition_probabilities: dict[str,float]
    confidence: float|None
    evidence_quality_score: float
    evidence_quality_probabilities: dict[str,float]
    redundancy_probability: float
    human_review_probability: float
    shadow_only: Literal[True]=True
    automatic_ontology_mutation: Literal[False]=False


class JevOntologyTriager:
    def __init__(self,client=None):
        self.client=client or JevDecisionClient();self.model=self.client.model;self.endpoint=self.client.endpoint

    def triage(self,signal,active_ontology):
        state={"proposal":signal,"active_ontology":active_ontology,
               "policy":"Shadow triage only. Use supplied evidence and definitions; do not approve or mutate the ontology."}
        answers,metadata=self.client.ask(state,QUESTIONS);disposition=answers["disposition"]
        if disposition.choice not in DISPOSITIONS:raise RuntimeError("Jev returned an invalid ontology disposition")
        score=answers["evidence_quality"]
        if score.confidence is None and not score.probabilities:raise RuntimeError("Jev returned no ontology evidence-quality signal")
        raw=score.score
        if raw is None:raise RuntimeError("Jev returned no ontology evidence-quality score")
        def probability(name):
            value=answers[name].noul
            if value is None or not 0<=value<=1:raise RuntimeError(f"Jev returned an invalid probability for {name}")
            return value
        return OntologyTriageDecision(disposition=disposition.choice,disposition_probabilities=disposition.probabilities,
            confidence=disposition.confidence,evidence_quality_score=float(raw),evidence_quality_probabilities=score.probabilities,
            redundancy_probability=probability("redundant_with_existing"),human_review_probability=probability("requires_human_review")),metadata,state


def triage_signals(active_ontology,signals,cache_dir,*,triager=None):
    triager=triager or JevOntologyTriager();cache_dir=Path(cache_dir);cache_dir.mkdir(parents=True,exist_ok=True);results=[];request_count=0
    ontology_hash=sha256(json.dumps(active_ontology,sort_keys=True).encode()).hexdigest()
    for signal in signals:
        key=sha256(json.dumps({"signal":signal,"ontology_hash":ontology_hash,"model":triager.model,"policy":POLICY_VERSION},sort_keys=True).encode()).hexdigest()
        path=cache_dir/(key+".json");cached=path.exists()
        if cached:
            record=json.loads(path.read_text());decision=OntologyTriageDecision.model_validate(record["decision"]);metadata=record["metadata"]
        else:
            decision,metadata,state=triager.triage(signal,active_ontology);request_count+=1
            record={"decision":decision.model_dump(),"metadata":metadata,"state":state,"questions":QUESTIONS}
            temporary=path.with_suffix(".tmp");temporary.write_text(json.dumps(record,indent=2)+"\n");temporary.replace(path)
        results.append({"concept_name":signal["concept_name"],"change_type":signal["change_type"],"decision":decision.model_dump(),"metadata":metadata,"cached":cached})
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"shadow_evaluation_only","policy_version":POLICY_VERSION,
            "model":triager.model,"endpoint":triager.endpoint,"ontology_hash":ontology_hash,"request_count":request_count,
            "signal_count":len(results),"results":results,"automatic_ontology_mutation":False,
            "interpretation":"Jev triage is a review-priority signal. Only the existing audited human decision path can change the ontology."}
