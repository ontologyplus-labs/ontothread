import argparse
import json
import os
from pathlib import Path
from fig.config import Settings
from fig.contracts import NeighborRequest
from fig.fixture import fixture, demo_bundles
from fig.store import Store


def main():
    parser = argparse.ArgumentParser(description="OntoThread by OntologyPlus — evidence-backed financial research")
    parser.add_argument("command",choices=["migrate","seed-fixture","demo","project","ingest-sec","ingest-history","ingest-filings","ingest-facts","review-claim","extract","evaluate"])
    parser.add_argument("--cik",default="1045810",help="SEC issuer CIK; default NVIDIA")
    parser.add_argument("--accession",help="Exact annual-filing accession; otherwise latest annual")
    parser.add_argument("--years",type=int,default=3,help="Annual filings for ingest-history; 1 to 10")
    parser.add_argument("--forms",default="10-K,10-Q,8-K,DEF 14A,4,20-F,6-K",help="Comma-separated supported SEC forms for ingest-filings")
    parser.add_argument("--filing-limit",type=int,default=20,help="Maximum filings for ingest-filings; 1 to 100")
    parser.add_argument("--review-file",type=Path,help="Explicit reviewed claim JSON")
    parser.add_argument("--document-id",help="Document to extract candidates from")
    parser.add_argument("--query",default="foundries",help="Literal passage phrase")
    parser.add_argument("--provider",choices=["rules","openai"],default="rules")
    parser.add_argument("--retry-failed",action="store_true")
    parser.add_argument("--dataset",type=Path,default=Path("evaluation/nvidia-pilot.json"))
    parser.add_argument("--report",type=Path,help="Evaluation report JSON path")
    parser.add_argument("--limit",type=int,help="Maximum benchmark cases; default all")
    args = parser.parse_args()
    settings = Settings.from_env()
    store = Store(settings.database_url)
    if args.command == "migrate":
        store.migrate()
        print("Migrations through 010 applied")
    elif args.command == "seed-fixture":
        bundle, original = fixture()
        print(json.dumps(store.ingest(bundle,original,settings.archive_dir),indent=2))
    elif args.command == "demo":
        first = None
        for bundle, original in demo_bundles():
            store.ingest(bundle, original, settings.archive_dir)
            if first is None:
                first = bundle.claim.subject_id
        print(json.dumps(store.neighbors(NeighborRequest(entity_id=first)),indent=2))
    elif args.command=="ingest-facts":
        from fig.sec import SecClient,SecError
        client=None
        try:
            client=SecClient(os.getenv("SEC_USER_AGENT",""),os.getenv("FIG_SEC_CACHE_DIR","data/sec-cache"))
            data=client.json(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{int(args.cik):010d}.json")
            print(json.dumps(store.ingest_company_facts(args.cik,data),indent=2))
        except (ValueError,SecError,KeyError) as error:parser.exit(1,str(error)+"\n")
        finally:
            if client:client.close()
    elif args.command in ("ingest-sec","ingest-history","ingest-filings"):
        from fig.sec import SecClient,SecError
        from fig.ingestion import ingest_annual,ingest_annual_history,ingest_filings
        client=None
        try:
            client=SecClient(os.getenv("SEC_USER_AGENT",""),os.getenv("FIG_SEC_CACHE_DIR","data/sec-cache"))
            if args.command=="ingest-history":
                if args.accession:parser.error("--accession cannot be combined with ingest-history")
                result=ingest_annual_history(client,store,settings.archive_dir,args.cik,args.years)
            elif args.command=="ingest-filings":
                if args.accession:parser.error("--accession cannot be combined with ingest-filings")
                forms=tuple(form.strip().upper() for form in args.forms.split(',') if form.strip())
                result=ingest_filings(client,store,settings.archive_dir,args.cik,forms,args.filing_limit)
            else:result=ingest_annual(client,store,settings.archive_dir,args.cik,args.accession)
            print(json.dumps(result,indent=2))
        except (ValueError,SecError) as error:
            parser.exit(1,str(error)+"\n")
        finally:
            if client:
                client.close()
    elif args.command=="evaluate":
        from fig.evaluation import Dataset,verify_sources,evaluate,write_report
        if args.limit is not None and not 1<=args.limit<=100:
            parser.error("--limit must be between 1 and 100")
        dataset=Dataset.model_validate_json(args.dataset.read_text())
        verify_sources(dataset,store)
        report=evaluate(dataset,args.provider,Path("data/evaluation-cache"),limit=args.limit)
        output=args.report or Path("evaluation/reports")/(args.provider+".json")
        write_report(report,output)
        print(json.dumps({k:report[k] for k in ("provider","model","status","completed_cases","requested_cases","metrics","failure")},indent=2))
        if report["failure"]:parser.exit(1,"Provider failure saved to evaluation report.\n")
    elif args.command=="extract":
        from fig.extraction import ReviewQueue,ExtractRequest,ExtractionError,ReviewConflict
        if not args.document_id or not args.query.strip():
            parser.error("--document-id and a nonempty --query are required")
        try:
            passages=store.passages(args.document_id,args.query,1 if args.provider=="openai" else 5)["passages"]
            if not passages:
                parser.exit(1,"No matching passages.\n")
            result=ReviewQueue(store,settings.archive_dir).extract(ExtractRequest(passage_ids=[p["id"] for p in passages],provider=args.provider,retry_failed=args.retry_failed))
            print(json.dumps(result,indent=2))
        except (ExtractionError,ReviewConflict,KeyError) as error:
            parser.exit(1,str(error)+"\n")
    elif args.command=="review-claim":
        from fig.review import ReviewInput,import_review
        if not args.review_file:
            parser.error("--review-file is required")
        review=ReviewInput.model_validate_json(args.review_file.read_text())
        print(json.dumps(import_review(store,settings.archive_dir,review),indent=2))
    else:
        from fig.projection import project_pending
        password = os.environ.get("FIG_NEO4J_PASSWORD")
        if not password:
            parser.error("FIG_NEO4J_PASSWORD is required")
        print(json.dumps({"delivered":project_pending(store,os.getenv("FIG_NEO4J_URI","bolt://localhost:7687"),os.getenv("FIG_NEO4J_USER","neo4j"),password)}))

if __name__ == "__main__":
    main()
