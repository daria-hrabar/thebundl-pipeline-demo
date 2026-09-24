# thebundl pipeline demo

---

## Data pipeline

`thebundl` automates web-based food-deal extraction for the two-mile areas around Baruch College and Columbia University's Morningside campus in New York City. It turns publicly available HTML into evidence-backed deal candidates; it does not invent offers or use visual media.

### Flow and tools

1. **Discover sources** — a Brave Search adapter runs targeted, aggregator-focused queries on its 14-day schedule. URL normalization and source deduplication keep reusable pages.
2. **Collect HTML** — `httpx` fetches only public HTTP(S) pages with redirect and content-type checks. Beautiful Soup extracts visible text, links, and JSON-LD. Relevant same-site promotion links are bounded.
3. **Extract candidates** — an AI-provider adapter (Groq by default) receives bounded text chunks and must return strict Pydantic JSON. The extractor verifies exact source excerpts.
4. **Validate and enrich** — Pydantic models enforce shape; source evidence, promotion language, branch resolution, and a Haversine two-mile campus check reject unsafe candidates. A deterministic fingerprint prevents duplicate offers.
5. **Publish and report** — the Supabase boundary checks `pipeline_deals` fingerprints then inserts only schema-compatible rows into the dedicated test project. The weekly report records the actual distinct-new-deal count against the target of 10.

### API controls

Configuration limits Brave search spend and requests, source volume, AI requests, HTTP timeout, per-domain pacing, and provider retries. These limits are safeguards, not a quota target. Secrets come from `.env` and are never printed.

---

## Environment setup

### Local setup and project commands

Use Python 3.14+.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
python -m thebundl check-config
```

| Command | Purpose |
| --- | --- |
| `python -m thebundl check-config` | Shows whether required settings exist without showing values. |
| `python -m thebundl discover --dry-run --limit 10` | Executes bounded discovery and saves sources locally; never writes to Supabase. |
| `python -m thebundl run --dry-run --limit 5` | Executes discovery when due, HTML collection, extraction, validation and deduplication; saves local results. |
| `python -m thebundl run --publish --limit 5` | Runs with publication enabled only when Supabase credentials are configured. |
| `python -m thebundl report --days 7` | Writes the actual-count weekly-report artifact. |

### GitHub Codespaces (`sandbox-dev`)

Use the `sandbox-dev` branch for Codespaces experimentation so production-facing work remains isolated.

```bash
git clone --branch sandbox-dev --single-branch <repository-url>
cd thebundl-pipeline-demo
python3.14 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
pip install codex
codex
```

Add API values as Codespaces secrets or to an uncommitted `.env`; then run `python -m thebundl check-config`. The exact Codex installation package or authentication method can change, so follow the Codex terminal’s current setup guidance if `pip install codex` is unavailable.

---

## Test suite

All tests use mocked Groq, search, HTTP, geocoding, and Supabase responses. They cover source discovery success and caps, safe HTML collection, strict/partial/invalid AI output, evidence semantics, validation, duplicates, persistence mapping, and CLI secret handling.

```powershell
.\.venv\Scripts\python.exe -m pytest
.\.venv\Scripts\python.exe -m pytest tests/test_groq_extractor.py -q
```

---

## Current limitations and improvements

- Input is HTML text, links, and JSON-LD only. JavaScript-rendered content, images, video, PDFs, and OCR are intentionally excluded.
- Branch verification currently uses a matching business name, exact street/full address, and valid coordinates from the collected page’s JSON-LD. Missing or ambiguous matches are rejected. The geocoder interface/cache remain available for a future external provider; no external geocoding service is configured.
- Live CLI execution requires operational credentials. Configure `SUPABASE_URL` and `SUPABASE_KEY` exclusively for the dedicated test project. Publication uses the existing `pipeline_deals` table without schema changes.
- Similar-offer matching is a helper only; this execution path uses exact fingerprints and the database unique constraint, not semantic duplicate classification.

### Execution state and limits

The earlier CLI unconditionally called a placeholder artifact writer and exited with code 3. Discovery, HTML collection, Groq extraction, validation, deduplication and Supabase storage were implemented but disconnected. The daily collector stopped before extraction; geocoding had only a protocol/cache; reporting always returned zero. Commands now execute and exit with code 0 on success or 1 on stage failure. JSON artifacts contain actual counts, accepted/rejected results, and sanitized stage errors. `pages_fetched` counts successfully collected HTML pages; `pages_reused` counts cached pages processed without a new fetch.

`--limit` caps source pages processed (also bounded by `MAX_SOURCES_PER_RUN`). This minimum execution path fetches the selected source pages; it does not recursively fetch promotion links. Discovery runs no more often than every 14 days. Collection attempts are recorded per URL before fetching and run no more often than every 24 hours. Successfully collected pages are reused within that interval, allowing `run --publish` immediately after a dry run. Publishing runs keep failed collection attempts subject to the daily interval. Manual `run --dry-run --limit 5` reruns AI extraction on cached successful HTML. Failed fetches also respect the daily interval. HTTP 401, 403, 404 and 410 put the URL into an automatic cooldown (`SOURCE_COOLDOWN_DAYS`, default 14); cooled-down URLs are skipped before applying the source limit, allowing other known sources to run. URLs remain staged and become eligible again after the cooldown. Run artifacts record skipped URLs and their next eligible time. Per-run API budgets and bounded retries still apply. Disabling an external scheduler does not clear the persisted collection state. Retain the ignored `work/` directory to preserve schedules and local reports. Run one CLI process at a time; local state is not a distributed scheduler.

Dry runs perform real provider requests and may incur costs. They never write to Supabase. With test Supabase credentials they read fingerprints for database duplicate checks; without those credentials they deduplicate within the current run only. Dry-run candidates are not treated as published. Publish checks stored fingerprints and inserts only distinct validated rows. Weekly reports count confirmed inserts recorded in this local work directory, not external database activity.

Set request and monetary limits before execution. `AI_BUDGET_USD` defaults to 1.00 and `AI_COST_PER_REQUEST_USD` to a conservative 0.05 reservation per attempt. Set the latter to an upper bound appropriate to your configured model’s pricing and bounded input/output; it is a configured cost estimate, not live billing data. Every AI attempt, including retries, consumes a reservation and a request slot; output is capped at 4,096 tokens. SDK retries are disabled so only the adapter’s bounded retries apply. Search uses `BRAVE_SEARCH_BUDGET_USD` and `BRAVE_SEARCH_COST_PER_REQUEST_USD` (configure the latter for your plan; its zero default assumes no marginal charge). Search spend and attempts are persisted before requests. Budget exhaustion and service failures are errors, not successful planning artifacts.


### Inspecting sources and run diagnostics

New run artifacts use UTC month-day-process names: `9-23-discovery.json`, `9-23-extraction.json`, and `9-23-report.json`. Additional runs use `-2`, `-3`, etc., so earlier results are retained. The full timestamp, including year, stays inside each artifact. Reports read both the older timestamp-based extraction filenames and the new names. Reusable caches keep their stable names (`known-sources.json`, `discovery-ledger.json`, and `collection-state.json`).

Discovery stages deduplicated source leads in `work/known-sources.json` (or `WORK_DIR/known-sources.json`). Open this readable JSON file to inspect URLs, titles, campus labels, discovery times and priorities before extraction. These are unverified leads, not publishable deals. Keep the file: subsequent runs reuse it rather than repeating search.

`run --dry-run --limit 5` can be repeated for testing and never writes database records. When ready, `run --publish --limit 5` reruns extraction and validation. If any source fails, publication is skipped. After deal publication succeeds, sources supporting validated deals (including already published duplicates) are copied to `pipeline_sources` using only existing schema columns. Sources without qualifying deals stay local. The staging file is retained for reuse; existing database sources are not overwritten. Deal and source writes are separate requests: a source-write failure can occur after deals have been inserted, and the run artifact preserves the confirmed deal count. Rerunning publication retries missing source records without reinserting duplicate deals.

All commands emit flushed UTC progress messages to stderr, including external request starts/responses, AI chunk attempts and retries, cache reuse, and save destinations. HTTP error statuses are reported as collection errors even when a response arrived. Normal summaries remain on stdout.

`pipeline-errors.txt` in the project root is created automatically and appended to for failures, including provider retries, stage failures, invalid arguments, configuration failures and report failures. Each line is JSON text with UTC date, stage, error type and a sanitized description. Raw provider exception bodies and credentials are excluded. A request failure may have both a request-level and a pipeline-stage entry. The log and local artifacts are ignored by Git. Run one command at a time.

Extraction rejections retain the candidate, source URL, chunk, fixed reason code and explanation in the run artifact, including rejections before a later chunk fails. Test error logs are isolated in temporary directories.

Branch verification can reuse business/address/coordinate JSON-LD from cached HTML collected within `BRANCH_CACHE_DAYS` (default 30). Explicit offers applying “at all locations” may use an empty extracted address and expand to verified nearby branches of the same business. “Participating locations,” missing scope, exceptions, ambiguous coordinates and out-of-range branches remain ineligible. Branch evidence URLs are retained in `branch_verifications`; the original offer evidence remains unchanged. This does not infer locations from brand familiarity or add external geocoding requests. Branch pages must already be collected; no verified cached branches means rejection.
