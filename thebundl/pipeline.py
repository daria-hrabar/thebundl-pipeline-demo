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
from .storage import existing_fingerprints, publish_candidates, publish_sources
from .observability import progress, record_error
from .validation import validate_with_branch_pages


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(payload, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)
    progress(f"Saved {path}")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}


def artifact_path(work_dir: Path, now: datetime, process: str) -> Path:
    """Readable UTC dates; retain repeated runs instead of overwriting them."""
    stem = f'{now.month}-{now.day}-{process}'
    path = work_dir / f'{stem}.json'
    sequence = 2
    while path.exists():
        path = work_dir / f'{stem}-{sequence}.json'
        sequence += 1
    return path


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
    process = {'discover': 'discovery', 'run': 'extraction'}[command]
    path = artifact_path(settings.work_dir, now, process)
    counts = dict.fromkeys(('sources_found', 'pages_fetched', 'pages_reused', 'candidates_extracted',
                            'candidates_rejected', 'duplicates', 'deals_inserted'), 0)
    payload = {'timestamp': now.isoformat(), 'command': command, 'limit': limit,
               'publish_requested': publish, 'status': 'running', 'counts': counts,
               'errors': [], 'sources': [], 'accepted': [], 'rejected': [], 'branch_verifications': []}
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
        progress(f"Discovery: {payload['discovery_status']}; source staging file: {settings.work_dir / 'known-sources.json'}")
        state_path = settings.work_dir / 'collection-state.json'
        state = _read(state_path)
        payload['skipped_sources'] = []
        eligible = []
        for source in sorted(known_sources(settings), key=lambda source: source.priority, reverse=True):
            entry = state.get(str(source.url), {})
            until = entry.get('cooldown_until')
            if until and now < datetime.fromisoformat(until):
                payload['skipped_sources'].append(dict(source_url=str(source.url),
                    reason_code=entry.get('failure_reason'), retry_after=until))
            else:
                eligible.append(source)
        sources = eligible[:limit]
        payload['sources'] = [source.model_dump(mode='json') for source in sources]
        if command == 'run':
            stage = 'extraction configuration'
            extractor = make_extractor(settings)
            accepted = []
            successful_sources = []
            state_path = settings.work_dir / 'collection-state.json'
            state = _read(state_path)
            last_fetch = {}
            with httpx.Client(timeout=settings.http_timeout_seconds) as client:
                for source_index, source in enumerate(sources, start=1):
                    url = str(source.url)
                    stage = 'collection'
                    entry = state.get(url)
                    progress(f'Processing source {source_index}/{len(sources)}')
                    if entry and now - datetime.fromisoformat(entry['attempted_at']) < timedelta(hours=settings.collection_interval_hours):
                        if not entry.get('page'):
                            payload['errors'].append({'stage': stage, 'error_type': 'CollectionIntervalError', 'source_url': url,
                                                      'message': 'Previous collection failed; next attempt allowed after daily interval'})
                            continue
                        page = ExtractedPage.model_validate(entry['page'])
                        counts['pages_reused'] += 1
                        progress('Reusing cached HTML; extraction will run again')
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
                            state[url]['failure_reason'] = result.reason
                            if result.reason in {'HTTP 401', 'HTTP 403', 'HTTP 404', 'HTTP 410'}:
                                state[url]['cooldown_until'] = (now + timedelta(days=settings.source_cooldown_days)).isoformat()
                            _write(state_path, state)
                            payload['errors'].append({'stage': stage, 'error_type': 'CollectionError', 'source_url': url, 'message': result.reason})
                            continue
                        page = result.page
                        counts['pages_fetched'] += 1
                        state[url]['page'] = page.model_dump(mode='json')
                        _write(state_path, state)
                    stage = 'extraction'
                    before = {key: getattr(extractor, key, 0) for key in
                              ('candidates_extracted', 'candidates_rejected', 'duplicates')}
                    rejection_start = len(getattr(extractor, 'rejections', []))
                    try:
                        candidates = extractor.extract(page.text, str(page.source_url))
                    except Exception as error:
                        payload['errors'].append({'stage': stage, 'error_type': type(error).__name__, 'source_url': url,
                                                  'message': f'{type(error).__name__}; check AI credentials, model, service availability and request budget'})
                        continue
                    finally:
                        payload['rejected'].extend(getattr(extractor, 'rejections', [])[rejection_start:])
                        payload['ai_requests_used'] = getattr(extractor, 'requests_used', 0)
                        payload['ai_reserved_cost_usd'] = payload['ai_requests_used'] * settings.ai_cost_per_request_usd
                        for key, value in before.items():
                            counts[key] += getattr(extractor, key, 0) - value
                    successful_sources.append(source.model_copy(update={"url": page.source_url}))
                    progress(f'Extraction returned {len(candidates)} candidates; validating evidence and location')
                    if not hasattr(extractor, 'candidates_extracted'):
                        counts['candidates_extracted'] += len(candidates)
                    for candidate in candidates:
                        stage = 'validation'
                        branch_pages = [ExtractedPage.model_validate(item['page']) for item in state.values()
                            if item.get('page') and now - datetime.fromisoformat(item['attempted_at'])
                            < timedelta(days=settings.branch_cache_days)]
                        for result in validate_with_branch_pages(candidate, page, branch_pages, settings.campuses):
                            if not result.accepted:
                                counts['candidates_rejected'] += 1
                                rejection = result.model_dump(mode='json')
                                rejection.update(stage='validation', source_url=str(page.source_url))
                                payload['rejected'].append(rejection)
                            elif exact_duplicate(result.candidate, accepted):
                                counts['duplicates'] += 1
                            else:
                                accepted.append(result.candidate)
                                if result.branch_evidence_urls:
                                    payload['branch_verifications'].append(dict(fingerprint=result.candidate.fingerprint,
                                        source_urls=result.branch_evidence_urls))
            payload['accepted'] = [deal.model_dump(mode='json') for deal in accepted]
            validated_urls = {str(deal.source_url) for deal in accepted}
            stage = 'duplicate lookup'
            # Dry runs may read existing fingerprints when test credentials are present.
            if accepted and settings.supabase_url and settings.supabase_key is not None:
                existing = existing_fingerprints(settings, [deal.fingerprint for deal in accepted])
                counts['duplicates'] += sum(deal.fingerprint in existing for deal in accepted)
                accepted = [deal for deal in accepted if deal.fingerprint not in existing]
            payload['accepted'] = [deal.model_dump(mode='json') for deal in accepted]
            if publish and not payload['errors']:
                stage = 'publication'
                counts['deals_inserted'] = publish_candidates(settings, accepted)
                counts['duplicates'] += len(accepted) - counts['deals_inserted']
                stage = 'source publication'
                payload['sources_published'] = publish_sources(settings, [source for source in successful_sources
                    if str(source.url) in validated_urls])
        payload['status'] = 'failed' if payload['errors'] else 'completed'
    except Exception as error:
        # Provider exception bodies can contain credentials or request headers.
        hints = {'discovery': 'check Brave credentials, service availability and search budget',
                 'extraction configuration': 'check AI_PROVIDER, GROQ_API_KEY and AI budget',
                 'configuration': 'check test SUPABASE_URL and SUPABASE_KEY',
                 'duplicate lookup': 'check test Supabase access and pipeline_deals schema',
                 'source publication': 'check test Supabase insert permissions and pipeline_sources schema; rerun publication to retry missing source records',
                 'publication': 'check test Supabase insert permissions and pipeline_deals schema; an interrupted insert may have an unknown outcome'}
        payload['errors'].append({'stage': stage, 'error_type': type(error).__name__, 'message': f'{type(error).__name__}; {hints.get(stage, "check local state and stage configuration")}'})
        payload['status'] = 'failed'
    for error in payload['errors']:
        record_error(error['stage'], error['error_type'], error['message'])
    _write(path, payload)
    return path, payload


def weekly_report(settings: Settings, days: int) -> Path:
    now = datetime.now(UTC)
    paths = set(settings.work_dir.glob('*-run.json'))
    paths.update(settings.work_dir.glob('*-extraction.json'))
    paths.update(settings.work_dir.glob('*-extraction-*.json'))
    records = [_read(path) for path in paths]
    records = [record for record in records if datetime.fromisoformat(record['timestamp']) >= now - timedelta(days=days)]
    count = sum(record.get('counts', {}).get('deals_inserted', 0) for record in records)
    path = artifact_path(settings.work_dir, now, 'report')
    _write(path, {'timestamp': now.isoformat(), 'status': 'completed', 'days': days,
                  'distinct_new_deals': count, 'target_distinct_new_deals_per_week': 10,
                  'scope': 'confirmed inserts recorded in this local work directory'})
    return path
