"""Explicit local review import, not an automated fact extractor."""
import json
from datetime import datetime,timezone
from hashlib import sha256
from uuid import UUID,uuid5,NAMESPACE_URL
from pydantic import BaseModel,ConfigDict,Field
from fig.contracts import Entity,Document,TextVersion,Passage,ClaimRevision,Evidence,ReviewedBundle

class ReviewInput(BaseModel):
    model_config=ConfigDict(extra="forbid")
    passage_id: UUID
    counterparty: Entity
    subject_is_issuer: bool=True
    predicate: str
    quote: str=Field(min_length=1)
    reviewer: str=Field(min_length=1)

def prepare_review(store,conn,review: ReviewInput,*,reuse_prior=False):
    row=store.execute(conn,"SELECT p.payload AS passage,t.payload AS text_version,d.payload AS document,e.payload AS issuer FROM passage p JOIN text_version t ON t.id=p.text_version_id JOIN document d ON d.id=t.document_id JOIN entity e ON e.id=d.issuer_id WHERE p.id=?",(str(review.passage_id),)).fetchone()
    if not row:
        raise ValueError("Reviewed passage was not ingested")
    passage=Passage.model_validate_json(row["passage"])
    version=TextVersion.model_validate_json(row["text_version"])
    document=Document.model_validate_json(row["document"])
    issuer=Entity.model_validate_json(row["issuer"])
    text=version.normalized_text[passage.start_offset:passage.end_offset]
    if text.count(review.quote)!=1:
        raise ValueError("Review quote must occur exactly once in the selected passage")
    start=passage.start_offset+text.index(review.quote)
    subject=issuer if review.subject_is_issuer else review.counterparty
    obj=review.counterparty if review.subject_is_issuer else issuer
    key=f"fig:review:{passage.id}:{subject.id}:{review.predicate}:{obj.id}:{sha256(review.quote.encode()).hexdigest()}"
    claim_id=uuid5(NAMESPACE_URL,key)
    revision_id=uuid5(NAMESPACE_URL,key+":revision:1")
    prior=store.execute(conn,"SELECT payload FROM claim_revision WHERE id=?",(str(revision_id),)).fetchone()
    if prior:
        claim=ClaimRevision.model_validate_json(prior["payload"])
        if claim.reviewer!=review.reviewer and not reuse_prior:
            raise ValueError("An existing review cannot be silently attributed to a different reviewer")
    else:
        claim=ClaimRevision(id=revision_id,claim_id=claim_id,subject_id=subject.id,object_id=obj.id,predicate=review.predicate,assertion_class="normalized_explicit",review_state="accepted",reviewer=review.reviewer,source_available_at=document.published_at,system_from=datetime.now(timezone.utc))
    evidence=Evidence(id=uuid5(NAMESPACE_URL,key+":evidence"),claim_revision_id=claim.id,passage_id=passage.id,quote=review.quote,start_offset=start,end_offset=start+len(review.quote),assessment="supported")
    bundle=ReviewedBundle(entities=[issuer,review.counterparty],document=document,text_version=version,passage=passage,claim=claim,evidence=evidence)
    return bundle

def import_review(store,archive_dir,review: ReviewInput):
    with store.connect() as conn:
        bundle=prepare_review(store,conn,review)
    original=(archive_dir/bundle.document.content_hash).read_bytes()
    return store.ingest(bundle,original,archive_dir)
