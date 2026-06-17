import pytest
from job_agent.store import Store
from job_agent.models import (
    Company, Job, RoleVariant, Match, Contact, OutreachDraft,
    MatchStatus, DraftType, Confidence,
)

@pytest.fixture
def store(tmp_path):
    return Store(db_path=str(tmp_path / "test.db"))

def test_upsert_company_new(store):
    c = Company(name="Acme AI", source_url="https://acme.com")
    cid = store.upsert_company(c)
    assert isinstance(cid, int) and cid > 0

def test_upsert_company_dedup(store):
    c = Company(name="Acme AI", source_url="https://acme.com")
    id1 = store.upsert_company(c)
    id2 = store.upsert_company(c)
    assert id1 == id2

def test_upsert_job_dedup(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    j = Job(title="Backend Eng", url="https://a.com/jobs/1", company_id=cid)
    id1 = store.upsert_job(j)
    id2 = store.upsert_job(j)
    assert id1 == id2

def test_upsert_role_variant(store):
    rv = RoleVariant(name="backend-eng", resume_path="r.txt", keywords=["python"], seniority="mid")
    rv_id = store.upsert_role_variant(rv)
    assert rv_id > 0
    rv_id2 = store.upsert_role_variant(rv)
    assert rv_id == rv_id2

def test_insert_match_dedup(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    m = Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="good fit")
    mid1 = store.insert_match(m)
    mid2 = store.insert_match(m)
    assert mid1 is not None
    assert mid2 is None  # dedup: same (rv, company, job=None) → skip

def test_get_unscored_companies(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    unscored = store.get_unscored_companies(rv_id)
    assert any(c.id == cid for c in unscored)
    # After inserting a match, it disappears from unscored
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=5, reasoning="ok"))
    assert all(c.id != cid for c in store.get_unscored_companies(rv_id))

def test_get_matches_above_threshold(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="great"))
    cid2 = store.upsert_company(Company(name="Beta", source_url="https://b.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid2, score=3, reasoning="weak"))
    above = store.get_matches_above_threshold(7)
    assert len(above) == 1 and above[0].score == 8

def test_get_contact_for_company(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    assert store.get_contact_for_company(cid) is None
    store.insert_contact(Contact(company_id=cid, name="Alice", title="CEO"))
    c = store.get_contact_for_company(cid)
    assert c is not None and c.name == "Alice"
