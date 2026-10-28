import json
import sqlite3
import os
import tempfile
from difflib import SequenceMatcher
from contextlib import contextmanager
from datetime import datetime, timezone
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

from fig.contracts import ReviewedBundle, SourceBundle, Document, Entity, ClaimRevision, NeighborRequest, PathRequest, DocumentComparisonRequest, RelationshipHistoryRequest, EntityResolutionDecision, OntologyProposalCreate, OntologyProposalDecision, SEED_ONTOLOGY, ONTOLOGY, eligible

class ImmutableConflict(ValueError):
    pass
class ResolutionConflict(ValueError):
    pass
class OntologyConflict(ValueError):
    pass

class Store:
    def __init__(self, database_url: str):
        self.url = database_url
        self.fixture_mode = database_url.startswith("sqlite:///")
        if not self.fixture_mode and not database_url.startswith(("postgresql://", "postgres://")):
            raise ValueError("database URL must be PostgreSQL or a SQLite fixture path")

    @contextmanager
    def connect(self):
        if self.fixture_mode:
            path = self.url.removeprefix("sqlite:///")
            Path(path).parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(path, timeout=5)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys=ON")
        else:
            import psycopg
            from psycopg.rows import dict_row
            conn = psycopg.connect(self.url, row_factory=dict_row, connect_timeout=5)
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    def execute(self, conn, sql, args=()):
        return conn.execute(sql if self.fixture_mode else sql.replace("?", "%s"), args)

    def migrate(self):
        with self.connect() as conn:
            if not self.fixture_mode:
                self.execute(conn, "SELECT pg_advisory_xact_lock(184273)")
            self.execute(conn, "CREATE TABLE IF NOT EXISTS schema_migration (version TEXT PRIMARY KEY, checksum TEXT NOT NULL)")
            for filename in ("001_core.sql", "002_ingestion.sql", "003_review.sql", "004_entity_resolution.sql", "005_ontology_evolution.sql", "006_entity_registry.sql", "007_event_review.sql", "008_financial_facts.sql", "009_runtime_ontology.sql", "010_claim_lifecycle.sql"):
                version=filename[:3]
                sql=files("fig").joinpath("resources/"+filename).read_text()
                checksum=sha256(sql.encode()).hexdigest()
                row=self.execute(conn,"SELECT checksum FROM schema_migration WHERE version=?",(version,)).fetchone()
                if row:
                    if row["checksum"]!=checksum:
                        raise ImmutableConflict("applied migration checksum changed")
                    continue
                for statement in sql.split(";"):
                    if statement.strip():
                        self.execute(conn,statement)
                self.execute(conn,"INSERT INTO schema_migration VALUES (?,?)",(version,checksum))
            for ordinal,ontology,parent,notes in ((1,SEED_ONTOLOGY,None,"Seed expert ontology."),(2,ONTOLOGY,SEED_ONTOLOGY["version"],"Expanded human-controlled MVP ontology.")):
                definitions=json.dumps(ontology,sort_keys=True,separators=(",",":"));schema_hash=sha256(definitions.encode()).hexdigest()
                self.execute(conn,"INSERT INTO ontology_version(version,ordinal,parent_version,schema_hash,definitions,migration_notes,approved_at,approved_by) VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(version) DO NOTHING",
                             (ontology["version"],ordinal,parent,schema_hash,definitions,notes,"2026-09-30T00:00:00.000000Z","project:seed"))
                row=self.execute(conn,"SELECT schema_hash FROM ontology_version WHERE version=?",(ontology["version"],)).fetchone()
                if row["schema_hash"]!=schema_hash:raise ImmutableConflict("seed ontology version changed")
            claims=self.execute(conn,"SELECT payload FROM claim_revision ORDER BY id").fetchall()
            for row in claims:
                claim=ClaimRevision.model_validate_json(row["payload"]);self._link_relationship_identity(conn,claim)
                validation=self.execute(conn,"SELECT claim_revision_id FROM claim_ontology_validation WHERE claim_revision_id=?",(str(claim.id),)).fetchone()
                if not validation:
                    endpoints={}
                    for entity_id in (claim.subject_id,claim.object_id):
                        entity_row=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(str(entity_id),)).fetchone()
                        if not entity_row:raise ImmutableConflict("legacy claim endpoint is missing")
                        endpoints[entity_id]=Entity.model_validate_json(entity_row["payload"])
                    rule=ONTOLOGY["predicates"].get(claim.predicate)
                    if not rule or endpoints[claim.subject_id].kind not in rule["subject"] or endpoints[claim.object_id].kind not in rule["object"]:
                        raise ImmutableConflict("legacy claim cannot be validated under finance-v2")
                    version=self.execute(conn,"SELECT schema_hash FROM ontology_version WHERE version=?",(ONTOLOGY["version"],)).fetchone()
                    payload={"claim_revision_id":str(claim.id),"ontology_version":ONTOLOGY["version"],"schema_hash":version["schema_hash"],
                        "validated_at":claim.system_from.isoformat(timespec="microseconds").replace("+00:00","Z"),"validator":"migration-backfill-v1"}
                    self.execute(conn,"INSERT INTO claim_ontology_validation VALUES (?,?,?,?,?,?)",(str(claim.id),ONTOLOGY["version"],version["schema_hash"],payload["validated_at"],payload["validator"],json.dumps(payload,sort_keys=True)))
        self.seed_core_registry()

    def _link_relationship_identity(self,conn,claim):
        key=f"{claim.subject_id}:{claim.predicate}:{claim.object_id}";relationship_id=str(uuid5(NAMESPACE_URL,"fig:relationship:"+key))
        payload={"id":relationship_id,"subject_id":str(claim.subject_id),"predicate":claim.predicate,"object_id":str(claim.object_id)}
        self.execute(conn,"INSERT INTO relationship_identity VALUES (?,?,?,?,?) ON CONFLICT(subject_id,predicate,object_id) DO NOTHING",
                     (relationship_id,str(claim.subject_id),claim.predicate,str(claim.object_id),json.dumps(payload,sort_keys=True)))
        self.execute(conn,"INSERT INTO claim_relationship_link VALUES (?,?) ON CONFLICT(claim_revision_id) DO NOTHING",(str(claim.id),relationship_id))
        return relationship_id

    @staticmethod
    def normalize_alias(value):
        return " ".join(value.casefold().replace(".","").split())

    def seed_core_registry(self):
        """Attach reviewed identifiers, aliases, products and technologies to the pilot."""
        registry={
            "1045810":{"ticker":"NVDA","aliases":["NVIDIA","Nvidia","NVIDIA Corporation","NVIDIA Corp."]},
            "2488":{"ticker":"AMD","aliases":["AMD","Advanced Micro Devices","Advanced Micro Devices, Inc."]},
            "1730168":{"ticker":"AVGO","aliases":["Broadcom","Broadcom Inc","Broadcom Inc."]},
            "937966":{"ticker":"ASML","aliases":["ASML","ASML Holding","ASML Holding N.V.","ASML Holding NV"]},
            "1046179":{"ticker":"TSM","aliases":["TSMC","Taiwan Semiconductor Manufacturing","Taiwan Semiconductor Manufacturing Company","Taiwan Semiconductor Manufacturing Company Limited"]},
        }
        with self.connect() as conn:
            for cik,item in registry.items():
                row=self.execute(conn,"SELECT id FROM entity WHERE slug=?",("sec-cik-"+cik,)).fetchone()
                if not row:continue
                entity_id=row["id"]
                for scheme,value in (("CIK",cik),("TICKER",item["ticker"])):
                    payload=json.dumps({"entity_id":entity_id,"scheme":scheme,"value":value,"source":"project:seed-registry"},sort_keys=True)
                    self.execute(conn,"INSERT INTO entity_identifier VALUES (?,?,?,?,?) ON CONFLICT(scheme,value) DO NOTHING",(entity_id,scheme,value,"project:seed-registry",payload))
                    current=self.execute(conn,"SELECT entity_id FROM entity_identifier WHERE scheme=? AND value=?",(scheme,value)).fetchone()
                    if current["entity_id"]!=entity_id:raise ImmutableConflict("identifier already belongs to another entity")
                for alias in item["aliases"]:
                    normalized=self.normalize_alias(alias);payload=json.dumps({"entity_id":entity_id,"alias":alias,"normalized_alias":normalized,"source":"project:seed-registry"},sort_keys=True)
                    self.execute(conn,"INSERT INTO entity_alias VALUES (?,?,?,?,?) ON CONFLICT(entity_id,normalized_alias) DO NOTHING",(entity_id,alias,normalized,"project:seed-registry",payload))
            supplemental={"Samsung Electronics Co., Ltd.":["Samsung","Samsung Electronics","Samsung Electronics Co., Ltd."]}
            for canonical_name,aliases in supplemental.items():
                row=self.execute(conn,"SELECT id FROM entity WHERE canonical_name=?",(canonical_name,)).fetchone()
                if not row:continue
                for alias in aliases:
                    normalized=self.normalize_alias(alias);payload=json.dumps({"entity_id":row["id"],"alias":alias,"normalized_alias":normalized,"source":"project:seed-registry"},sort_keys=True)
                    self.execute(conn,"INSERT INTO entity_alias VALUES (?,?,?,?,?) ON CONFLICT(entity_id,normalized_alias) DO NOTHING",(row["id"],alias,normalized,"project:seed-registry",payload))
            golden=(
                ("Product","NVIDIA H100","nvidia-h100",("H100","NVIDIA H100 Tensor Core GPU")),
                ("Product","NVIDIA H200","nvidia-h200",("H200","NVIDIA H200 Tensor Core GPU")),
                ("Product","NVIDIA Blackwell","nvidia-blackwell",("Blackwell","Blackwell GPU")),
                ("Product","AMD Instinct MI300X","amd-mi300x",("MI300X","AMD MI300X")),
                ("Product","AMD Instinct MI325X","amd-mi325x",("MI325X","AMD MI325X")),
                ("Technology","TSMC N3","tsmc-n3",("N3","TSMC 3nm")),
                ("Technology","TSMC N5","tsmc-n5",("N5","TSMC 5nm")),
                ("Technology","ASML EUV lithography","asml-euv",("EUV","EUV systems","ASML EUV systems")),
                ("Product","Broadcom networking products","broadcom-networking-products",("Broadcom networking","Broadcom networking products")),
                ("Person","Jen-Hsun Huang","jen-hsun-huang",("Jensen Huang","Jen-Hsun Huang")),
                ("Person","Lisa Su","lisa-su",("Dr. Lisa Su","Lisa Su")),
                ("Person","Hock Tan","hock-tan",("Hock Tan",)),
                ("Person","Christophe Fouquet","christophe-fouquet",("Christophe Fouquet",)),
                ("Person","C.C. Wei","cc-wei",("Dr. C.C. Wei","C. C. Wei","C.C. Wei")),
            )
            for kind,canonical_name,slug,aliases in golden:
                entity=Entity(id=uuid5(NAMESPACE_URL,"fig:golden-entity:"+slug),kind=kind,canonical_name=canonical_name,slug=slug,status="reviewed")
                self.insert_immutable(conn,"entity",entity,["kind","canonical_name","slug","status"])
                for alias in (canonical_name,*aliases):
                    normalized=self.normalize_alias(alias);payload=json.dumps({"entity_id":str(entity.id),"alias":alias,"normalized_alias":normalized,"source":"project:golden-entity-set"},sort_keys=True)
                    self.execute(conn,"INSERT INTO entity_alias VALUES (?,?,?,?,?) ON CONFLICT(entity_id,normalized_alias) DO NOTHING",(str(entity.id),alias,normalized,"project:golden-entity-set",payload))

    def entity_registry(self,entity_id):
        with self.connect() as conn:
            row=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(str(entity_id),)).fetchone()
            if not row:raise KeyError("entity not found")
            canonical=self.canonical_entity_id(conn,entity_id)
            entity=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(canonical,)).fetchone()
            identifiers=[json.loads(r["payload"]) for r in self.execute(conn,"SELECT payload FROM entity_identifier WHERE entity_id=? ORDER BY scheme",(canonical,)).fetchall()]
            aliases=[json.loads(r["payload"]) for r in self.execute(conn,"SELECT payload FROM entity_alias WHERE entity_id=? ORDER BY normalized_alias",(canonical,)).fetchall()]
            return {"entity":json.loads(entity["payload"]),"identifiers":identifiers,"aliases":aliases}

    def resolve_entity_mention(self,mention):
        normalized=self.normalize_alias(mention)
        with self.connect() as conn:
            rows=self.execute(conn,"""SELECT DISTINCT e.payload FROM entity e LEFT JOIN entity_alias a ON a.entity_id=e.id
                LEFT JOIN entity_identifier i ON i.entity_id=e.id
                WHERE LOWER(e.canonical_name)=? OR a.normalized_alias=? OR LOWER(i.value)=?
                ORDER BY e.canonical_name""",(mention.strip().casefold(),normalized,mention.strip().casefold())).fetchall()
            entities=[Entity.model_validate_json(r["payload"]).model_dump(mode="json") for r in rows]
            return {"mention":mention,"normalized_mention":normalized,"matches":entities,"resolved":entities[0] if len(entities)==1 else None,"ambiguous":len(entities)>1}

    def entity_resolution_candidates(self,mention,limit=10):
        normalized=self.normalize_alias(mention)
        if len(normalized)<2:raise ValueError("mention must contain at least two characters")
        exact=self.resolve_entity_mention(mention)
        with self.connect() as conn:
            rows=self.execute(conn,"""SELECT e.payload,a.alias,i.value AS identifier FROM entity e
                LEFT JOIN entity_alias a ON a.entity_id=e.id
                LEFT JOIN entity_identifier i ON i.entity_id=e.id ORDER BY e.canonical_name,e.id""").fetchall()
        candidates={}
        for row in rows:
            entity=json.loads(row["payload"]);terms=[entity["canonical_name"],row["alias"],row["identifier"]]
            score=max((SequenceMatcher(None,normalized,self.normalize_alias(str(term)),autojunk=False).ratio() for term in terms if term),default=0)
            current=candidates.get(entity["id"])
            if current is None or score>current["score"]:candidates[entity["id"]]={"entity":entity,"score":round(score,4)}
        ranked=sorted(candidates.values(),key=lambda item:(-item["score"],item["entity"]["canonical_name"]))[:limit]
        for item in ranked:
            score=item["score"]
            item["confidence_band"]="exact" if score==1 else ("contextual_validation" if score>=.9 else ("manual_review" if score>=.7 else "unresolved"))
            item["automatic_merge_allowed"]=False
        return {"mention":mention,"normalized_mention":normalized,"exact_resolution":exact["resolved"],"candidates":ranked,
                "policy":{">=1.0":"exact registry resolution",">=0.90":"contextual validation required",">=0.70":"manual review required","<0.70":"unresolved"},
                "automatic_fuzzy_merge":False}

    def ontology_versions(self):
        with self.connect() as conn:
            rows=self.execute(conn,"SELECT * FROM ontology_version ORDER BY ordinal").fetchall()
            return {"versions":[{"version":r["version"],"ordinal":r["ordinal"],"parent_version":r["parent_version"],"schema_hash":r["schema_hash"],"definitions":json.loads(r["definitions"]),"migration_notes":r["migration_notes"],"approved_at":r["approved_at"],"approved_by":r["approved_by"]} for r in rows]}

    def create_schema_discovery(self,*,passage_id,failure_type,concept_name,proposed_change_type,exact_quote,rationale,proposed_schema):
        passage=self.passage(passage_id)
        if passage["text"].count(exact_quote)!=1:raise ValueError("discovery quote must occur exactly once in the passage")
        created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        key=json.dumps([str(passage_id),failure_type,concept_name,exact_quote],ensure_ascii=False)
        discovery_id=str(uuid5(NAMESPACE_URL,"fig:schema-discovery:"+key))
        payload={"id":discovery_id,"passage_id":str(passage_id),"failure_type":failure_type,"concept_name":concept_name,
                 "proposed_change_type":proposed_change_type,"exact_quote":exact_quote,"rationale":rationale,
                 "proposed_schema":proposed_schema,"state":"pending","created_at":created_at}
        with self.connect() as conn:
            self.execute(conn,"INSERT INTO schema_discovery VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                         (discovery_id,str(passage_id),"pending",failure_type,concept_name,proposed_change_type,created_at,json.dumps(payload,sort_keys=True)))
            row=self.execute(conn,"SELECT payload FROM schema_discovery WHERE id=?",(discovery_id,)).fetchone()
        stored=json.loads(row["payload"])
        if {k:stored[k] for k in ("passage_id","failure_type","concept_name","exact_quote")}!={k:payload[k] for k in ("passage_id","failure_type","concept_name","exact_quote")}:
            raise ImmutableConflict("schema discovery ID already has different content")
        return stored

    def schema_discoveries(self,state="all"):
        with self.connect() as conn:
            where="" if state=="all" else " WHERE state=?";args=() if state=="all" else (state,)
            rows=self.execute(conn,"SELECT payload FROM schema_discovery"+where+" ORDER BY created_at,id",args).fetchall()
        return {"discoveries":[json.loads(row["payload"]) for row in rows]}

    def create_reprocessing_job(self,proposal_id,from_version,to_version,passage_ids):
        passages=sorted({str(value) for value in passage_ids})
        if not passages:raise ValueError("reprocessing job requires an impact set")
        input_hash=sha256(json.dumps({"passage_ids":passages,"from":from_version,"to":to_version},sort_keys=True).encode()).hexdigest()
        job_id=str(uuid5(NAMESPACE_URL,f"fig:ontology-reprocess:{proposal_id}:{to_version}:{input_hash}"))
        payload={"id":job_id,"proposal_id":str(proposal_id),"from_version":from_version,"to_version":to_version,
                 "input_hash":input_hash,"impact":{"passage_ids":passages,"passage_count":len(passages)},"status":"pending"}
        with self.connect() as conn:
            for passage_id in passages:
                if not self.execute(conn,"SELECT id FROM passage WHERE id=?",(passage_id,)).fetchone():raise KeyError("impact passage not found")
            self.execute(conn,"INSERT INTO ontology_reprocessing_job VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(proposal_id,to_version,input_hash) DO NOTHING",
                         (job_id,str(proposal_id),from_version,to_version,"pending",input_hash,None,None,json.dumps(payload,sort_keys=True)))
            row=self.execute(conn,"SELECT payload FROM ontology_reprocessing_job WHERE proposal_id=? AND to_version=? AND input_hash=?",(str(proposal_id),to_version,input_hash)).fetchone()
        return json.loads(row["payload"])

    def update_reprocessing_job(self,job_id,status,*,result=None,error=None):
        now=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            row=self.execute(conn,"SELECT * FROM ontology_reprocessing_job WHERE id=?",(str(job_id),)).fetchone()
            if not row:raise KeyError("reprocessing job not found")
            payload=json.loads(row["payload"]);payload.update({"status":status})
            if result is not None:payload["result"]=result
            if error is not None:payload["error"]=error
            started=row["started_at"] or (now if status=="running" else None);completed=now if status in {"completed","failed"} else None
            self.execute(conn,"UPDATE ontology_reprocessing_job SET status=?,started_at=?,completed_at=?,payload=? WHERE id=?",
                         (status,started,completed,json.dumps(payload,sort_keys=True),str(job_id)))
        return payload

    def reprocessing_jobs(self,status="all"):
        with self.connect() as conn:
            where="" if status=="all" else " WHERE status=?";args=() if status=="all" else (status,)
            rows=self.execute(conn,"SELECT payload FROM ontology_reprocessing_job"+where+" ORDER BY id",args).fetchall()
        return {"jobs":[json.loads(row["payload"]) for row in rows]}

    def create_ontology_proposal(self, proposal: OntologyProposalCreate):
        created_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        proposal_id=str(uuid4())
        payload={"id":proposal_id,**proposal.model_dump(mode="json"),"state":"pending","version":1,"created_at":created_at}
        with self.connect() as conn:
            if not self.execute(conn,"SELECT version FROM ontology_version WHERE version=?",(proposal.base_ontology_version,)).fetchone():
                raise KeyError("base ontology version not found")
            for passage_id in proposal.evidence_passage_ids:
                if not self.execute(conn,"SELECT id FROM passage WHERE id=?",(str(passage_id),)).fetchone():
                    raise KeyError("evidence passage not found")
            duplicate=self.execute(conn,"SELECT id FROM ontology_change_proposal WHERE base_ontology_version=? AND change_type=? AND concept_name=? AND state IN ('pending','deferred')",(proposal.base_ontology_version,proposal.change_type,proposal.concept_name)).fetchone()
            if duplicate:raise OntologyConflict("An open proposal already exists for this concept.")
            self.execute(conn,"INSERT INTO ontology_change_proposal VALUES (?,?,?,?,?,?,?,?)",(proposal_id,proposal.base_ontology_version,proposal.change_type,proposal.concept_name,"pending",1,created_at,json.dumps(payload,sort_keys=True)))
            for passage_id in proposal.evidence_passage_ids:
                self.execute(conn,"INSERT INTO ontology_proposal_evidence VALUES (?,?)",(proposal_id,str(passage_id)))
        return payload

    def ontology_proposals(self,state="all",limit=100,offset=0):
        with self.connect() as conn:
            where="" if state=="all" else " WHERE state=?"
            args=() if state=="all" else (state,)
            rows=self.execute(conn,"SELECT payload FROM ontology_change_proposal"+where+" ORDER BY created_at,id LIMIT ? OFFSET ?",(*args,limit+1,offset)).fetchall()
            return {"proposals":[json.loads(r["payload"]) for r in rows[:limit]],"truncated":len(rows)>limit,"next_offset":offset+limit if len(rows)>limit else None}

    def ontology_proposal(self,proposal_id):
        with self.connect() as conn:
            row=self.execute(conn,"SELECT payload FROM ontology_change_proposal WHERE id=?",(str(proposal_id),)).fetchone()
            if not row:raise KeyError("ontology proposal not found")
            decisions=self.execute(conn,"SELECT payload FROM ontology_change_decision WHERE proposal_id=? ORDER BY proposal_version",(str(proposal_id),)).fetchall()
            migration=self.execute(conn,"SELECT payload FROM ontology_migration WHERE proposal_id=?",(str(proposal_id),)).fetchone()
            return {"proposal":json.loads(row["payload"]),"decisions":[json.loads(r["payload"]) for r in decisions],"migration":json.loads(migration["payload"]) if migration else None}

    @staticmethod
    def _apply_ontology_change(definitions,proposal):
        result=json.loads(json.dumps(definitions))
        name=proposal["concept_name"];schema=proposal["proposed_schema"]
        if proposal["change_type"]=="add_entity_kind":
            if name in result["entities"]:raise OntologyConflict("Entity kind already exists.")
            if schema not in ({},{"name":name}):raise ValueError("Entity-kind schema may only repeat its name.")
            result["entities"].append(name)
        elif proposal["change_type"]=="add_predicate":
            if name in result["predicates"]:raise OntologyConflict("Predicate already exists.")
            if set(schema)!={"subject","object"} or not all(isinstance(schema[k],list) and schema[k] for k in ("subject","object")):
                raise ValueError("Predicate schema requires nonempty subject and object lists.")
            unknown=set(schema["subject"]+schema["object"])-set(result["entities"])
            if unknown:raise ValueError("Predicate schema references unknown entity kinds: "+", ".join(sorted(unknown)))
            result["predicates"][name]={"subject":schema["subject"],"object":schema["object"]}
        else:
            qualifiers=result.setdefault("qualifiers",{})
            if name in qualifiers:raise OntologyConflict("Qualifier already exists.")
            if not schema:raise ValueError("Qualifier schema cannot be empty.")
            qualifiers[name]=schema
        return result

    def rebase_ontology_proposal(self,proposal_id,rebase):
        proposal_id=str(proposal_id);decided_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            if self.fixture_mode:self.execute(conn,"BEGIN IMMEDIATE")
            row=self.execute(conn,"SELECT * FROM ontology_change_proposal WHERE id=?"+('' if self.fixture_mode else ' FOR UPDATE'),(proposal_id,)).fetchone()
            if not row:raise KeyError("ontology proposal not found")
            if row["version"]!=rebase.expected_version:raise OntologyConflict("Ontology proposal changed. Reload before rebasing.")
            if row["state"] not in {"pending","deferred"}:raise OntologyConflict("Only pending or deferred proposals can be rebased.")
            target=self.execute(conn,"SELECT definitions FROM ontology_version WHERE version=?",(rebase.target_ontology_version,)).fetchone()
            if not target:raise KeyError("target ontology version not found")
            proposal=json.loads(row["payload"])
            if proposal["base_ontology_version"]==rebase.target_ontology_version:raise OntologyConflict("Proposal already uses that ontology version.")
            self._apply_ontology_change(json.loads(target["definitions"]),proposal)
            new_version=row["version"]+1
            audit={"id":str(uuid4()),"proposal_id":proposal_id,"proposal_version":new_version,"action":"rebase","reviewer":rebase.reviewer.strip(),
                "notes":rebase.notes.strip(),"from_ontology_version":proposal["base_ontology_version"],"ontology_version":rebase.target_ontology_version,"decided_at":decided_at}
            updated={**proposal,"base_ontology_version":rebase.target_ontology_version,"version":new_version,"latest_decision":audit}
            self.execute(conn,"UPDATE ontology_change_proposal SET base_ontology_version=?,version=?,payload=? WHERE id=?",
                (rebase.target_ontology_version,new_version,json.dumps(updated,sort_keys=True),proposal_id))
            self.execute(conn,"INSERT INTO ontology_change_decision VALUES (?,?,?,?)",(audit["id"],proposal_id,new_version,json.dumps(audit,sort_keys=True)))
        return {"proposal":updated,"decision":audit}

    def decide_ontology_proposal(self,proposal_id,decision: OntologyProposalDecision):
        proposal_id=str(proposal_id);decided_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            if self.fixture_mode:self.execute(conn,"BEGIN IMMEDIATE")
            row=self.execute(conn,"SELECT * FROM ontology_change_proposal WHERE id=?"+('' if self.fixture_mode else ' FOR UPDATE'),(proposal_id,)).fetchone()
            if not row:raise KeyError("ontology proposal not found")
            if row["version"]!=decision.expected_version:raise OntologyConflict("Ontology proposal changed. Reload before deciding.")
            if row["state"] in ("accepted","merged","rejected"):raise OntologyConflict("Ontology proposal already has a final decision.")
            proposal=json.loads(row["payload"]);new_version=row["version"]+1
            ontology_version=None;migration=None
            if decision.action=="merge":
                base=self.execute(conn,"SELECT definitions FROM ontology_version WHERE version=?",(row["base_ontology_version"],)).fetchone()
                if not base:raise KeyError("base ontology version not found")
                definitions=json.loads(base["definitions"]);target=decision.merge_target
                if row["change_type"]=="add_entity_kind":exists=target in definitions.get("entities",[])
                elif row["change_type"]=="add_predicate":exists=target in definitions.get("predicates",{})
                else:exists=target in definitions.get("qualifiers",{})
                if not exists:
                    raise ValueError("merge_target must name an existing concept of the same ontology category")
            if decision.action=="accept":
                latest=self.execute(conn,"SELECT * FROM ontology_version ORDER BY ordinal DESC LIMIT 1"+('' if self.fixture_mode else ' FOR UPDATE')).fetchone()
                if latest["version"]!=row["base_ontology_version"]:
                    raise OntologyConflict("Proposal base is no longer the current ontology. Rebase it before acceptance.")
                definitions=self._apply_ontology_change(json.loads(latest["definitions"]),proposal)
                ordinal=latest["ordinal"]+1;ontology_version=f"finance-v{ordinal}"
                definitions["version"]=ontology_version
                encoded=json.dumps(definitions,sort_keys=True,separators=(",",":"));digest=sha256(encoded.encode()).hexdigest()
                self.execute(conn,"INSERT INTO ontology_version VALUES (?,?,?,?,?,?,?,?)",(ontology_version,ordinal,latest["version"],digest,encoded,decision.migration_notes,decided_at,decision.reviewer.strip()))
                migration={"id":str(uuid4()),"proposal_id":proposal_id,"from_version":latest["version"],"to_version":ontology_version,"change_type":row["change_type"],"concept_name":row["concept_name"],"migration_notes":decision.migration_notes,"created_at":decided_at}
                self.execute(conn,"INSERT INTO ontology_migration VALUES (?,?,?,?,?)",(migration["id"],proposal_id,latest["version"],ontology_version,json.dumps(migration,sort_keys=True)))
            decision_payload={"id":str(uuid4()),"proposal_id":proposal_id,"proposal_version":new_version,"action":decision.action,"reviewer":decision.reviewer.strip(),"notes":decision.notes.strip(),"merge_target":decision.merge_target,"ontology_version":ontology_version,"decided_at":decided_at}
            updated={**proposal,"state":{"accept":"accepted","merge":"merged","reject":"rejected","defer":"deferred"}[decision.action],"version":new_version,"latest_decision":decision_payload}
            self.execute(conn,"UPDATE ontology_change_proposal SET state=?,version=?,payload=? WHERE id=?",(updated["state"],new_version,json.dumps(updated,sort_keys=True),proposal_id))
            self.execute(conn,"INSERT INTO ontology_change_decision VALUES (?,?,?,?)",(decision_payload["id"],proposal_id,new_version,json.dumps(decision_payload,sort_keys=True)))
        return {"proposal":updated,"decision":decision_payload,"migration":migration}

    def insert_immutable(self, conn, table, record, columns):
        data = record.model_dump(mode="json")
        payload = json.dumps(data, sort_keys=True, separators=(",", ":"))
        names = ["id", *columns, "payload"]
        args = [data["id"], *(data[x] for x in columns), payload]
        self.execute(conn, f"INSERT INTO {table} ({','.join(names)}) VALUES ({','.join('?' for _ in names)}) ON CONFLICT(id) DO NOTHING", args)
        row = self.execute(conn, f"SELECT payload FROM {table} WHERE id=?", (data["id"],)).fetchone()
        previous = row["payload"]
        if table == "document":
            previous = json.dumps(Document.model_validate_json(previous).model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        if previous != payload:
            raise ImmutableConflict(f"{table} ID already has different content")

    def archive(self, original: bytes, content_hash: str, archive_dir: Path):
        if sha256(original).hexdigest()!=content_hash:
            raise ValueError("original source checksum mismatch")
        archive_dir.mkdir(parents=True, exist_ok=True)
        archive = archive_dir / content_hash
        # Content-addressed artifacts may remain after rollback; safe to garbage-collect later.
        # Publish complete bytes atomically: interrupted writes cannot leave a
        # truncated artifact at its content hash. Hard-link publication is no-clobber.
        with tempfile.NamedTemporaryFile(dir=archive_dir, delete=False) as output:
            temporary = Path(output.name)
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
        try:
            try:
                os.link(temporary, archive)
            except FileExistsError:
                if sha256(archive.read_bytes()).hexdigest() != content_hash:
                    raise ImmutableConflict("archived bytes are corrupt")
        finally:
            temporary.unlink(missing_ok=True)
        return archive

    def ingest(self, bundle: ReviewedBundle, original: bytes, archive_dir: Path):
        archive=self.archive(original,bundle.document.content_hash,archive_dir)
        with self.connect() as conn:
            self.persist_reviewed(conn,bundle)
        return {"document_id": str(bundle.document.id), "claim_revision_id": str(bundle.claim.id), "archive_hash": archive.name}

    def persist_reviewed(self,conn,bundle: ReviewedBundle):
        """Persist validated records and outbox inside the caller's transaction."""
        from fig.ontology_runtime import RuntimeOntology
        ontology=RuntimeOntology.from_store(self,bundle.ontology_version)
        entities={entity.id:entity for entity in bundle.entities}
        ontology.validate_relationship(entities[bundle.claim.subject_id].kind,bundle.claim.predicate,entities[bundle.claim.object_id].kind)
        if bundle.ontology_schema_hash and bundle.ontology_schema_hash!=ontology.schema_hash:
            raise ValueError("ontology schema hash does not match the selected immutable version")
        for entity in bundle.entities:
            self.insert_immutable(conn, "entity", entity, ["kind", "canonical_name", "slug", "status"])
        self.insert_immutable(conn, "document", bundle.document, ["issuer_id","source","source_url","accession","filename","published_at","acquired_at","content_hash"])
        self.insert_immutable(conn, "text_version", bundle.text_version, ["document_id","parser_version","normalized_hash","normalized_text"])
        self.insert_immutable(conn, "passage", bundle.passage, ["text_version_id","start_offset","end_offset","section_path"])
        claim = bundle.claim
        self.execute(conn, "INSERT INTO claim(id) VALUES (?) ON CONFLICT(id) DO NOTHING", (str(claim.claim_id),))
        self.insert_immutable(conn, "claim_revision", claim, ["claim_id","revision","subject_id","object_id","predicate","review_state","assertion_class","polarity","source_available_at","system_from","system_to","valid_from","valid_to"])
        self._link_relationship_identity(conn,claim)
        self.insert_immutable(conn, "evidence", bundle.evidence, ["claim_revision_id","passage_id","quote","start_offset","end_offset","assessment"])
        validation={"claim_revision_id":str(claim.id),"ontology_version":ontology.version,"schema_hash":ontology.schema_hash,
                    "validated_at":datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z"),"validator":"runtime-ontology-v1"}
        self.execute(conn,"INSERT INTO claim_ontology_validation VALUES (?,?,?,?,?,?) ON CONFLICT(claim_revision_id) DO NOTHING",
                     (str(claim.id),ontology.version,ontology.schema_hash,validation["validated_at"],validation["validator"],json.dumps(validation,sort_keys=True)))
        current=self.execute(conn,"SELECT ontology_version,schema_hash FROM claim_ontology_validation WHERE claim_revision_id=?",(str(claim.id),)).fetchone()
        if current["ontology_version"]!=ontology.version or current["schema_hash"]!=ontology.schema_hash:
            raise ImmutableConflict("claim ontology validation changed")
        event_id = str(uuid5(NAMESPACE_URL, f"fig:projection:{claim.id}"))
        self.execute(conn, "INSERT INTO projection_outbox VALUES (?,?,?,?) ON CONFLICT(id) DO NOTHING", (event_id, str(claim.id), bundle.model_dump_json(), "pending"))

    def record_claim_lifecycle(self,relationship_id,*,action,reviewer,notes,claim_revision_id=None,conflicting_claim_revision_id=None):
        if action not in {"supersede","retract","correct","retain_conflict"}:raise ValueError("unsupported lifecycle action")
        if not reviewer.strip() or not notes.strip():raise ValueError("lifecycle decisions require reviewer and notes")
        decided_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            if not self.execute(conn,"SELECT id FROM relationship_identity WHERE id=?",(str(relationship_id),)).fetchone():raise KeyError("relationship identity not found")
            for value in (claim_revision_id,conflicting_claim_revision_id):
                if value and not self.execute(conn,"SELECT c.id FROM claim_revision c JOIN claim_relationship_link l ON l.claim_revision_id=c.id WHERE c.id=? AND l.relationship_id=?",(str(value),str(relationship_id))).fetchone():raise KeyError("claim revision is not part of this relationship identity")
            if action in {"supersede","correct"} and not claim_revision_id:raise ValueError("supersede and correct require the affected claim revision")
            if action=="retain_conflict" and (not claim_revision_id or not conflicting_claim_revision_id):raise ValueError("retain_conflict requires two claim revisions")
            if action=="retain_conflict" and str(claim_revision_id)==str(conflicting_claim_revision_id):raise ValueError("retain_conflict requires two distinct claim revisions")
            key=json.dumps([str(relationship_id),action,str(claim_revision_id),str(conflicting_claim_revision_id),decided_at])
            decision_id=str(uuid5(NAMESPACE_URL,"fig:claim-lifecycle:"+key))
            payload={"id":decision_id,"relationship_id":str(relationship_id),"action":action,"claim_revision_id":str(claim_revision_id) if claim_revision_id else None,
                     "conflicting_claim_revision_id":str(conflicting_claim_revision_id) if conflicting_claim_revision_id else None,
                     "reviewer":reviewer.strip(),"notes":notes.strip(),"decided_at":decided_at}
            self.execute(conn,"INSERT INTO claim_lifecycle_decision VALUES (?,?,?,?,?,?,?)",
                         (decision_id,str(relationship_id),action,payload["claim_revision_id"],payload["conflicting_claim_revision_id"],decided_at,json.dumps(payload,sort_keys=True)))
        return payload

    def relationship_lifecycle(self,relationship_id,knowledge_cutoff=None):
        with self.connect() as conn:
            row=self.execute(conn,"SELECT payload FROM relationship_identity WHERE id=?",(str(relationship_id),)).fetchone()
            if not row:raise KeyError("relationship identity not found")
            cutoff=knowledge_cutoff.isoformat(timespec="microseconds").replace("+00:00","Z") if knowledge_cutoff else None
            claim_sql="SELECT c.payload FROM claim_revision c JOIN claim_relationship_link l ON l.claim_revision_id=c.id WHERE l.relationship_id=?"
            decision_sql="SELECT payload FROM claim_lifecycle_decision WHERE relationship_id=?"
            args=[str(relationship_id)]
            if cutoff:claim_sql+=" AND c.system_from<=?";decision_sql+=" AND decided_at<=?";args.append(cutoff)
            claims=self.execute(conn,claim_sql+" ORDER BY c.source_available_at,c.id",tuple(args)).fetchall()
            decisions=self.execute(conn,decision_sql+" ORDER BY decided_at,id",(str(relationship_id),cutoff) if cutoff else (str(relationship_id),)).fetchall()
        return {"relationship":json.loads(row["payload"]),"claims":[json.loads(r["payload"]) for r in claims],"decisions":[json.loads(r["payload"]) for r in decisions]}

    def _claim_lifecycle_active(self,conn,claim_id,knowledge_cutoff=None):
        link=self.execute(conn,"SELECT relationship_id FROM claim_relationship_link WHERE claim_revision_id=?",(str(claim_id),)).fetchone()
        if not link:return True
        rows=self.execute(conn,"SELECT payload FROM claim_lifecycle_decision WHERE relationship_id=? ORDER BY decided_at,id",(link["relationship_id"],)).fetchall()
        cutoff=knowledge_cutoff.isoformat(timespec="microseconds").replace("+00:00","Z") if knowledge_cutoff else None
        decisions=[json.loads(row["payload"]) for row in rows]
        if cutoff:decisions=[row for row in decisions if row["decided_at"]<=cutoff]
        for decision in decisions:
            if decision["action"]=="retract":return False
            if decision["action"] in {"supersede","correct"} and decision["claim_revision_id"]==str(claim_id):return False
        return True

    def canonical_entity_id(self,conn,entity_id,identity_cutoff=None,_seen=None):
        entity_id=str(entity_id);_seen=set() if _seen is None else _seen
        if entity_id in _seen:return entity_id
        _seen.add(entity_id)
        if identity_cutoff:
            cutoff=identity_cutoff.isoformat(timespec="microseconds").replace("+00:00","Z")
            rows=self.execute(conn,"SELECT payload FROM entity_resolution_decision WHERE alias_entity_id=? ORDER BY resolution_version",(entity_id,)).fetchall()
            decisions=[json.loads(row["payload"]) for row in rows]
            eligible=[row for row in decisions if row["decided_at"]<=cutoff]
            if not eligible or eligible[-1]["action"]!="merge":return entity_id
            target=eligible[-1]["canonical_entity_id"]
            return self.canonical_entity_id(conn,target,identity_cutoff,_seen)
        row=self.execute(conn,"SELECT canonical_entity_id FROM entity_resolution WHERE alias_entity_id=? AND state='merged'",(entity_id,)).fetchone()
        return row["canonical_entity_id"] if row else entity_id

    def identity_members(self,conn,entity_id,identity_cutoff=None):
        canonical=self.canonical_entity_id(conn,entity_id,identity_cutoff)
        if identity_cutoff:
            aliases=self.execute(conn,"SELECT DISTINCT alias_entity_id FROM entity_resolution_decision ORDER BY alias_entity_id").fetchall()
            members=[row["alias_entity_id"] for row in aliases if self.canonical_entity_id(conn,row["alias_entity_id"],identity_cutoff)==canonical]
        else:
            aliases=self.execute(conn,"SELECT alias_entity_id FROM entity_resolution WHERE canonical_entity_id=? AND state='merged' ORDER BY alias_entity_id",(canonical,)).fetchall();members=[row["alias_entity_id"] for row in aliases]
        return canonical,[canonical,*[member for member in members if member!=canonical]]

    def resolve_entity(self,alias_entity_id,decision: EntityResolutionDecision):
        alias_id=str(alias_entity_id);target_id=str(decision.canonical_entity_id) if decision.canonical_entity_id else None
        decided_at=datetime.now(timezone.utc).isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            if self.fixture_mode:self.execute(conn,"BEGIN IMMEDIATE")
            alias_row=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(alias_id,)).fetchone()
            if not alias_row:raise KeyError("alias entity not found")
            current=self.execute(conn,"SELECT * FROM entity_resolution WHERE alias_entity_id=?"+('' if self.fixture_mode else ' FOR UPDATE'),(alias_id,)).fetchone()
            current_version=current["version"] if current else 0
            if current_version!=decision.expected_version:
                raise ResolutionConflict("Entity resolution changed. Reload before deciding.")
            alias=Entity.model_validate_json(alias_row["payload"])
            if decision.action=="merge":
                if target_id==alias_id:raise ValueError("An entity cannot resolve to itself.")
                target_row=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(target_id,)).fetchone()
                if not target_row:raise KeyError("canonical entity not found")
                target=Entity.model_validate_json(target_row["payload"])
                if alias.status!='reviewed' or target.status!='reviewed':raise ValueError("Only reviewed entities can be merged.")
                if alias.kind!=target.kind:raise ValueError("Entity kinds must match.")
                if self.canonical_entity_id(conn,target_id)!=target_id:
                    raise ValueError("Choose a canonical target, not another alias.")
                incoming=self.execute(conn,"SELECT alias_entity_id FROM entity_resolution WHERE canonical_entity_id=? AND state='merged' LIMIT 1",(alias_id,)).fetchone()
                if incoming:raise ValueError("An entity with active aliases cannot itself become an alias.")
                state="merged";canonical_id=target_id
            else:
                if not current or current["state"]!='merged':raise ResolutionConflict("Entity is not currently merged.")
                state="split";canonical_id=current["canonical_entity_id"]
            version=current_version+1
            payload={"alias_entity_id":alias_id,"alias_name":alias.canonical_name,
                     "canonical_entity_id":canonical_id,"action":decision.action,
                     "reviewer":decision.reviewer.strip(),"notes":decision.notes.strip(),
                     "version":version,"decided_at":decided_at}
            self.execute(conn,"INSERT INTO entity_resolution VALUES (?,?,?,?,?,?) ON CONFLICT(alias_entity_id) DO UPDATE SET canonical_entity_id=excluded.canonical_entity_id,state=excluded.state,version=excluded.version,decided_at=excluded.decided_at,payload=excluded.payload",(alias_id,canonical_id,state,version,decided_at,json.dumps(payload)))
            self.execute(conn,"INSERT INTO entity_resolution_decision VALUES (?,?,?,?)",(str(uuid4()),alias_id,version,json.dumps(payload)))
            # Re-project affected immutable claims using the current identity mapping.
            self.execute(conn,"UPDATE projection_outbox SET state='pending' WHERE claim_revision_id IN (SELECT id FROM claim_revision WHERE subject_id=? OR object_id=?)",(alias_id,alias_id))
        return {"alias_entity_id":alias_id,"canonical_entity_id":canonical_id,"state":state,"version":version,"decided_at":decided_at}

    def resolution_history(self,entity_id):
        with self.connect() as conn:
            entity=self.execute(conn,"SELECT payload FROM entity WHERE id=?",(str(entity_id),)).fetchone()
            if not entity:raise KeyError("entity not found")
            canonical,members=self.identity_members(conn,entity_id)
            current=self.execute(conn,"SELECT payload FROM entity_resolution WHERE alias_entity_id=?",(str(entity_id),)).fetchone()
            decisions=self.execute(conn,"SELECT payload FROM entity_resolution_decision WHERE alias_entity_id=? ORDER BY resolution_version",(str(entity_id),)).fetchall()
            return {"entity":Entity.model_validate_json(entity["payload"]).model_dump(mode="json"),
                    "canonical_entity_id":canonical,"identity_members":members,
                    "current":json.loads(current["payload"]) if current else None,
                    "decisions":[json.loads(row["payload"]) for row in decisions]}

    def neighbors(self, request: NeighborRequest):
        # Identity redirects are applied at read time; immutable claim endpoints remain
        # available for audit and can be restored by a reviewed split decision.
        conditions, args = [], []
        def timestamp(v):
            return v.isoformat(timespec="microseconds").replace("+00:00", "Z")
        with self.connect() as conn:
            exists = self.execute(conn, "SELECT payload FROM entity WHERE id=?", (str(request.entity_id),)).fetchone()
            if not exists:
                raise KeyError("entity not found")
            canonical,members=self.identity_members(conn,request.entity_id,request.identity_cutoff)
            placeholders=",".join("?" for _ in members)
            if request.direction == "both":
                conditions.append(f"(subject_id IN ({placeholders}) OR object_id IN ({placeholders}))")
                args.extend([*members,*members])
            else:
                conditions.append(("subject_id" if request.direction == "outgoing" else "object_id") + f" IN ({placeholders})")
                args.extend(members)
            conditions.extend(["review_state='accepted'", "assertion_class <> 'inferred'", "polarity='positive'"])
            ontology=None
            if request.ontology_version:
                from fig.ontology_runtime import RuntimeOntology
                ontology=RuntimeOntology.from_store(self,request.ontology_version)
                predicates=sorted(ontology.definitions.get("predicates",{}))
                conditions.append("predicate IN ("+",".join("?" for _ in predicates)+")");args.extend(predicates)
            if request.public_cutoff:
                conditions.append("source_available_at <= ?");args.append(timestamp(request.public_cutoff))
            if request.knowledge_cutoff:
                conditions.append("system_from <= ? AND (system_to IS NULL OR system_to > ?)");args.extend([timestamp(request.knowledge_cutoff)] * 2)
            else:conditions.append("system_to IS NULL")
            if request.effective_at:
                conditions.append("valid_from IS NOT NULL AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)");args.extend([timestamp(request.effective_at)] * 2)
            rows = self.execute(conn, "SELECT payload FROM claim_revision WHERE " + " AND ".join(conditions) + " ORDER BY id LIMIT ?", (*args,request.limit+1)).fetchall()
            result = []
            for row in rows[:request.limit]:
                claim = ClaimRevision.model_validate_json(row["payload"])
                if not eligible(claim, request):
                    continue
                if not self._claim_lifecycle_active(conn,claim.id,request.knowledge_cutoff):continue
                evidence = self.execute(conn, "SELECT e.payload AS evidence, p.payload AS passage, t.payload AS text_version, d.payload AS document FROM evidence e JOIN passage p ON p.id=e.passage_id JOIN text_version t ON t.id=p.text_version_id JOIN document d ON d.id=t.document_id WHERE e.claim_revision_id=? AND e.assessment='supported' ORDER BY e.id", (str(claim.id),)).fetchall()
                if evidence:
                    items=[{k:json.loads(r[k]) for k in r.keys()} for r in evidence]
                    for item in items:
                        item["text_version"].pop("normalized_text",None)
                    link=self.execute(conn,"SELECT relationship_id FROM claim_relationship_link WHERE claim_revision_id=?",(str(claim.id),)).fetchone()
                    result.append({"claim":claim.model_dump(mode="json"),"relationship_id":link["relationship_id"] if link else None,
                                   "resolved_subject_id":self.canonical_entity_id(conn,claim.subject_id,request.identity_cutoff),
                                   "resolved_object_id":self.canonical_entity_id(conn,claim.object_id,request.identity_cutoff),
                                   "evidence":items,"validity_known":claim.valid_from is not None})
            ids={canonical}
            for item in result:
                ids.update((item["resolved_subject_id"],item["resolved_object_id"]))
            placeholders=",".join("?" for _ in ids)
            entities=self.execute(conn,f"SELECT payload FROM entity WHERE id IN ({placeholders}) ORDER BY canonical_name",tuple(sorted(ids))).fetchall()
            return {"relationships":result,"entities":[Entity.model_validate_json(r["payload"]).model_dump(mode="json") for r in entities],"requested_entity_id":str(request.entity_id),"canonical_entity_id":canonical,"truncated":len(rows)>request.limit,"storage_mode":"sqlite_development" if self.fixture_mode else "postgresql","query_source":"authoritative_claim_store",
                    "ontology_version":ontology.version if ontology else None,"ontology_schema_hash":ontology.schema_hash if ontology else None,
                    "identity_cutoff":request.identity_cutoff.isoformat() if request.identity_cutoff else None}

    def paths(self, request: PathRequest):
        """Enumerate bounded simple business paths from authoritative accepted claims."""
        def timestamp(value):return value.isoformat(timespec="microseconds").replace("+00:00","Z")
        with self.connect() as conn:
            source_row=self.execute(conn,"SELECT id FROM entity WHERE id=?",(str(request.source_entity_id),)).fetchone()
            if not source_row:raise KeyError("source entity not found")
            source=self.canonical_entity_id(conn,request.source_entity_id,request.identity_cutoff)
            target=None
            if request.target_entity_id:
                if not self.execute(conn,"SELECT id FROM entity WHERE id=?",(str(request.target_entity_id),)).fetchone():raise KeyError("target entity not found")
                target=self.canonical_entity_id(conn,request.target_entity_id,request.identity_cutoff)
                if target==source:raise ValueError("source and target resolve to the same entity")
            conditions=["review_state='accepted'","assertion_class <> 'inferred'","polarity='positive'"];args=[]
            ontology=None
            if request.ontology_version:
                from fig.ontology_runtime import RuntimeOntology
                ontology=RuntimeOntology.from_store(self,request.ontology_version)
                allowed=sorted(ontology.definitions.get("predicates",{}));conditions.append("predicate IN ("+",".join("?" for _ in allowed)+")");args.extend(allowed)
            if request.public_cutoff:conditions.append("source_available_at <= ?");args.append(timestamp(request.public_cutoff))
            if request.knowledge_cutoff:
                conditions.append("system_from <= ? AND (system_to IS NULL OR system_to > ?)");args.extend([timestamp(request.knowledge_cutoff)]*2)
            else:conditions.append("system_to IS NULL")
            if request.effective_at:
                conditions.append("valid_from IS NOT NULL AND valid_from <= ? AND (valid_to IS NULL OR valid_to > ?)");args.extend([timestamp(request.effective_at)]*2)
            if request.predicates:
                conditions.append("predicate IN ("+",".join("?" for _ in request.predicates)+")");args.extend(request.predicates)
            rows=self.execute(conn,"SELECT payload FROM claim_revision WHERE "+" AND ".join(conditions)+" ORDER BY id",args).fetchall()
            adjacency={};edge_data={};entity_ids={source};selected={}
            for row in rows:
                claim=ClaimRevision.model_validate_json(row["payload"])
                if not self._claim_lifecycle_active(conn,claim.id,request.knowledge_cutoff):continue
                link=self.execute(conn,"SELECT relationship_id FROM claim_relationship_link WHERE claim_revision_id=?",(str(claim.id),)).fetchone()
                relationship_id=link["relationship_id"] if link else str(claim.id)
                rank=(claim.source_available_at,claim.system_from,claim.revision,str(claim.id))
                if relationship_id not in selected or rank>selected[relationship_id][0]:selected[relationship_id]=(rank,claim,relationship_id)
            for _,claim,relationship_id in selected.values():
                subject=self.canonical_entity_id(conn,claim.subject_id,request.identity_cutoff);object_=self.canonical_entity_id(conn,claim.object_id,request.identity_cutoff)
                if subject==object_:continue
                evidence=self.execute(conn,"SELECT e.payload AS evidence,p.payload AS passage,t.payload AS text_version,d.payload AS document FROM evidence e JOIN passage p ON p.id=e.passage_id JOIN text_version t ON t.id=p.text_version_id JOIN document d ON d.id=t.document_id WHERE e.claim_revision_id=? AND e.assessment='supported' ORDER BY e.id",(str(claim.id),)).fetchall()
                if not evidence:continue
                evidence_items=[{key:json.loads(item[key]) for key in item.keys()} for item in evidence]
                for item in evidence_items:item["text_version"].pop("normalized_text",None)
                edge={"claim":claim.model_dump(mode="json"),"resolved_subject_id":subject,"resolved_object_id":object_,"evidence":evidence_items,"validity_known":claim.valid_from is not None}
                edge["relationship_id"]=relationship_id
                edge_data[str(claim.id)]=edge;entity_ids.update((subject,object_))
                if request.direction in ("both","outgoing"):adjacency.setdefault(subject,[]).append((object_,str(claim.id),"forward"))
                if request.direction in ("both","incoming"):adjacency.setdefault(object_,[]).append((subject,str(claim.id),"reverse"))
            for links in adjacency.values():links.sort(key=lambda item:(item[0],item[1],item[2]))
            found=[];frontier=[(source,[source],[])] ; expansions=0;truncated=False
            while frontier and len(found)<request.limit:
                current,nodes,edges=frontier.pop(0)
                if len(edges)>=request.max_hops:continue
                for next_id,claim_id,traversal in adjacency.get(current,[]):
                    expansions+=1
                    if expansions>5000:truncated=True;frontier=[];break
                    if next_id in nodes or any(item["claim_revision_id"]==claim_id for item in edges):continue
                    next_nodes=[*nodes,next_id]
                    next_edges=[*edges,{"claim_revision_id":claim_id,"traversal":traversal,**edge_data[claim_id]}]
                    hops=len(next_edges);matches_target=target is None or next_id==target
                    if hops>=request.min_hops and matches_target:
                        found.append({"hops":hops,"entity_ids":next_nodes,"edges":next_edges})
                        if len(found)>=request.limit:truncated=bool(frontier or adjacency.get(current));break
                    if hops<request.max_hops and (target is None or next_id!=target):frontier.append((next_id,next_nodes,next_edges))
            used={entity for path in found for entity in path["entity_ids"]}
            entities=[]
            if used:
                placeholders=",".join("?" for _ in used)
                entities=[Entity.model_validate_json(row["payload"]).model_dump(mode="json") for row in self.execute(conn,f"SELECT payload FROM entity WHERE id IN ({placeholders}) ORDER BY canonical_name,id",tuple(sorted(used))).fetchall()]
            return {"paths":found,"entities":entities,"requested_source_entity_id":str(request.source_entity_id),"source_entity_id":source,"requested_target_entity_id":str(request.target_entity_id) if request.target_entity_id else None,"target_entity_id":target,"min_hops":request.min_hops,"max_hops":request.max_hops,"truncated":truncated,"projection_watermark":None,"query_source":"authoritative_claim_store",
                    "ontology_version":ontology.version if ontology else None,"ontology_schema_hash":ontology.schema_hash if ontology else None,
                    "identity_cutoff":request.identity_cutoff.isoformat() if request.identity_cutoff else None}

    def compare_documents(self,request: DocumentComparisonRequest):
        left=self.document(request.left_document_id);right=self.document(request.right_document_id)
        if left["issuer_id"]!=right["issuer_id"]:raise ValueError("comparison documents must have the same issuer")
        left_matches=self.passages(request.left_document_id,request.query,request.limit)["passages"]
        right_matches=self.passages(request.right_document_id,request.query,request.limit)["passages"]
        candidates=[]
        for l_index,l_passage in enumerate(left_matches):
            for r_index,r_passage in enumerate(right_matches):
                score=SequenceMatcher(None," ".join(l_passage["text"].split()).casefold()," ".join(r_passage["text"].split()).casefold(),autojunk=False).ratio()
                candidates.append((score,l_index,r_index))
        pairs=[];used_left=set();used_right=set()
        for score,l_index,r_index in sorted(candidates,key=lambda item:(-item[0],item[1],item[2])):
            if l_index in used_left or r_index in used_right:continue
            used_left.add(l_index);used_right.add(r_index)
            classification="unchanged" if score>=.98 else "modified"
            pairs.append({"classification":classification,"similarity":round(score,4),"left":left_matches[l_index],"right":right_matches[r_index]})
        for index,item in enumerate(left_matches):
            if index not in used_left:pairs.append({"classification":"removed","similarity":None,"left":item,"right":None})
        for index,item in enumerate(right_matches):
            if index not in used_right:pairs.append({"classification":"added","similarity":None,"left":None,"right":item})
        for document in (left,right):document.pop("text_versions",None)
        return {"query":request.query,"left_document":left,"right_document":right,"left_match_count":len(left_matches),"right_match_count":len(right_matches),"pairs":pairs,"method":"literal passage retrieval plus deterministic normalized-text similarity","interpretation":"Wording changes require source review; they do not by themselves establish a relationship change."}

    def relationship_history(self,request: RelationshipHistoryRequest):
        """Build a disclosure timeline from accepted claims without inferring termination."""
        with self.connect() as conn:
            if not self.execute(conn,"SELECT id FROM entity WHERE id=?",(str(request.subject_id),)).fetchone():
                raise KeyError("subject entity not found")
            subject=self.canonical_entity_id(conn,request.subject_id)
            object_id=None
            if request.object_id:
                if not self.execute(conn,"SELECT id FROM entity WHERE id=?",(str(request.object_id),)).fetchone():
                    raise KeyError("object entity not found")
                object_id=self.canonical_entity_id(conn,request.object_id)
            rows=self.execute(conn,"""SELECT c.payload AS claim,e.payload AS evidence,p.payload AS passage,d.payload AS document
                FROM claim_revision c JOIN evidence e ON e.claim_revision_id=c.id
                JOIN passage p ON p.id=e.passage_id JOIN text_version t ON t.id=p.text_version_id
                JOIN document d ON d.id=t.document_id
                WHERE c.review_state='accepted' AND c.assertion_class<>'inferred' AND c.polarity='positive'
                  AND e.assessment='supported' AND c.system_to IS NULL
                ORDER BY d.published_at,c.id,e.id""").fetchall()
            groups={}
            for row in rows:
                claim=ClaimRevision.model_validate_json(row["claim"])
                resolved_subject=self.canonical_entity_id(conn,claim.subject_id)
                resolved_object=self.canonical_entity_id(conn,claim.object_id)
                if resolved_subject!=subject or (object_id and resolved_object!=object_id) or (request.predicate and claim.predicate!=request.predicate):continue
                key=(resolved_subject,claim.predicate,resolved_object)
                evidence=json.loads(row["evidence"]);document=json.loads(row["document"]);passage=json.loads(row["passage"])
                groups.setdefault(key,[]).append({"claim":claim.model_dump(mode="json"),"evidence":evidence,"passage":passage,"document":document})
            entity_ids={value for key in groups for value in (key[0],key[2])}
            entities={}
            if entity_ids:
                placeholders=",".join("?" for _ in entity_ids)
                entities={row["id"]:json.loads(row["payload"]) for row in self.execute(conn,f"SELECT id,payload FROM entity WHERE id IN ({placeholders})",tuple(sorted(entity_ids))).fetchall()}
            timelines=[]
            for key,items in sorted(groups.items(),key=lambda pair:pair[0]):
                previous=None;events=[]
                for item in items:
                    normalized=" ".join(item["evidence"]["quote"].split()).casefold()
                    classification="introduced" if previous is None else ("continued" if normalized==previous else "wording_modified")
                    events.append({"classification":classification,**item})
                    previous=normalized
                timelines.append({"subject":entities[key[0]],"predicate":key[1],"object":entities[key[2]],"events":events})
            return {"timelines":timelines,"requested_subject_id":str(request.subject_id),"subject_id":subject,"classification_method":"The first reviewed disclosure is introduced; later exact normalized quotes are continued; changed quotes are wording_modified.","interpretation":"These labels describe reviewed filing disclosures. Missing disclosure is not classified as relationship termination."}

    def health(self):
        with self.connect() as conn:
            self.execute(conn, "SELECT 1").fetchone()
            row = self.execute(conn, "SELECT version FROM schema_migration WHERE version='010'").fetchone()
            if not row:
                raise RuntimeError("core migration has not been applied")
            pending = self.execute(conn, "SELECT COUNT(*) AS n FROM projection_outbox WHERE state='pending'").fetchone()["n"]
            return {"database":"ok", "migration":"010", "pending_projection_events":pending, "storage_mode":"sqlite_development" if self.fixture_mode else "postgresql"}

    def ingest_company_facts(self,cik,data):
        if str(int(data.get("cik",0)))!=str(int(cik)):raise ValueError("company facts issuer mismatch")
        with self.connect() as conn:
            entity=self.execute(conn,"SELECT id FROM entity WHERE slug=?",("sec-cik-"+str(int(cik)),)).fetchone()
            if not entity:raise KeyError("registered SEC issuer not found")
            inserted=0
            for taxonomy,concepts in data.get("facts",{}).items():
                if not isinstance(concepts,dict):continue
                for concept,definition in concepts.items():
                    for unit,observations in definition.get("units",{}).items():
                        for observation in observations:
                            required=("end","filed","accn","form","val")
                            if any(name not in observation for name in required):continue
                            payload={"entity_id":entity["id"],"taxonomy":taxonomy,"concept":concept,"label":definition.get("label"),"description":definition.get("description"),"unit":unit,**observation,
                                     "source_url":f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(cik):010d}.json"}
                            key=f"{entity['id']}:{taxonomy}:{concept}:{unit}:{observation['end']}:{observation['accn']}"
                            observation_id=str(uuid5(NAMESPACE_URL,"fig:financial-observation:"+key))
                            result=self.execute(conn,"INSERT INTO financial_observation VALUES (?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO NOTHING",
                                (observation_id,entity["id"],taxonomy,concept,unit,observation["end"],observation["filed"],observation["accn"],json.dumps(payload,sort_keys=True)))
                            inserted+=getattr(result,"rowcount",0)
        return {"cik":str(int(cik)),"entity_id":entity["id"],"inserted":inserted}

    def financial_metrics(self,entity_id,concept=None,limit=100):
        with self.connect() as conn:
            canonical=self.canonical_entity_id(conn,entity_id)
            args=[canonical];where="entity_id=?"
            if concept:where+=" AND LOWER(concept)=?";args.append(concept.casefold())
            rows=self.execute(conn,"SELECT id,payload FROM financial_observation WHERE "+where+" ORDER BY period_end DESC,filed_at DESC,id LIMIT ?",(*args,limit)).fetchall()
        return {"entity_id":canonical,"concept":concept,"observations":[{"id":row["id"],**json.loads(row["payload"])} for row in rows],"source":"SEC Company Facts","truncated":len(rows)==limit}


    def ingest_source(self,bundle: SourceBundle,original: bytes,archive_dir: Path):
        self.archive(original,bundle.document.content_hash,archive_dir)
        with self.connect() as conn:
            self.insert_immutable(conn,"entity",bundle.issuer,["kind","canonical_name","slug","status"])
            self.insert_immutable(conn,"document",bundle.document,["issuer_id","source","source_url","accession","filename","published_at","acquired_at","content_hash"])
            self.insert_immutable(conn,"text_version",bundle.text_version,["document_id","parser_version","normalized_hash","normalized_text"])
            for passage in bundle.passages:
                self.insert_immutable(conn,"passage",passage,["text_version_id","start_offset","end_offset","section_path"])
            self.execute(conn,"INSERT INTO ingestion_receipt VALUES (?,?,?) ON CONFLICT(id) DO NOTHING",(str(bundle.text_version.id),str(bundle.document.id),json.dumps(bundle.quality_flags)))
        return {"document_id":str(bundle.document.id),"issuer_id":str(bundle.issuer.id),"text_version_id":str(bundle.text_version.id),"passage_count":len(bundle.passages),"quality_flags":bundle.quality_flags}

    def document(self,document_id):
        with self.connect() as conn:
            row=self.execute(conn,"SELECT payload FROM document WHERE id=?",(str(document_id),)).fetchone()
            if not row:
                raise KeyError("document not found")
            result=Document.model_validate_json(row["payload"]).model_dump(mode="json")
            result["text_versions"]=[{"id":r["id"],"parser_version":r["parser_version"],"quality_flags":json.loads(r["quality_flags"] or "[]"),"passage_count":r["passage_count"]} for r in self.execute(conn,"SELECT t.id,t.parser_version,i.quality_flags,(SELECT COUNT(*) FROM passage p WHERE p.text_version_id=t.id) AS passage_count FROM text_version t LEFT JOIN ingestion_receipt i ON i.id=t.id WHERE t.document_id=? ORDER BY t.id",(str(document_id),)).fetchall()]
            return result

    def documents(self,limit=20,offset=0):
        with self.connect() as conn:
            rows=self.execute(conn,"SELECT payload FROM document ORDER BY published_at DESC,id LIMIT ? OFFSET ?",(limit+1,offset)).fetchall()
            return {"documents":[Document.model_validate_json(r["payload"]).model_dump(mode="json") for r in rows[:limit]],"truncated":len(rows)>limit,"next_offset":offset+limit if len(rows)>limit else None}

    def passages(self,document_id,query="",limit=20,offset=0):
        self.document(document_id)
        with self.connect() as conn:
            result=[]
            skipped=0;matched=0;needle=query.lower()
            versions=self.execute(conn,"SELECT id,normalized_text FROM text_version WHERE document_id=? ORDER BY id",(str(document_id),)).fetchall()
            for version in versions:
                rows=self.execute(conn,"SELECT payload FROM passage WHERE text_version_id=? ORDER BY start_offset",(version["id"],)).fetchall()
                for row in rows:
                    passage=json.loads(row["payload"])
                    text=version["normalized_text"][passage["start_offset"]:passage["end_offset"]]
                    # Slice before lowercasing so Unicode case mappings cannot alter
                    # authoritative source offsets. Search is literal: %, _ and !
                    # have no wildcard meaning.
                    if needle not in text.lower():continue
                    if skipped<offset:skipped+=1;continue
                    matched+=1
                    if matched<=limit:
                        passage["text"]=text;result.append(passage)
                    else:
                        return {"passages":result,"truncated":True,"next_offset":offset+limit}
            return {"passages":result,"truncated":False,"next_offset":None}

    def passage(self,passage_id):
        with self.connect() as conn:
            row=self.execute(conn,"SELECT p.payload,t.normalized_text,t.document_id FROM passage p JOIN text_version t ON t.id=p.text_version_id WHERE p.id=?",(str(passage_id),)).fetchone()
            if not row:
                raise KeyError("passage not found")
            passage=json.loads(row["payload"])
            passage["text"]=row["normalized_text"][passage["start_offset"]:passage["end_offset"]]
            passage["document"]=self.document(row["document_id"])
            return passage


    def entities(self,query="",limit=100,offset=0,include_synthetic=False):
        with self.connect() as conn:
            escaped=query.lower().replace("!","!!").replace("%","!%").replace("_","!_")
            scope="" if include_synthetic else """ AND (
                EXISTS (SELECT 1 FROM document d WHERE d.issuer_id=e.id AND d.source='sec') OR
                EXISTS (SELECT 1 FROM claim_revision c JOIN evidence v ON v.claim_revision_id=c.id
                    JOIN passage p ON p.id=v.passage_id JOIN text_version t ON t.id=p.text_version_id
                    JOIN document d ON d.id=t.document_id
                    WHERE (c.subject_id=e.id OR c.object_id=e.id) AND d.source='sec')
                )"""
            rows=self.execute(conn,"SELECT e.payload FROM entity e WHERE e.kind='Company' AND (LOWER(e.canonical_name) LIKE ? ESCAPE '!' OR EXISTS (SELECT 1 FROM entity_alias a WHERE a.entity_id=e.id AND a.normalized_alias LIKE ? ESCAPE '!') OR EXISTS (SELECT 1 FROM entity_identifier i WHERE i.entity_id=e.id AND LOWER(i.value) LIKE ? ESCAPE '!')) AND NOT EXISTS (SELECT 1 FROM entity_resolution r WHERE r.alias_entity_id=e.id AND r.state='merged')"+scope+" ORDER BY e.canonical_name,e.id LIMIT ? OFFSET ?",("%"+escaped+"%","%"+self.normalize_alias(query).replace("!","!!").replace("%","!%").replace("_","!_")+"%","%"+escaped+"%",limit+1,offset)).fetchall()
            return {"entities":[Entity.model_validate_json(r["payload"]).model_dump(mode="json") for r in rows[:limit]],"truncated":len(rows)>limit,"next_offset":offset+limit if len(rows)>limit else None}
