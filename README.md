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
| `python -m thebundl discover --dry-run --limit 10` | Records a bounded source-discovery dry run. |
| `python -m thebundl run --dry-run --limit 5` | Records a no-publish pipeline dry run. |
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
- Geocoding requires a configured, rate-limited provider and cache; ambiguous addresses are rejected.
- Scheduled CLI orchestration and live publication need operational credentials and should be exercised first against the separate test Supabase project.
- Future visual-media analysis could add accessible image metadata or a separately consented vision pipeline, but it must retain source attribution, cost controls, privacy review, and the same evidence/location checks. It is not part of this pipeline today.
