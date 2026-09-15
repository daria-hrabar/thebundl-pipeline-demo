# thebundl-pipeline-demo

`thebundl` is a food-deal pipeline skeleton focused on two-mile straight-line
coverage around Baruch College and Columbia University's Morningside campus in
New York City.

## Setup

Use Python 3.14 or newer. Create a virtual environment, install the package
with its test extras, then copy `.env.example` to `.env` and supply the keys
needed for the command you plan to run. `.env` is ignored by Git.

```powershell
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m thebundl check-config
```

`check-config` reports only whether each setting is present; it never displays
API keys.

## Commands

```powershell
python -m thebundl check-config
python -m thebundl discover --dry-run --limit 10
python -m thebundl run --dry-run --limit 5
python -m thebundl run --publish --limit 5
python -m thebundl run --publish
python -m thebundl report --days 7
```

`limit` bounds the number of source pages processed. `--dry-run` may make API
requests and writes only local output; it never writes to Supabase. A run is
designed to discover sources when due (every 14 days) before daily collection.
All command output is saved under ignored `work/`.

Until pipeline stages are implemented, `discover` and `run` create an artifact,
print their unfinished status, and exit with code 3.

## Current status

This first step provides the package structure, configuration, schemas, CLI,
AI-provider interfaces, SQL schema, and scheduled workflow. Discovery, HTTP
collection, AI extraction, validation, deduplication against stored deals, and
Supabase publishing are intentionally unfinished. Commands state that status
and create an artifact instead of claiming work succeeded or creating deals.

The future implementation will use Brave Search, prioritize aggregator pages,
reuse and deduplicate sources, and extract only HTML text, links, and embedded
structured data. It will use Groq by default behind a swappable provider adapter,
publish only evidence-backed and geographically valid unique candidates to the
separate test Supabase project, and report the actual weekly distinct-deal
count against the target of 10.
