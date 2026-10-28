# OntoThread by OntologyPlus

**OntologyPlus** is the umbrella brand associated with `ontologyplus.com`.
**OntoThread** is the product, repository name, and Python distribution.
“Financial intelligence graph” describes its initial finance and SEC research capability.

Use this product description:

> OntoThread is an evidence-backed financial intelligence graph by OntologyPlus.
> It turns SEC filings into reviewed relationships and evolving knowledge graphs,
> with traceable source evidence and audited history.

The domain identifies the umbrella brand; this release does not deploy a public
website or change DNS. GitHub publication still requires a confirmed destination
owner; owning the domain does not confer control of the existing GitHub username.

## Compatibility

| Interface | Policy |
| --- | --- |
| Repository and Python distribution | `ontothread` |
| Preferred command | `ontothread` |
| Original command | `fig` remains an alias with identical arguments |
| Python import package and ASGI target | Keep `fig` and `fig.api:app` |
| Configuration | Keep `FIG_*` variables and existing storage defaults |
| API paths and request/response contracts | Keep `/v1` contracts |
| Database schema and ontology versions | Preserve migrations and `finance-v*` identifiers |
| Persistent IDs, source hashes, and historical review records | Preserve exactly, including `fig:` UUID namespaces |

For an existing installation, stop the API, activate its virtual environment, uninstall
`financial-intelligence-graph` if installed, and then install the new source with
`python -m pip install -e ".[dev]"`. Both distributions share `fig` imports and a command
entry point, so uninstall the old distribution **before** installing OntoThread.
Keep the existing database, archive directory, and `.env`; this branding change adds
no database migration. Restart with the same `uvicorn fig.api:app` target.
If moving the checkout, recreate its virtual environment at the new location rather
than reusing scripts containing absolute paths to the previous directory.

## Historical attribution

The original project was named Financial Intelligence Graph. Existing copyright
attribution, source provenance manifests, original fixture IDs, reviewed evidence,
and research references retain that history. The original research workspace is
preserved separately. Branding edits do not rewrite historical evidence or transfer
copyright ownership to the umbrella brand. The MIT license remains unchanged.
