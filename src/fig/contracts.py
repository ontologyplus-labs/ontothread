from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
from typing import Any, Literal
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, field_serializer, model_validator

SEED_ONTOLOGY = yaml.safe_load(files("fig").joinpath("resources/finance-v1.yaml").read_text())
ONTOLOGY = yaml.safe_load(files("fig").joinpath("resources/finance-v2.yaml").read_text())

class Record(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: UUID

class TimedRecord(Record):
    @field_serializer("*", when_used="json")
    def canonical_dates(self, value):
        if isinstance(value, datetime):
            return value.isoformat(timespec="microseconds").replace("+00:00", "Z")
        return value

    @field_validator("*", mode="after")
    @classmethod
    def utc_dates(cls, value):
        if isinstance(value, datetime):
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("timestamps require a timezone")
            return value.astimezone(timezone.utc)
        return value

class Entity(Record):
    kind: Literal["Company","Person","Security","Product","Technology","Industry","Geography","FinancialMetric","Guidance","Risk","Event","Document","Claim"]
    canonical_name: str
    slug: str
    status: Literal["reviewed", "provisional"] = "reviewed"

class EntityResolutionDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["merge", "split"]
    canonical_entity_id: UUID | None = None
    expected_version: int = Field(ge=0)
    reviewer: str = Field(min_length=1,max_length=120)
    notes: str = Field(min_length=1,max_length=2000)

    @model_validator(mode="after")
    def target_matches_action(self):
        if self.action=="merge" and self.canonical_entity_id is None:
            raise ValueError("Merge requires a canonical entity ID")
        if self.action=="split" and self.canonical_entity_id is not None:
            raise ValueError("Split does not accept a canonical entity ID")
        return self

class OntologyProposalCreate(BaseModel):
    """A reviewable claim that the current schema cannot represent a recurring fact."""
    model_config = ConfigDict(extra="forbid")
    change_type: Literal["add_entity_kind", "add_predicate", "add_qualifier"]
    concept_name: str = Field(min_length=2, max_length=120)
    definition: str = Field(min_length=10, max_length=2000)
    rationale: str = Field(min_length=10, max_length=4000)
    proposed_schema: dict[str, Any]
    evidence_passage_ids: list[UUID] = Field(min_length=1, max_length=100)
    recurrence_count: int = Field(ge=1)
    base_ontology_version: str = Field(min_length=1, max_length=120)
    proposer: str = Field(min_length=1, max_length=120)

    @field_validator("concept_name")
    @classmethod
    def normalized_concept_name(cls, value):
        value=value.strip()
        if not value or any(character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for character in value):
            raise ValueError("concept_name must use uppercase letters, digits and underscores")
        return value

    @field_validator("evidence_passage_ids")
    @classmethod
    def distinct_evidence(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("evidence passages must be unique")
        return value

class SchemaDiscoveryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passage_id: UUID
    failure_type: Literal["missing_predicate","missing_entity_kind","qualifier_required","unresolved_identity","insufficient_context","unsupported_assertion"]
    concept_name: str | None = Field(default=None,max_length=120)
    proposed_change_type: Literal["add_predicate","add_entity_kind","add_qualifier"] | None = None
    exact_quote: str = Field(min_length=1,max_length=16000)
    rationale: str = Field(min_length=10,max_length=4000)
    proposed_schema: dict[str,Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def proposed_fields(self):
        if self.failure_type in {"missing_predicate","missing_entity_kind","qualifier_required"} and (not self.concept_name or not self.proposed_change_type):
            raise ValueError("schema discoveries require a concept name and proposed change type")
        return self

class ClaimLifecycleDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["supersede","retract","correct","retain_conflict"]
    reviewer: str = Field(min_length=1,max_length=120)
    notes: str = Field(min_length=1,max_length=4000)
    claim_revision_id: UUID | None = None
    conflicting_claim_revision_id: UUID | None = None

class OntologyProposalDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "merge", "reject", "defer"]
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1, max_length=120)
    notes: str = Field(min_length=1, max_length=4000)
    merge_target: str | None = Field(default=None, max_length=120)
    migration_notes: str | None = Field(default=None, max_length=4000)

    @model_validator(mode="after")
    def action_fields(self):
        if self.action == "merge" and not self.merge_target:
            raise ValueError("Merge requires an existing ontology concept")
        if self.action != "merge" and self.merge_target is not None:
            raise ValueError("merge_target is only valid for merge decisions")
        if self.action == "accept" and not self.migration_notes:
            raise ValueError("Accepted changes require migration notes")
        return self

class OntologyProposalRebase(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)
    target_ontology_version: str = Field(min_length=1,max_length=120)
    reviewer: str = Field(min_length=1,max_length=120)
    notes: str = Field(min_length=10,max_length=4000)

class Document(TimedRecord):
    issuer_id: UUID
    source: Literal["synthetic_fixture", "sec"]
    source_url: str
    accession: str
    filename: str
    form: str
    published_at: datetime
    acquired_at: datetime
    content_hash: str
    publication_precision: Literal["timestamp", "date"] = "timestamp"
    publication_basis: str = "source_timestamp"
    reporting_period: str | None = None

class TextVersion(Record):
    document_id: UUID
    parser_version: str
    normalized_hash: str
    normalized_text: str

class Passage(Record):
    text_version_id: UUID
    section_path: str
    start_offset: int
    end_offset: int

class ClaimRevision(TimedRecord):
    claim_id: UUID
    revision: int = 1
    subject_id: UUID
    object_id: UUID
    predicate: str
    assertion_class: Literal["explicit", "normalized_explicit", "inferred"] = "explicit"
    polarity: Literal["positive", "negative"] = "positive"
    review_state: Literal["pending", "accepted", "rejected", "superseded"] = "pending"
    source_available_at: datetime
    system_from: datetime
    system_to: datetime | None = None
    valid_from: datetime | None = None
    valid_to: datetime | None = None
    reviewer: str | None = None

    @model_validator(mode="after")
    def intervals(self):
        if self.revision < 1:
            raise ValueError("revision must be positive")
        for start, end in ((self.system_from, self.system_to), (self.valid_from, self.valid_to)):
            if start and end and end <= start:
                raise ValueError("interval must be nonempty and increasing")
        if self.system_from < self.source_available_at:
            raise ValueError("system observation cannot predate source availability")
        if self.review_state == "accepted" and not self.reviewer:
            raise ValueError("accepted pilot claims require a reviewer")
        return self

class Evidence(Record):
    claim_revision_id: UUID
    passage_id: UUID
    quote: str
    start_offset: int
    end_offset: int
    assessment: Literal["supported", "partial", "unsupported", "contradictory"]

class ReviewedBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    ontology_version: str = "finance-v2"
    ontology_schema_hash: str | None = None
    entities: list[Entity]
    document: Document
    text_version: TextVersion
    passage: Passage
    claim: ClaimRevision
    evidence: Evidence

    @model_validator(mode="after")
    def integrity(self):
        entities = {e.id: e for e in self.entities}
        if len(entities) != len(self.entities):
            raise ValueError("duplicate entity IDs")
        d, t, p, c, e = self.document, self.text_version, self.passage, self.claim, self.evidence
        if d.issuer_id not in entities or t.document_id != d.id or p.text_version_id != t.id:
            raise ValueError("broken document lineage")
        if c.subject_id not in entities or c.object_id not in entities:
            raise ValueError("unresolved claim endpoints")
        packaged={SEED_ONTOLOGY["version"]:SEED_ONTOLOGY,ONTOLOGY["version"]:ONTOLOGY}.get(self.ontology_version)
        if packaged:
            rule = packaged["predicates"].get(c.predicate)
            if not rule or entities[c.subject_id].kind not in rule["subject"] or entities[c.object_id].kind not in rule["object"]:
                raise ValueError("predicate violates ontology")
        if e.claim_revision_id != c.id or e.passage_id != p.id:
            raise ValueError("broken evidence lineage")
        if not 0 <= p.start_offset < p.end_offset <= len(t.normalized_text):
            raise ValueError("invalid passage offsets")
        if not p.start_offset <= e.start_offset < e.end_offset <= p.end_offset:
            raise ValueError("evidence must lie inside passage")
        if t.normalized_text[e.start_offset:e.end_offset] != e.quote:
            raise ValueError("evidence quote does not match normalized text")
        if sha256(t.normalized_text.encode()).hexdigest() != t.normalized_hash:
            raise ValueError("normalized text hash mismatch")
        if c.source_available_at != d.published_at:
            raise ValueError("pilot claim availability must match its evidence document")
        if d.acquired_at < d.published_at or c.system_from < d.acquired_at:
            raise ValueError("invalid acquisition or system timestamp")
        if c.review_state == "accepted":
            if e.assessment != "supported" or any(entities[x].status != "reviewed" for x in (c.subject_id,c.object_id)):
                raise ValueError("accepted claims require supported evidence and reviewed entities")
        return self

class NeighborRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    direction: Literal["both", "outgoing", "incoming"] = "both"
    public_cutoff: datetime | None = None
    knowledge_cutoff: datetime | None = None
    effective_at: datetime | None = None
    ontology_version: str | None = Field(default=None,min_length=1,max_length=120)
    identity_cutoff: datetime | None = None
    limit: int = 20

    @field_validator("public_cutoff", "knowledge_cutoff", "effective_at", "identity_cutoff")
    @classmethod
    def utc(cls, value):
        if value and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("cutoffs require a timezone")
        return value.astimezone(timezone.utc) if value else None

    @field_validator("limit")
    @classmethod
    def bounded(cls, value):
        if not 1 <= value <= 100:
            raise ValueError("limit must be between 1 and 100")
        return value

class PathRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_entity_id: UUID
    target_entity_id: UUID | None = None
    direction: Literal["both", "outgoing", "incoming"] = "both"
    min_hops: int = Field(default=1, ge=1, le=3)
    max_hops: int = Field(default=3, ge=1, le=3)
    predicates: list[str] = Field(default_factory=list, max_length=20)
    public_cutoff: datetime | None = None
    knowledge_cutoff: datetime | None = None
    effective_at: datetime | None = None
    ontology_version: str | None = Field(default=None,min_length=1,max_length=120)
    identity_cutoff: datetime | None = None
    limit: int = Field(default=20, ge=1, le=100)

    @field_validator("public_cutoff", "knowledge_cutoff", "effective_at", "identity_cutoff")
    @classmethod
    def utc(cls, value):
        if value and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("cutoffs require a timezone")
        return value.astimezone(timezone.utc) if value else None

    @field_validator("predicates")
    @classmethod
    def distinct_predicates(cls, value):
        if len(set(value)) != len(value):
            raise ValueError("predicates must be unique")
        return value

    @model_validator(mode="after")
    def hop_range(self):
        if self.min_hops > self.max_hops:
            raise ValueError("min_hops cannot exceed max_hops")
        if self.target_entity_id == self.source_entity_id:
            raise ValueError("source and target entities must differ")
        return self

class DocumentComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    left_document_id: UUID
    right_document_id: UUID
    query: str = Field(min_length=2,max_length=200)
    limit: int = Field(default=10,ge=1,le=20)

    @field_validator("query")
    @classmethod
    def meaningful_query(cls,value):
        value=value.strip()
        if len(value)<2:raise ValueError("query must contain at least two non-space characters")
        return value

    @model_validator(mode="after")
    def distinct_documents(self):
        if self.left_document_id==self.right_document_id:raise ValueError("comparison documents must differ")
        return self

class RelationshipHistoryRequest(BaseModel):
    """Retrieve source-reviewed disclosures for one canonical relationship."""
    model_config = ConfigDict(extra="forbid")
    subject_id: UUID
    object_id: UUID | None = None
    predicate: str | None = Field(default=None,min_length=1,max_length=120)

class ResearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=5,max_length=1000)
    max_hops: int = Field(default=3,ge=1,le=3)
    public_cutoff: datetime | None = None
    knowledge_cutoff: datetime | None = None
    effective_at: datetime | None = None
    ontology_version: str | None = Field(default=None,min_length=1,max_length=120)
    identity_cutoff: datetime | None = None
    limit: int = Field(default=20,ge=1,le=50)

    @field_validator("question")
    @classmethod
    def normalized_question(cls,value):
        value=" ".join(value.split())
        if len(value)<5:raise ValueError("question is too short")
        return value

    @field_validator("public_cutoff","knowledge_cutoff","effective_at","identity_cutoff")
    @classmethod
    def research_utc(cls,value):
        if value and (value.tzinfo is None or value.utcoffset() is None):raise ValueError("cutoffs require a timezone")
        return value.astimezone(timezone.utc) if value else None

class PassageAnalysisRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    passage_ids: list[UUID] = Field(min_length=1,max_length=20)

    @field_validator("passage_ids")
    @classmethod
    def unique_passages(cls,value):
        if len(set(value)) != len(value):raise ValueError("passage IDs must be unique")
        return value

class HybridRetrievalRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    query: str = Field(min_length=3,max_length=500)
    document_limit: int = Field(default=20,ge=1,le=100)
    passage_limit: int = Field(default=10,ge=1,le=50)
    graph_limit: int = Field(default=10,ge=1,le=25)
    use_embeddings: bool = False
    public_cutoff: datetime | None = None
    knowledge_cutoff: datetime | None = None
    effective_at: datetime | None = None
    ontology_version: str | None = Field(default=None,min_length=1,max_length=120)
    identity_cutoff: datetime | None = None

    @field_validator("query")
    @classmethod
    def normalize_retrieval_query(cls,value):
        value=" ".join(value.split())
        if len(value)<3:raise ValueError("query is too short")
        return value

    @field_validator("public_cutoff","knowledge_cutoff","effective_at","identity_cutoff")
    @classmethod
    def retrieval_utc(cls,value):
        if value and (value.tzinfo is None or value.utcoffset() is None):raise ValueError("cutoffs require a timezone")
        return value.astimezone(timezone.utc) if value else None

class EntityMention(BaseModel):
    model_config = ConfigDict(extra="forbid")
    entity_id: UUID
    canonical_name: str
    kind: Literal["Company","Product","Technology"]
    matched_text: str
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    method: Literal["canonical","alias","identifier"]

class EventCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["GUIDANCE_CHANGE","ACQUISITION","INVESTMENT","RISK_CHANGE"]
    company_id: UUID
    direction: Literal["increase","decrease","unchanged","not_applicable"]
    evidence_span: str = Field(min_length=1,max_length=4000)
    start_offset: int = Field(ge=0)
    end_offset: int = Field(gt=0)
    effective_date: str | None = None
    confidence: float = Field(ge=0,le=1)
    review_state: Literal["candidate"] = "candidate"

class EventReviewDecision(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept","reject"]
    expected_version: int = Field(ge=1)
    reviewer: str = Field(min_length=1,max_length=120)
    notes: str = Field(min_length=1,max_length=2000)



def eligible(claim: ClaimRevision, request: NeighborRequest) -> bool:
    if claim.review_state != "accepted" or claim.assertion_class == "inferred" or claim.polarity != "positive":
        return False
    if request.public_cutoff and claim.source_available_at > request.public_cutoff:
        return False
    if request.knowledge_cutoff:
        if claim.system_from > request.knowledge_cutoff or (claim.system_to and request.knowledge_cutoff >= claim.system_to):
            return False
    elif claim.system_to is not None:
        return False
    if request.effective_at:
        if claim.valid_from is None or request.effective_at < claim.valid_from:
            return False
        if claim.valid_to and request.effective_at >= claim.valid_to:
            return False
    return True


class SourceBundle(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: Entity
    document: Document
    text_version: TextVersion
    passages: list[Passage]
    quality_flags: list[str]

    @model_validator(mode="after")
    def source_integrity(self):
        d,t=self.document,self.text_version
        if self.issuer.id!=d.issuer_id or t.document_id!=d.id:
            raise ValueError("broken document lineage")
        if d.acquired_at<d.published_at:
            raise ValueError("publication cutoff exceeds acquisition time")
        if sha256(t.normalized_text.encode()).hexdigest()!=t.normalized_hash:
            raise ValueError("normalized hash mismatch")
        if not self.passages or len({p.id for p in self.passages})!=len(self.passages):
            raise ValueError("passages must be nonempty with unique IDs")
        previous=0
        for p in self.passages:
            if p.text_version_id!=t.id or not previous<=p.start_offset<p.end_offset<=len(t.normalized_text):
                raise ValueError("invalid passage lineage or offsets")
            previous=p.end_offset
        return self
