"""Bounded execution, local artifacts, and daily HTML reuse."""
from __future__ import annotations

import json
import time
from urllib.parse import urlsplit
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

from .ai.groq_provider import GroqExtractor
from .collection import collect_sources
from .config import Settings
from .deduplication import exact_duplicate
from .discovery import discover_sources, discovery_due, known_sources
from .schemas import ExtractedPage
from .storage import existing_fingerprints, publish_candidates
from .validation import StructuredDataGeocoder, validate_candidate


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def make_extractor(settings: Settings):
    """Provider selection stays at the adapter boundary."""
    if settings.ai_provider != 'groq':
        raise RuntimeError('Unsupported AI_PROVIDER; configure an installed extractor adapter')
    if settings.groq_api_key is None:
        raise RuntimeError('GROQ_API_KEY is required for extraction')
    requests = min(settings.max_ai_requests_per_run,
                   int(settings.ai_budget_usd / settings.ai_cost_per_request_usd))
    if requests < 1:
        raise RuntimeError('AI budget exhausted; check AI request and monetary limits')
    return GroqExtractor(settings.groq_api_key.get_secret_value(), model=settings.ai_model,
                         max_requests=requests)


def execute_pipeline(settings: Settings, command: str, *, limit: int | None, publish: bool) -> tuple[Path, dict]:
    now = datetime.now(UTC)
    path = settings.work_dir / f'{now:%Y%m%dT%H%M%S%fZ}-{command}.json'
    counts = dict.fromkeys(('sources_found', 'pages_fetched', 'pages_reused', 'candidates_extracted',
                            'candidates_rejected', 'duplicates', 'deals_inserted'), 0)
    payload = {'timestamp': now.isoformat(), 'command': command, 'limit': limit,
               'publish_requested': publish, 'status': 'running', 'counts': counts,
               'errors': [], 'sources': [], 'accepted': [], 'rejected': []}
    stage = 'configuration'
    limit = min(limit or settings.max_sources_per_run, settings.max_sources_per_run)
    try:
        if publish and (not settings.supabase_url or settings.supabase_key is None):
            raise RuntimeError('Publishing requires SUPABASE_URL and SUPABASE_KEY for the test project')
        stage = 'discovery'
        due = discovery_due(settings)
        found = discover_sources(settings, limit) if due else []
        counts['sources_found'] = len(found)
        payload['discovery_status'] = 'executed' if due else 'not_due'
        sources = sorted(known_sources(settings), key=lambda source: source.priority, reverse=True)[:limit]
        payload['sources'] = [source.model_dump(mode='json') for source in sources]
        if command == 'run':
            stage = 'extraction configuration'
            extractor = make_extractor(settings)
            accepted = []
            state_path = settings.work_dir / 'collection-state.json'
            state = _read(state_path)
            last_fetch = {}
            with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                for source in sources:
                    url = str(source.url)
                    stage = 'collection'
                    entry = state.get(url)
                    if entry and now - datetime.fromisoformat(entry['attempted_at']) < timedelta(hours=settings.collection_interval_hours):
                        if not entry.get('page'):
                            payload['errors'].append({'stage': stage, 'source_url': url,
                                                      'message': 'Previous collection failed; next attempt allowed after daily interval'})
                            continue
                        page = ExtractedPage.model_validate(entry['page'])
                        counts['pages_reused'] += 1
                    else:
                        state[url] = {'attempted_at': now.isoformat(), 'page': None}
                        _write(state_path, state)  # Reserve the daily attempt before network I/O.
                        domain = urlsplit(url).hostname
                        delay = settings.domain_pacing_seconds - (time.monotonic() - last_fetch.get(domain, float("-inf")))
                        if delay > 0:
                            time.sleep(delay)
                        result = collect_sources([source], client=client, maximum_links=0,
                                                 pace_seconds=settings.domain_pacing_seconds)[0]
                        last_fetch[domain] = time.monotonic()
                        if result.page is None:
                            payload['errors'].append({'stage': stage, 'source_url': url, 'message': result.reason})
                            continue
                        page = result.page
                        counts['pages_fetched'] += 1
                        state[url]['page'] = page.model_dump(mode='json')
                        _write(state_path, state)
                    stage = 'extraction'
                    before = {key: getattr(extractor, key, 0) for key in
                              ('candidates_extracted', 'candidates_rejected', 'duplicates')}
                    try:
                        candidates = extractor.extract(page.text, str(page.source_url))
                    except Exception as error:
                        payload['errors'].append({'stage': stage, 'source_url': url,
                                                  'message': f'{type(error).__name__}; check AI credentials, model, service availability and request budget'})
                        continue
                    finally:
                        payload['ai_requests_used'] = getattr(extractor, 'requests_used', 0)
                        payload['ai_reserved_cost_usd'] = payload['ai_requests_used'] * settings.ai_cost_per_request_usd
                        for key, value in before.items():
                            counts[key] += getattr(extractor, key, 0) - value
                    if not hasattr(extractor, 'candidates_extracted'):
                        counts['candidates_extracted'] += len(candidates)
                    for candidate in candidates:
                        stage = 'validation'
                        result = validate_candidate(candidate, page,
                            geocoder=StructuredDataGeocoder(page, candidate.business_name), campuses=settings.campuses)
                        if not result.accepted:
                            counts['candidates_rejected'] += 1
                            payload['rejected'].append(result.model_dump(mode='json'))
                        elif exact_duplicate(result.candidate, accepted):
                            counts['duplicates'] += 1
                        else:
                            accepted.append(result.candidate)
            payload['accepted'] = [deal.model_dump(mode='json') for deal in accepted]
            stage = 'duplicate lookup'
            # Dry runs may read existing fingerprints when test credentials are present.
            if accepted and settings.supabase_url and settings.supabase_key is not None:
                existing = existing_fingerprints(settings, [deal.fingerprint for deal in accepted])
                counts['duplicates'] += sum(deal.fingerprint in existing for deal in accepted)
                accepted = [deal for deal in accepted if deal.fingerprint not in existing]
            payload['accepted'] = [deal.model_dump(mode='json') for deal in accepted]
            if publish:
                stage = 'publication'
                counts['deals_inserted'] = publish_candidates(settings, accepted)
                counts['duplicates'] += len(accepted) - counts['deals_inserted']
        payload['status'] = 'failed' if payload['errors'] else 'completed'
    except Exception as error:
        # Provider exception bodies can contain credentials or request headers.
        hints = {'discovery': 'check Brave credentials, service availability and search budget',
                 'extraction configuration': 'check AI_PROVIDER, GROQ_API_KEY and AI budget',
                 'configuration': 'check test SUPABASE_URL and SUPABASE_KEY',
                 'duplicate lookup': 'check test Supabase access and pipeline_deals schema',
                 'publication': 'check test Supabase insert permissions and pipeline_deals schema; an interrupted insert may have an unknown outcome'}
        payload['errors'].append({'stage': stage, 'message': f'{type(error).__name__}; {hints.get(stage, "check local state and stage configuration")}'})
        payload['status'] = 'failed'
    _write(path, payload)
    return path, payload


def weekly_report(settings: Settings, days: int) -> Path:
    now = datetime.now(UTC)
    records = [_read(path) for path in settings.work_dir.glob('*-run.json')]
    records = [record for record in records if datetime.fromisoformat(record['timestamp']) >= now - timedelta(days=days)]
    count = sum(record.get('counts', {}).get('deals_inserted', 0) for record in records)
    path = settings.work_dir / f'{now:%Y%m%dT%H%M%S%fZ}-report.json'
    _write(path, {'timestamp': now.isoformat(), 'status': 'completed', 'days': days,
                  'distinct_new_deals': count, 'target_distinct_new_deals_per_week': 10,
                  'scope': 'confirmed inserts recorded in this local work directory'})
    return path
