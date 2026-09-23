from types import SimpleNamespace

import pytest

from thebundl.config import Settings
from thebundl.schemas import DealCandidate
from thebundl.storage import deal_row, publish_candidates


def candidate():
    return DealCandidate(business_name="Bite Cafe", address="55 Lexington Ave", title="Lunch special",
                         description="Lunch special", source_url="https://food.test/deals", evidence_text="proof",
                         fingerprint="abc")


def test_database_row_matches_pipeline_deals_sql_columns_exactly():
    assert deal_row(candidate()) == {"fingerprint": "abc", "title": "Lunch special",
                                     "business_name": "Bite Cafe", "source_url": "https://food.test/deals",
                                     "evidence": "proof"}


def test_publish_uses_mocked_supabase_and_skips_existing_fingerprints():
    class Table:
        def select(self, columns): assert columns == "fingerprint"; return self
        def in_(self, column, values): assert column == "fingerprint"; return self
        def execute(self): return SimpleNamespace(data=[{"fingerprint": "abc"}])
        def insert(self, rows): raise AssertionError("existing deal must not be inserted")
    client = SimpleNamespace(table=lambda name: Table())
    assert publish_candidates(Settings(), [candidate()], client=client) == 0


def test_unfingerprinted_candidate_is_rejected_before_any_api_call():
    with pytest.raises(ValueError, match="fingerprint"):
        deal_row(candidate().model_copy(update={"fingerprint": None}))
