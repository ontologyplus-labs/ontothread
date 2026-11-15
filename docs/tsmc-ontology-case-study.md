# Case study: When a TSMC filing changed the graph

The [offline demo](real-demo.md) helps readers follow company relationships back to
SEC filings. This case from the original OntoThread research asks what happens when
a filing describes a relationship the graph has no way to express.

## The evidence and the gap

In its [Form 20‑F for fiscal 2023](https://www.sec.gov/Archives/edgar/data/1046179/000119312524099840/d592628d20f.htm),
[filed April 18, 2024](https://www.sec.gov/Archives/edgar/data/1046179/000119312524099840/0001193125-24-099840-index.htm)
(accession `0001193125-24-099840`), TSMC describes what it offers in the
“Business Overview of the Company” section. The normalized passage reads:

> We also offer design, mask making, TSMC 3DFabricTM advanced packaging and silicon stacking technologies and testing services.

`finance-v2` could say that a company **uses** a technology. It had no relationship
for a company **providing** advanced packaging technology or services. Using
`USES_TECHNOLOGY` here would change the meaning of TSMC’s disclosure.

## The accepted change

OntoThread recorded the passage as a missing relationship type and linked it to a
proposal: **`Company → PROVIDES_ADVANCED_PACKAGING → Technology`**. The new type
means the company explicitly provides advanced semiconductor packaging technology
or services. Codex accepted the proposal during a development source review, creating
`finance-v3` while preserving `finance-v2` and the claims validated under it.

## What the query returned

The development case asked: **Which reviewed company explicitly provides advanced
packaging technology or services?** It compared the same TSMC relationship query
under both versions. After approval, the reprocessing job targeted three linked
passages and recorded one reviewed relationship.

| Ontology | Matching relationships | Recorded result |
| --- | ---: | --- |
| `finance-v2` | 0 | `unsupported_by_ontology`: the relationship type did not exist. |
| `finance-v3` | 1 | TSMC → `PROVIDES_ADVANCED_PACKAGING` → Advanced Packaging Services, citing the exact passage above. |

The result describes a service TSMC disclosed. It does not say which customers use
the service or how much revenue it generates. This was a development case, without
independent human annotation; it demonstrates the schema change and reprocessing
workflow, rather than a measured improvement in extraction accuracy. The result is
from the original research workspace. The default demo does not seed this case or
install `finance-v3`.
