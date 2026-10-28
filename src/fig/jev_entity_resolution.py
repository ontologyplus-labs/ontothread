"""Jev shadow ranking over deterministic entity-resolution candidates."""
import json
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from fig.jev_shadow import JevDecisionClient


POLICY_VERSION = "entity-resolution-shadow-v1"
NEW_ENTITY = "new_entity"
INSUFFICIENT = "insufficient_information"


class EntityShadowDecision(BaseModel):
    selection: str
    selection_probabilities: dict[str, float]
    confidence: float | None
    same_entity_probability: float
    human_review_probability: float
    shadow_only: Literal[True] = True
    automatic_merge_allowed: Literal[False] = False


def _questions(candidates: list[dict[str, Any]]):
    criteria = {
        item["entity"]["id"]: {
            "canonical_name": item["entity"]["canonical_name"],
            "kind": item["entity"]["kind"],
            "deterministic_similarity": item["score"],
        }
        for item in candidates
    }
    criteria[NEW_ENTITY] = "The mention refers to a real entity absent from the candidate list."
    criteria[INSUFFICIENT] = "The supplied mention and context cannot reliably identify an entity."
    return {
        "canonical_entity": {
            "type": "choice",
            "instructions": (
                "Choose the canonical entity explicitly referred to by the mention in context. "
                "Use only the supplied candidates. Choose new_entity if clearly absent, or "
                "insufficient_information when ambiguous. Similar spelling alone is not proof."
            ),
            "criteria": criteria,
        },
        "same_entity": {
            "type": "noul",
            "instructions": "Does the best listed candidate refer to the same real-world entity as the mention in context?",
            "criteria": {"true": "The identity match is supported.", "false": "It is a different entity or cannot be established."},
        },
        "requires_human_review": {
            "type": "noul",
            "instructions": "Should a person review this identity decision because it is ambiguous or consequential?",
            "criteria": {"true": "Human identity review is required.", "false": "The bounded ranking is clear enough for shadow analysis."},
        },
    }


class JevEntityResolver:
    def __init__(self, client=None):
        self.client = client or JevDecisionClient()
        self.model = self.client.model
        self.endpoint = self.client.endpoint

    def rank(self, mention, context, deterministic_result):
        candidates = deterministic_result["candidates"]
        if not candidates:
            raise ValueError("Entity shadow ranking requires at least one deterministic candidate")
        questions = _questions(candidates)
        state = {
            "mention": mention,
            "context": context or "No additional source context supplied.",
            "candidate_entities": [
                {"id": row["entity"]["id"], "canonical_name": row["entity"]["canonical_name"],
                 "kind": row["entity"]["kind"], "deterministic_similarity": row["score"]}
                for row in candidates
            ],
            "policy": "Shadow ranking only. Do not merge entities or use outside knowledge.",
        }
        answers, metadata = self.client.ask(state, questions)
        choice = answers["canonical_entity"]
        allowed = set(questions["canonical_entity"]["criteria"])
        if choice.choice not in allowed:
            raise RuntimeError("Jev returned an entity choice outside the supplied candidate set")
        def probability(name):
            value = answers[name].noul
            if value is None or not 0 <= value <= 1:
                raise RuntimeError(f"Jev returned an invalid probability for {name}")
            return value
        return EntityShadowDecision(
            selection=choice.choice,
            selection_probabilities=choice.probabilities,
            confidence=choice.confidence,
            same_entity_probability=probability("same_entity"),
            human_review_probability=probability("requires_human_review"),
        ), metadata, state, questions


def rank_entity_mentions(store, cases, cache_dir, *, resolver=None, limit=10):
    resolver = resolver or JevEntityResolver()
    cache_dir = Path(cache_dir); cache_dir.mkdir(parents=True, exist_ok=True)
    results=[]; request_count=0
    for case in cases:
        mention=case["mention"]; context=case.get("context","")
        deterministic=store.entity_resolution_candidates(mention,limit)
        key=sha256(json.dumps({"case":case,"candidates":deterministic["candidates"],"model":resolver.model,"policy":POLICY_VERSION},sort_keys=True).encode()).hexdigest()
        path=cache_dir/(key+".json"); cached=path.exists()
        if cached:
            record=json.loads(path.read_text());decision=EntityShadowDecision.model_validate(record["decision"]);metadata=record["metadata"]
        else:
            decision,metadata,state,questions=resolver.rank(mention,context,deterministic);request_count+=1
            record={"decision":decision.model_dump(),"metadata":metadata,"state":state,"questions":questions}
            temporary=path.with_suffix(".tmp");temporary.write_text(json.dumps(record,indent=2)+"\n");temporary.replace(path)
        expected=case.get("expected_entity_id")
        results.append({"id":case.get("id",mention),"mention":mention,"expected_entity_id":expected,
                        "matches_expected":decision.selection==expected if expected else None,
                        "deterministic_candidates":deterministic["candidates"],"decision":decision.model_dump(),
                        "metadata":metadata,"cached":cached})
    labelled=[row for row in results if row["expected_entity_id"]]
    return {"generated_at":datetime.now(timezone.utc).isoformat(),"mode":"shadow_evaluation_only","policy_version":POLICY_VERSION,
            "model":resolver.model,"endpoint":resolver.endpoint,"request_count":request_count,"case_count":len(results),
            "labelled_accuracy":sum(row["matches_expected"] for row in labelled)/len(labelled) if labelled else None,
            "results":results,"automatic_merge_allowed":False,
            "interpretation":"Jev ranks a deterministic shortlist only. It does not merge, create, or mutate entities."}
