# tests/test_sourcing.py
import json
import pytest
from unittest.mock import MagicMock
from prospector.stages.sourcing import run_sourcing
from prospector.store import Store
from prospector.llm.client import LLMClient
from prospector.config import RoleVariantConfig, SourcingConfig
from prospector.models import RawResult, RoleVariant

RV = RoleVariantConfig(name="be", resume="r.txt", keywords=["python"], seniority="mid")
CFG = SourcingConfig(max_queries_per_role_per_run=2, funding_lookback_days=30)


class FixtureConnector:
    connector_type = "funding_news"

    def __init__(self, results):
        self._results = results

    def search(self, query):
        return self._results


def _make_llm(call_responses: list[str], call_json_responses: list[dict]):
    llm = MagicMock(spec=LLMClient)
    llm.is_over_budget.return_value = False
    call_iter = iter(call_responses)
    json_iter = iter(call_json_responses)
    llm.call.side_effect = lambda s, u, **kw: next(call_iter, "fallback query")
    llm.call_json.side_effect = lambda s, u: next(json_iter, {"relevant": False})
    return llm


def test_sourcing_writes_company_to_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=["python"], seniority="mid")
    )
    connector = FixtureConnector([
        RawResult(url="https://tc.com/acme", title="Acme raises $5M", snippet="Acme AI raised Seed"),
    ])
    llm = _make_llm(
        call_responses=["site:techcrunch.com python startup 2026"],
        call_json_responses=[
            {"relevant": True, "company": {"name": "Acme AI", "funding_stage": "Seed",
             "funding_amount": "$5M", "funding_date": "2026-06"}, "job": None},
        ],
    )
    counts = run_sourcing(role_variant=RV, role_variant_id=rv_id,
                          connectors=[connector], llm=llm, store=store, config=CFG)
    assert counts["companies"] >= 1
    companies = store.get_unscored_companies(rv_id)
    assert any("Acme" in c.name for c in companies)


def test_sourcing_deduplicates(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    connector = FixtureConnector([
        RawResult(url="https://tc.com/acme", title="Acme raises", snippet="..."),
    ])
    extract = {"relevant": True, "company": {"name": "Acme AI", "funding_stage": "Seed",
               "funding_amount": "$5M", "funding_date": "2026-06"}, "job": None}
    llm = _make_llm(
        call_responses=["q1", "q2", "q3", "q4"],
        call_json_responses=[extract, extract, extract, extract],
    )
    run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[connector], llm=llm, store=store, config=CFG)
    run_sourcing(role_variant=RV, role_variant_id=rv_id, connectors=[connector], llm=llm, store=store, config=CFG)
    with store._conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM companies WHERE name='Acme AI'").fetchone()[0]
    assert count == 1


def test_sourcing_respects_iteration_cap(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    call_tracker = {"n": 0}

    class CountingConnector:
        connector_type = "funding_news"

        def search(self, query):
            call_tracker["n"] += 1
            return []

    llm = _make_llm(call_responses=["q"] * 10, call_json_responses=[])
    cfg = SourcingConfig(max_queries_per_role_per_run=3, funding_lookback_days=30)
    run_sourcing(role_variant=RV, role_variant_id=rv_id,
                 connectors=[CountingConnector()], llm=llm, store=store, config=cfg)
    assert call_tracker["n"] == 3


def test_sourcing_skips_irrelevant_results(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    connector = FixtureConnector([RawResult(url="https://x.com", title="Noise", snippet="unrelated")])
    llm = _make_llm(
        call_responses=["query"],
        call_json_responses=[{"relevant": False, "company": None, "job": None}],
    )
    counts = run_sourcing(role_variant=RV, role_variant_id=rv_id,
                          connectors=[connector], llm=llm, store=store, config=CFG)
    assert counts["companies"] == 0
