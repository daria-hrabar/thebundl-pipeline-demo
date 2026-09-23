import json
from types import SimpleNamespace

import httpx
import pytest

from thebundl.__main__ import main
from thebundl.config import Settings
from thebundl import collection, discovery, pipeline, storage

PAGE = 'Bite Cafe, 55 Lexington Ave: 20% off lunch through September 30. Dine-in only.'
DEAL = dict(business_name='Bite Cafe', address='55 Lexington Ave', title='20% off lunch',
            description='20% off lunch through September 30.', evidence_text=PAGE, restrictions='Dine-in only.')
GEO = {'@type': 'Restaurant', 'name': 'Bite Cafe', 'address': {'streetAddress': '55 Lexington Ave'},
       'geo': {'latitude': 40.7406, 'longitude': -73.9832}}


@pytest.fixture
def services(monkeypatch, tmp_path):
    settings = Settings(_env_file=None, work_dir=tmp_path, brave_search_api_key='secret-search',
                        groq_api_key='secret-ai', supabase_url='https://test.invalid',
                        supabase_key='secret-db', max_search_requests_per_run=1, domain_pacing_seconds=0)
    monkeypatch.setattr('thebundl.__main__.get_settings', lambda: settings)
    calls = SimpleNamespace(search=0, pages=0, ai=0, inserts=[], existing=set(),
                            fail=None, deals=[DEAL], geo=GEO, sources=1)

    def search(self, query, *, count):
        calls.search += 1
        if calls.fail == 'search':
            raise RuntimeError('secret-search')
        return [{'url': f'https://food.test/deals/{i}', 'title': 'Lunch deals'} for i in range(calls.sources)]

    monkeypatch.setattr(discovery.BraveSearchClient, 'search', search)
    monkeypatch.setattr(collection, '_public_host', lambda *args: True)
    real_client = httpx.Client

    def http(request):
        calls.pages += 1
        if calls.fail == 'http':
            return httpx.Response(503)
        return httpx.Response(200, headers={'content-type': 'text/html'},
                              text=f'<p>{PAGE}</p><a href="/offers/extra">More</a>'
                                   f'<script type="application/ld+json">{json.dumps(calls.geo)}</script>')

    monkeypatch.setattr(httpx, 'Client', lambda **kw: real_client(transport=httpx.MockTransport(http), **kw))

    def completions(**kwargs):
        calls.ai += 1
        if calls.fail == 'ai':
            raise RuntimeError('secret-ai')
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(
            content=json.dumps({'deals': calls.deals})))])

    ai_client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=completions)))
    original = pipeline.GroqExtractor
    monkeypatch.setattr(pipeline, 'GroqExtractor', lambda *a, **kw: original(*a, client=ai_client, **kw))

    class Table:
        def select(self, columns):
            assert columns == 'fingerprint'
            self.rows = None
            return self
        def in_(self, column, values):
            self.values = values
            return self
        def insert(self, rows):
            assert all(set(row) == {'fingerprint', 'title', 'business_name', 'source_url', 'evidence'} for row in rows)
            self.rows = rows
            return self
        def execute(self):
            if calls.fail == 'db' or (calls.fail == 'insert' and self.rows is not None):
                raise RuntimeError('secret-db')
            if self.rows is None:
                return SimpleNamespace(data=[{'fingerprint': value} for value in self.values if value in calls.existing])
            calls.inserts.extend(self.rows)
            calls.existing.update(row['fingerprint'] for row in self.rows)
            return SimpleNamespace(data=self.rows)
    def table(name):
        assert name == 'pipeline_deals'
        return Table()
    monkeypatch.setattr(storage, '_client', lambda settings: SimpleNamespace(table=table))
    return calls, settings


def artifact(settings, command='run'):
    return json.loads(sorted(settings.work_dir.glob(f'*-{command}.json'))[-1].read_text())


def test_check_config_does_not_print_secret(services, capsys):
    assert main(['check-config']) == 0
    assert 'secret-' not in capsys.readouterr().out


def test_discover_executes_and_reuses_schedule(services):
    calls, settings = services
    assert main(['discover', '--dry-run', '--limit', '10']) == 0
    assert artifact(settings, 'discover')['counts']['sources_found'] == 1
    assert calls.search == 1 and calls.ai == 0 and calls.pages == 0 and not calls.inserts
    assert main(['discover', '--dry-run', '--limit', '10']) == 0
    assert calls.search == 1
    assert artifact(settings, 'discover')['discovery_status'] == 'not_due'


def test_dry_run_processes_without_writes(services):
    calls, settings = services
    assert main(['run', '--dry-run', '--limit', '5']) == 0
    result = artifact(settings)
    assert result['counts'] == dict(sources_found=1, pages_fetched=1, pages_reused=0,
                                   candidates_extracted=1, candidates_rejected=0, duplicates=0, deals_inserted=0)
    assert result['accepted'][0]['campus'] == 'baruch'
    assert calls.ai == 1 and not calls.inserts


def test_publish_after_dry_run_reuses_html_and_inserts(services):
    calls, settings = services
    assert main(['run', '--dry-run', '--limit', '5']) == 0
    assert main(['run', '--publish', '--limit', '5']) == 0
    assert calls.pages == 1 and calls.search == 1 and len(calls.inserts) == 1
    assert artifact(settings)['counts']['deals_inserted'] == 1
    assert artifact(settings)['counts']['pages_reused'] == 1
    assert main(['report', '--days', '7']) == 0
    report = json.loads(next(settings.work_dir.glob('*-report.json')).read_text())
    assert report['distinct_new_deals'] == 1


def test_duplicates_not_inserted(services):
    calls, settings = services
    calls.sources = 2
    assert main(['run', '--publish', '--limit', '5']) == 0
    assert len(calls.inserts) == 1
    assert artifact(settings)['counts']['duplicates'] == 1
    assert main(['run', '--publish', '--limit', '5']) == 0
    assert len(calls.inserts) == 1
    assert artifact(settings)['counts']['duplicates'] == 2
    assert artifact(settings)['counts']['deals_inserted'] == 0


@pytest.mark.parametrize('failure,stage', [('search', 'discovery'), ('http', 'collection'),
                                          ('ai', 'extraction'), ('db', 'duplicate lookup'), ('insert', 'publication')])
def test_service_failure_is_clear_and_sanitized(services, capsys, failure, stage):
    calls, settings = services
    calls.fail = failure
    assert main(['run', '--publish', '--limit', '5']) == 1
    result = artifact(settings)
    assert result['status'] == 'failed'
    assert result['errors'][0]['stage'] == stage
    output = capsys.readouterr().out
    assert stage in output and 'secret-' not in output
    assert 'secret-' not in json.dumps(result)
    assert not calls.inserts


def test_limit_caps_actual_pages(services):
    calls, settings = services
    calls.sources = 10
    assert main(['run', '--dry-run', '--limit', '2']) == 0
    assert calls.pages == 2
    assert artifact(settings)['counts']['sources_found'] == 2


def test_missing_branch_coordinates_rejected(services):
    calls, settings = services
    calls.geo = {}
    assert main(['run', '--publish', '--limit', '5']) == 0
    assert artifact(settings)['counts']['candidates_rejected'] == 1
    assert not calls.inserts


def test_ai_evidence_rejection_counted(services):
    calls, settings = services
    calls.deals = [{**DEAL, 'description': 'invented offer'}]
    assert main(['run', '--dry-run', '--limit', '5']) == 0
    counts = artifact(settings)['counts']
    assert counts['candidates_extracted'] == 1 and counts['candidates_rejected'] == 1
    assert not calls.inserts


def test_zero_ai_budget_prevents_calls(services):
    calls, settings = services
    settings.ai_budget_usd = 0
    assert main(['run', '--dry-run', '--limit', '5']) == 1
    assert calls.ai == 0 and calls.pages == 0


def test_dry_run_without_database_credentials(services, monkeypatch):
    calls, settings = services
    settings.supabase_url = None
    settings.supabase_key = None
    def forbidden(*args, **kwargs):
        raise AssertionError('Database must not be contacted without credentials')
    monkeypatch.setattr(storage, '_client', forbidden)
    assert main(['run', '--dry-run', '--limit', '5']) == 0
    assert artifact(settings)['accepted'] and not calls.inserts


def test_daily_failure_does_not_refetch(services):
    calls, settings = services
    calls.fail = 'http'
    assert main(['run', '--dry-run', '--limit', '5']) == 1
    assert main(['run', '--dry-run', '--limit', '5']) == 1
    assert calls.pages == 1


def test_out_of_range_branch_is_rejected(services):
    calls, settings = services
    calls.geo = {**GEO, 'geo': {'latitude': 0, 'longitude': 0}}
    assert main(['run', '--publish', '--limit', '5']) == 0
    assert artifact(settings)['counts']['candidates_rejected'] == 1
    assert not calls.inserts
