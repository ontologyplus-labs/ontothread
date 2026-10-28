from uuid import UUID
from datetime import datetime
from importlib.resources import files
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi import FastAPI, HTTPException, Query, Request, Depends
from fig.config import Settings
from fig.contracts import NeighborRequest, PathRequest, DocumentComparisonRequest, RelationshipHistoryRequest, ResearchRequest, PassageAnalysisRequest, HybridRetrievalRequest, EventReviewDecision, EntityResolutionDecision, OntologyProposalCreate, OntologyProposalDecision, OntologyProposalRebase, SchemaDiscoveryCreate, ClaimLifecycleDecision
from fig.store import Store, ResolutionConflict, OntologyConflict
from fig.extraction import ReviewQueue, ExtractRequest, Decision, ExtractionError, ReviewConflict, configuration
from typing import Literal
from fig.research import ResearchService
from fig.analysis import PassageAnalyzer
from fig.retrieval import RetrievalService
from fig.schema_pressure import detect_schema_pressure
from fig.events import EventReview,EventReviewConflict


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    store = Store(settings.database_url)
    app = FastAPI(title="OntoThread API", description="OntoThread by OntologyPlus: an evidence-backed financial intelligence graph with evolving ontologies.", version="0.1.0")

    @app.get("/v1/health")
    def health():
        try:
            return store.health()
        except Exception:
            raise HTTPException(503, detail={"code":"dependency_unavailable", "message":"Database unavailable or migrations missing"}) from None

    @app.post("/v1/graph/neighbors")
    def neighbors(request: NeighborRequest):
        try:
            return store.neighbors(request)
        except KeyError:
            raise HTTPException(404, detail={"code":"entity_not_found"}) from None
        except Exception:
            raise HTTPException(503, detail={"code":"dependency_unavailable"}) from None

    @app.post("/v1/graph/paths")
    def paths(request: PathRequest):
        try:return store.paths(request)
        except KeyError as error:raise HTTPException(404,detail={"code":"entity_not_found","message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"code":"invalid_path_request","message":str(error)}) from None
        except Exception:raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.post("/v1/documents/compare")
    def compare_documents(request: DocumentComparisonRequest):
        try:return store.compare_documents(request)
        except KeyError:raise HTTPException(404,detail={"code":"document_not_found"}) from None
        except ValueError as error:raise HTTPException(422,detail={"code":"invalid_comparison","message":str(error)}) from None
        except Exception:raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.post("/v1/relationships/history")
    def relationship_history(request: RelationshipHistoryRequest):
        try:return store.relationship_history(request)
        except KeyError as error:raise HTTPException(404,detail={"code":"entity_not_found","message":str(error)}) from None
        except Exception:raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    research=ResearchService(store)

    @app.post("/v1/research/ask")
    def ask_research(request: ResearchRequest):
        try:return research.ask(request)
        except KeyError as error:raise HTTPException(404,detail={"code":"entity_not_found","message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"code":"unsupported_question","message":str(error)}) from None
        except Exception:raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    analyzer=PassageAnalyzer(store)
    @app.post("/v1/extraction/analyze-passages")
    def analyze_passages(request: PassageAnalysisRequest):
        try:return analyzer.analyze(request.passage_ids)
        except KeyError:raise HTTPException(404,detail={"code":"passage_not_found"}) from None
        except Exception:raise HTTPException(503,detail={"code":"analysis_unavailable"}) from None

    retrieval=RetrievalService(store)
    @app.post("/v1/retrieval/hybrid")
    def hybrid_retrieval(request: HybridRetrievalRequest):
        try:return retrieval.retrieve(request)
        except ValueError as error:raise HTTPException(422,detail={"code":"invalid_retrieval","message":str(error)}) from None
        except Exception:raise HTTPException(503,detail={"code":"retrieval_unavailable"}) from None
    @app.get("/v1/documents")
    def documents(limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0)):
        try:
            return store.documents(limit,offset)
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/documents/{document_id}")
    def document(document_id: UUID):
        try:
            return store.document(document_id)
        except KeyError:
            raise HTTPException(404,detail={"code":"document_not_found"}) from None
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/documents/{document_id}/passages")
    def passages(document_id: UUID,query: str=Query("",max_length=200),limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0)):
        try:
            return store.passages(document_id,query,limit,offset)
        except KeyError:
            raise HTTPException(404,detail={"code":"document_not_found"}) from None
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/passages/{passage_id}")
    def passage(passage_id: UUID):
        try:
            return store.passage(passage_id)
        except KeyError:
            raise HTTPException(404,detail={"code":"passage_not_found"}) from None
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None
    @app.get("/v1/entities")
    def entities(query: str=Query("",max_length=200),limit: int=Query(100,ge=1,le=100),offset: int=Query(0,ge=0),include_synthetic: bool=False):
        try:
            return store.entities(query,limit,offset,include_synthetic)
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/entities/candidates/{mention}")
    def entity_resolution_candidates(mention: str,limit: int=Query(10,ge=1,le=50)):
        try:return store.entity_resolution_candidates(mention,limit)
        except ValueError as error:raise HTTPException(422,detail={"code":"invalid_mention","message":str(error)}) from None

    @app.get("/v1/financial/metrics")
    def financial_metrics(entity_id: UUID,concept: str|None=Query(None,max_length=200),limit: int=Query(100,ge=1,le=500)):
        try:return store.financial_metrics(entity_id,concept,limit)
        except KeyError:raise HTTPException(404,detail={"code":"entity_not_found"}) from None

    @app.get("/v1/entities/{entity_id}/resolution")
    def entity_resolution(entity_id: UUID):
        try:
            return store.resolution_history(entity_id)
        except KeyError:
            raise HTTPException(404,detail={"code":"entity_not_found"}) from None
        except Exception:
            raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/entities/{entity_id}/registry")
    def entity_registry(entity_id: UUID):
        try:return store.entity_registry(entity_id)
        except KeyError:raise HTTPException(404,detail={"code":"entity_not_found"}) from None
        except Exception:raise HTTPException(503,detail={"code":"dependency_unavailable"}) from None

    @app.get("/v1/entities/resolve/{mention}")
    def resolve_entity_mention(mention: str):
        if not mention.strip() or len(mention)>200:raise HTTPException(422,detail={"code":"invalid_mention"})
        return store.resolve_entity_mention(mention)

    queue=ReviewQueue(store,settings.archive_dir)

    def same_origin(request: Request):
        # The local UI may mutate records; cross-site browser requests may not.
        origin=request.headers.get('origin')
        if request.headers.get('sec-fetch-site')=='cross-site' or (origin and origin!=str(request.base_url).rstrip('/')):
            raise HTTPException(403,detail={'message':'Use the application origin for review actions.'})

    event_review=EventReview(store)
    @app.post("/v1/events/analyze",dependencies=[Depends(same_origin)])
    def analyze_event_candidates(body: PassageAnalysisRequest):
        try:return event_review.analyze(body.passage_ids)
        except KeyError:raise HTTPException(404,detail={"message":"Passage not found."}) from None

    @app.get("/v1/events/candidates")
    def event_candidates(state: Literal["pending","accepted","rejected","all"]="pending",limit: int=Query(100,ge=1,le=100),offset: int=Query(0,ge=0)):
        return event_review.list(state,limit,offset)

    @app.post("/v1/events/candidates/{candidate_id}/decisions",dependencies=[Depends(same_origin)])
    def decide_event_candidate(candidate_id: UUID,body: EventReviewDecision):
        try:return event_review.decide(candidate_id,body)
        except KeyError:raise HTTPException(404,detail={"message":"Event candidate not found."}) from None
        except EventReviewConflict as error:raise HTTPException(409,detail={"message":str(error)}) from None

    @app.get("/v1/events/candidates/{candidate_id}/decisions")
    def event_candidate_history(candidate_id: UUID):
        try:return event_review.history(candidate_id)
        except KeyError:raise HTTPException(404,detail={"message":"Event candidate not found."}) from None

    @app.post("/v1/entities/{entity_id}/resolution-decisions",dependencies=[Depends(same_origin)])
    def decide_entity_resolution(entity_id: UUID,body: EntityResolutionDecision):
        try:
            return store.resolve_entity(entity_id,body)
        except KeyError:
            raise HTTPException(404,detail={"message":"Entity not found."}) from None
        except ResolutionConflict as error:
            raise HTTPException(409,detail={"message":str(error)}) from None
        except ValueError as error:
            raise HTTPException(422,detail={"message":str(error)}) from None
        except Exception:
            raise HTTPException(503,detail={"message":"Entity resolution service unavailable."}) from None

    @app.get("/v1/ontology/versions")
    def ontology_versions():
        return store.ontology_versions()

    @app.get("/v1/ontology/schema-pressure")
    def ontology_schema_pressure(min_documents: int=Query(2,ge=2,le=20),example_limit: int=Query(5,ge=1,le=20)):
        return detect_schema_pressure(store,min_documents,example_limit)

    @app.post("/v1/ontology/discoveries",dependencies=[Depends(same_origin)])
    def create_ontology_discovery(body: SchemaDiscoveryCreate):
        try:return store.create_schema_discovery(**body.model_dump())
        except KeyError:raise HTTPException(404,detail={"message":"Passage not found."}) from None
        except ValueError as error:raise HTTPException(422,detail={"message":str(error)}) from None

    @app.get("/v1/ontology/discoveries")
    def ontology_discoveries(state: Literal["pending","linked","rejected","resolved","all"]="all"):
        return store.schema_discoveries(state)

    @app.get("/v1/ontology/reprocessing-jobs")
    def ontology_reprocessing_jobs(status: Literal["pending","running","completed","failed","all"]="all"):
        return store.reprocessing_jobs(status)

    @app.get("/v1/relationships/{relationship_id}/lifecycle")
    def relationship_lifecycle(relationship_id: UUID,knowledge_cutoff: datetime|None=None):
        try:return store.relationship_lifecycle(relationship_id,knowledge_cutoff)
        except KeyError:raise HTTPException(404,detail={"message":"Relationship identity not found."}) from None

    @app.post("/v1/relationships/{relationship_id}/lifecycle-decisions",dependencies=[Depends(same_origin)])
    def decide_relationship_lifecycle(relationship_id: UUID,body: ClaimLifecycleDecision):
        try:return store.record_claim_lifecycle(relationship_id,**body.model_dump())
        except KeyError as error:raise HTTPException(404,detail={"message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"message":str(error)}) from None

    @app.post("/v1/ontology/proposals",dependencies=[Depends(same_origin)])
    def create_ontology_proposal(body: OntologyProposalCreate):
        try:return store.create_ontology_proposal(body)
        except KeyError as error:raise HTTPException(404,detail={"message":str(error)}) from None
        except OntologyConflict as error:raise HTTPException(409,detail={"message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"message":str(error)}) from None

    @app.get("/v1/ontology/proposals")
    def ontology_proposals(state: Literal['pending','accepted','merged','rejected','deferred','all']='all',limit: int=Query(100,ge=1,le=100),offset: int=Query(0,ge=0)):
        return store.ontology_proposals(state,limit,offset)

    @app.get("/v1/ontology/proposals/{proposal_id}")
    def ontology_proposal(proposal_id: UUID):
        try:return store.ontology_proposal(proposal_id)
        except KeyError:raise HTTPException(404,detail={"message":"Ontology proposal not found."}) from None

    @app.post("/v1/ontology/proposals/{proposal_id}/decisions",dependencies=[Depends(same_origin)])
    def decide_ontology_proposal(proposal_id: UUID,body: OntologyProposalDecision):
        try:return store.decide_ontology_proposal(proposal_id,body)
        except KeyError:raise HTTPException(404,detail={"message":"Ontology proposal not found."}) from None
        except OntologyConflict as error:raise HTTPException(409,detail={"message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"message":str(error)}) from None

    @app.post("/v1/ontology/proposals/{proposal_id}/rebase",dependencies=[Depends(same_origin)])
    def rebase_ontology_proposal(proposal_id: UUID,body: OntologyProposalRebase):
        try:return store.rebase_ontology_proposal(proposal_id,body)
        except KeyError as error:raise HTTPException(404,detail={"message":str(error)}) from None
        except OntologyConflict as error:raise HTTPException(409,detail={"message":str(error)}) from None
        except ValueError as error:raise HTTPException(422,detail={"message":str(error)}) from None

    def review_call(operation):
        try:
            return operation()
        except KeyError:
            raise HTTPException(404,detail={'message':'Record not found.'}) from None
        except ReviewConflict as error:
            raise HTTPException(409,detail={'message':str(error)}) from None
        except (ExtractionError,ValueError) as error:
            raise HTTPException(422,detail={'message':str(error)}) from None
        except Exception:
            raise HTTPException(503,detail={'message':'Review service unavailable. Check migrations and archived source files.'}) from None

    @app.get('/v1/extraction/configuration')
    def extraction_configuration():
        return configuration()

    @app.post('/v1/extraction/runs',dependencies=[Depends(same_origin)])
    def extract_candidates(body: ExtractRequest):
        return review_call(lambda:queue.extract(body))

    @app.get('/v1/documents/{document_id}/candidates')
    def candidates(document_id: UUID,state: Literal['pending','accepted','rejected','duplicate','all']='pending',limit: int=Query(20,ge=1,le=100),offset: int=Query(0,ge=0)):
        return review_call(lambda:queue.list(document_id,state,limit,offset))

    @app.post('/v1/candidates/{candidate_id}/decisions',dependencies=[Depends(same_origin)])
    def decide_candidate(candidate_id: UUID,body: Decision):
        return review_call(lambda:queue.decide(candidate_id,body))

    @app.get('/v1/candidates/{candidate_id}/decisions')
    def candidate_history(candidate_id: UUID):
        return review_call(lambda:queue.history(candidate_id))

    web_directory=str(files("fig").joinpath("web"))
    app.mount("/assets",StaticFiles(directory=web_directory),name="assets")

    @app.get("/",include_in_schema=False)
    def analyst_screen():
        return FileResponse(web_directory+"/index.html",headers={"Cache-Control":"no-cache"})
    return app

app = create_app()
