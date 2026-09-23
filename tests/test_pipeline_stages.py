from datetime import UTC, datetime

import httpx

from thebundl.collection import collect_source, collect_sources, record_successful_processing, should_process_content, successful_content_hashes
from thebundl.config import BARUCH_COLLEGE, COLUMBIA_UNIVERSITY, Settings
from thebundl.deduplication import exact_duplicate
import pytest

from thebundl.discovery import discover_sources, discovery_due, discovery_queries, normalize_url
from thebundl.schemas import DealCandidate, ExtractedPage, Source
from thebundl.validation import GeocodeMatch, validate_candidate


NOW = datetime(2026, 9, 15, tzinfo=UTC)


class FixtureSearch:
    def __init__(self):
        self.queries = []

    def search(self, query, *, count):
        self.queries.append(query)
        return [
            {"url": "https://example.test/offers?branch=lex&utm_source=newsletter", "title": "NYC food deals"},
            {"url": "https://example.test/offers?branch=lex&fbclid=ignore", "title": "More specials"},
        ]


def test_discovery_uses_local_fixture_budget_and_persists_schedule(tmp_path):
    settings = Settings(work_dir=tmp_path, brave_search_budget_usd=5, brave_search_cost_per_request_usd=5)
    search = FixtureSearch()

    sources = discover_sources(settings, 10, search_client=search, now=NOW)

    assert len(sources) == 1
    assert str(sources[0].url) == "https://example.test/offers?branch=lex"
    assert search.queries
    assert any("Baruch College" in query for _, query in discovery_queries())
    assert any("Morningside Heights" in query for _, query in discovery_queries())
    assert not discovery_due(settings, now=NOW)
    assert discover_sources(settings, 10, search_client=search, now=NOW) == []


def test_normalize_url_removes_only_tracking_parameters():
    assert normalize_url("https://EXAMPLE.test/branch?location=5&utm_source=x&gclid=y") == (
        "https://example.test/branch?location=5"
    )


def test_discovery_respects_request_cap_and_reports_traceable_search_errors(tmp_path):
    settings = Settings(work_dir=tmp_path, max_search_requests_per_run=1)
    search = FixtureSearch()
    discover_sources(settings, 10, search_client=search, now=NOW)
    assert len(search.queries) == 1

    class BrokenSearch:
        def search(self, query, *, count):
            raise RuntimeError("fixture outage")

    with pytest.raises(RuntimeError, match="Source discovery failed for query"):
        discover_sources(Settings(work_dir=tmp_path / "broken"), 10, search_client=BrokenSearch(), now=NOW)


def test_collection_uses_html_fixture_and_follows_only_relevant_same_site_links():
    source = Source(url="https://food.test/home", title="Offers", discovered_at=NOW, campus="baruch")
    pages = {
        "/home": '<html><body><a href="/promotions/lunch">Lunch deal</a><a href="https://other.test/deals">Other</a>'
                 '<script type="application/ld+json">{"name":"Cafe"}</script>Home</body></html>',
        "/promotions/lunch": "<html><body>Lunch promotion valid through September 30.</body></html>",
    }

    def handler(request):
        return httpx.Response(200, headers={"content-type": "text/html; charset=utf-8"}, text=pages[request.url.path], request=request)

    resolver = lambda host, port: [(None, None, None, None, ("8.8.8.8", 0))]
    with httpx.Client(transport=httpx.MockTransport(handler)) as client:
        results = collect_sources([source], client=client, resolver=resolver)

    assert len(results) == 2
    assert results[0].page and results[0].page.structured_data == [{"name": "Cafe"}]
    assert results[1].page and "September 30" in results[1].page.text


def test_successful_content_cache_does_not_mark_failed_processing(tmp_path):
    settings = Settings(work_dir=tmp_path)
    assert should_process_content("abc", successful_content_hashes(settings))
    record_successful_processing(settings, "abc")
    assert not should_process_content("abc", successful_content_hashes(settings))
    assert should_process_content("failed", successful_content_hashes(settings))


def test_collection_rejects_private_destinations_without_a_request():
    source = Source(url="http://127.0.0.1/deals", title="Unsafe", discovered_at=NOW, campus="baruch")
    with httpx.Client(transport=httpx.MockTransport(lambda request: AssertionError("must not fetch"))) as client:
        result = collect_source(source, client=client)

    assert result.page is None
    assert result.reason == "unsafe destination"


class FixtureGeocoder:
    def lookup(self, address):
        assert address == "55 Lexington Ave"
        return [GeocodeMatch(address=address, latitude=40.7406, longitude=-73.9832)]


def test_validation_requires_source_evidence_and_source_backed_branch():
    evidence = "Bite Cafe, 55 Lexington Ave: $10 lunch special valid through September 30. Dine-in only."
    candidate = DealCandidate(business_name="Bite Cafe", address="55 Lexington Ave", title="$10 lunch special",
                              description="$10 lunch special valid through September 30.", source_url="https://food.test/deals",
                              evidence_text=evidence, restrictions="Dine-in only.")
    page = ExtractedPage(source_url="https://food.test/deals", text=evidence, links=[], structured_data=[])

    result = validate_candidate(candidate, page, geocoder=FixtureGeocoder(), campuses=(BARUCH_COLLEGE, COLUMBIA_UNIVERSITY))

    assert result.accepted and result.candidate.campus == "baruch" and result.candidate.fingerprint
    assert exact_duplicate(result.candidate, [result.candidate])


def test_validation_rejects_regular_menu_price_without_a_promotion():
    candidate = DealCandidate(business_name="Bite Cafe", address="55 Lexington Ave", title="Lunch menu",
                              description="Lunch costs $10.", source_url="https://food.test/menu",
                              evidence_text="Bite Cafe, 55 Lexington Ave. Lunch costs $10.")
    page = ExtractedPage(source_url="https://food.test/menu", text=candidate.evidence_text, links=[], structured_data=[])

    result = validate_candidate(candidate, page, geocoder=FixtureGeocoder(), campuses=(BARUCH_COLLEGE, COLUMBIA_UNIVERSITY))

    assert not result.accepted
    assert "regular menu item is not an explicit promotion" in result.reasons
