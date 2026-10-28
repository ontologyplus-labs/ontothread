"""Registry-backed entity mentions and narrow, review-only event candidates."""
import json
import re

from fig.contracts import EntityMention,EventCandidate

GUIDANCE=re.compile(
    r"(?P<span>(?:we|the company|[A-Z][A-Za-z0-9&.,-]*(?:\s+[A-Z][A-Za-z0-9&.,-]*){0,4})\s+(?:raised|increased|lowered|reduced|maintained|reaffirmed)"
    r"\s+(?:our\s+)?(?:revenue|earnings|margin|sales|financial)?\s*guidance[^.]{0,300}\.)",re.I)
EVENTS=(
    ("ACQUISITION",re.compile(r"(?P<span>(?:we|the company)\s+(?:acquired|completed the acquisition of)\s+[^.]{2,250}\.)",re.I)),
    ("INVESTMENT",re.compile(r"(?P<span>(?:we|the company)\s+(?:invested in|made an investment in)\s+[^.]{2,250}\.)",re.I)),
)

class PassageAnalyzer:
    def __init__(self,store):self.store=store

    def _registry_terms(self):
        with self.store.connect() as conn:
            rows=self.store.execute(conn,"""SELECT e.payload,a.alias,a.normalized_alias,NULL AS identifier
                FROM entity e JOIN entity_alias a ON a.entity_id=e.id
                UNION ALL
                SELECT e.payload,NULL,NULL,i.value FROM entity e JOIN entity_identifier i ON i.entity_id=e.id""").fetchall()
        return rows

    def analyze(self,passage_ids):
        terms=self._registry_terms();results=[]
        for passage_id in passage_ids:
            passage=self.store.passage(passage_id);text=passage["text"];matches={}
            for row in terms:
                entity=json.loads(row["payload"])
                term=row["alias"] or row["identifier"]
                if not term:continue
                for found in re.finditer(r"(?<![A-Za-z0-9])"+re.escape(term)+r"(?![A-Za-z0-9])",text,re.I):
                    method="identifier" if row["identifier"] else ("canonical" if term.casefold()==entity["canonical_name"].casefold() else "alias")
                    key=(entity["id"],found.start(),found.end())
                    matches[key]=EntityMention(entity_id=entity["id"],canonical_name=entity["canonical_name"],kind=entity["kind"],matched_text=found.group(),start_offset=found.start(),end_offset=found.end(),method=method).model_dump(mode="json")
            document=passage["document"];events=[]
            issuer_id=document["issuer_id"]
            for found in GUIDANCE.finditer(text):
                word=found.group("span").casefold()
                direction="increase" if "raised" in word or "increased" in word else ("decrease" if "lowered" in word or "reduced" in word else "unchanged")
                events.append(EventCandidate(event_type="GUIDANCE_CHANGE",company_id=issuer_id,direction=direction,evidence_span=found.group("span"),start_offset=found.start("span"),end_offset=found.end("span"),confidence=.95).model_dump(mode="json"))
            for event_type,pattern in EVENTS:
                for found in pattern.finditer(text):
                    events.append(EventCandidate(event_type=event_type,company_id=issuer_id,direction="not_applicable",evidence_span=found.group("span"),start_offset=found.start("span"),end_offset=found.end("span"),confidence=.9).model_dump(mode="json"))
            results.append({"passage_id":str(passage_id),"document_id":document["id"],"entity_mentions":sorted(matches.values(),key=lambda item:(item["start_offset"],item["canonical_name"])),"event_candidates":events})
        return {"results":results,"review_required":True,"method":"review-only deterministic registry and explicit event patterns"}
