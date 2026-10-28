"""Deterministic synthetic fixture: deliberately contains no real company claims."""
from datetime import datetime, timezone
from hashlib import sha256
from uuid import uuid5, NAMESPACE_URL
from fig.contracts import ReviewedBundle

def fixture():
    def uid(name):
        return str(uuid5(NAMESPACE_URL, "fig:synthetic:"+name))
    original = "Business\nExample Designer contracts manufacturing to Example Foundry.\n".encode()
    text = original.decode()
    quote = "Example Designer contracts manufacturing to Example Foundry."
    start = text.index(quote)
    return ReviewedBundle.model_validate({
        "entities":[{"id":uid("designer"),"kind":"Company","canonical_name":"Example Designer","slug":"example-designer"}, {"id":uid("foundry"),"kind":"Company","canonical_name":"Example Foundry","slug":"example-foundry"}],
        "document":{"id":uid("document"),"issuer_id":uid("designer"),"source":"synthetic_fixture","source_url":"https://example.invalid/synthetic-fixture","accession":"synthetic-001","filename":"synthetic.txt","form":"SYNTHETIC","published_at":"2025-01-01T00:00:00Z","acquired_at":"2025-01-02T00:00:00Z","content_hash":sha256(original).hexdigest()},
        "text_version":{"id":uid("text"),"document_id":uid("document"),"parser_version":"fixture-v1","normalized_hash":sha256(original).hexdigest(),"normalized_text":text},
        "passage":{"id":uid("passage"),"text_version_id":uid("text"),"section_path":"Business","start_offset":start,"end_offset":start+len(quote)},
        "claim":{"id":uid("claim-revision-1"),"claim_id":uid("claim"),"subject_id":uid("designer"),"object_id":uid("foundry"),"predicate":"CONTRACTS_MANUFACTURING_TO","review_state":"accepted","source_available_at":"2025-01-01T00:00:00Z","system_from":"2025-01-02T00:00:00Z","reviewer":"synthetic-test-author"},
        "evidence":{"id":uid("evidence"),"claim_revision_id":uid("claim-revision-1"),"passage_id":uid("passage"),"quote":quote,"start_offset":start,"end_offset":start+len(quote),"assessment":"supported"}
    }), original


def demo_bundles():
    """Offline walkthrough; deterministic records preserve decisions across reseeding.

    The minimal fixture() remains unchanged for API and integration consumers.
    All new source text and company relationships here are deliberately fictional.
    """
    from copy import deepcopy

    base, _ = fixture()
    def uid(name):
        return str(uuid5(NAMESPACE_URL, "fig:demo:v1:" + name))

    companies = {e.canonical_name: e.model_dump(mode="json") for e in base.entities}
    for name in ("Example Packaging", "Example Customer"):
        companies[name] = {"id": uid(name), "kind": "Company", "canonical_name": name,
                           "slug": name.lower().replace(" ", "-")}
    rows = [
        ("Example Designer", "Example Foundry", "CONTRACTS_MANUFACTURING_TO",
         "Example Designer contracts manufacturing to Example Foundry.",
         "We utilize foundries, such as Example Fabrication Limited, and Example Assembly Limited, to produce our semiconductor wafers."),
        ("Example Foundry", "Example Packaging", "CONTRACTS_MANUFACTURING_TO",
         "Example Foundry contracts manufacturing to Example Packaging.", ""),
        ("Example Packaging", "Example Customer", "SUPPLIES_TO",
         "Example Packaging supplies Example Customer.", ""),
    ]
    for index, (subject, target, predicate, quote, pending) in enumerate(rows):
        text = "Fictional demonstration — no real company claims.\nBusiness\n" + quote
        if pending:
            text += "\n" + pending
        text += "\n"
        original = text.encode()
        data = deepcopy(base.model_dump(mode="json"))
        data["entities"] = [companies[subject], companies[target]]
        document_id, text_id, passage_id = (uid(f"{index}:{kind}") for kind in ("document", "text", "passage"))
        claim_id = uid(f"{index}:claim-revision")
        data["document"].update(id=document_id, issuer_id=companies[subject]["id"],
            accession=f"synthetic-demo-{index + 1:03d}", filename="synthetic-demo.txt",
            source_url=f"https://example.invalid/fig-demo/{index + 1}",
            content_hash=sha256(original).hexdigest())
        data["text_version"].update(id=text_id, document_id=document_id, parser_version="demo-v1",
            normalized_hash=sha256(original).hexdigest(), normalized_text=text)
        data["passage"].update(id=passage_id, text_version_id=text_id, start_offset=0, end_offset=len(text))
        data["claim"].update(id=claim_id, claim_id=uid(f"{index}:relationship"),
            subject_id=companies[subject]["id"], object_id=companies[target]["id"],
            predicate=predicate, reviewer="synthetic-demo-author")
        start = text.index(quote)
        data["evidence"].update(id=uid(f"{index}:evidence"), claim_revision_id=claim_id,
            passage_id=passage_id, quote=quote, start_offset=start, end_offset=start + len(quote))
        yield ReviewedBundle.model_validate(data), original
