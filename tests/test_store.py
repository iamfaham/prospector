import pytest
from prospector.store import Store
from prospector.models import (
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
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="great"))
    cid2 = store.upsert_company(Company(name="Beta", source_url="https://b.com"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid2, score=3, reasoning="weak"))
    # new matches are not returned — must be accepted first
    assert store.get_matches_above_threshold(7) == []
    store.update_match_status(mid, MatchStatus.ACCEPTED)
    above = store.get_matches_above_threshold(7)
    assert len(above) == 1 and above[0].score == 8


def test_update_match_status(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="great"))
    store.update_match_status(mid, MatchStatus.ACCEPTED)
    above = store.get_matches_above_threshold(7)
    assert above[0].status == MatchStatus.ACCEPTED
    store.update_match_status(mid, MatchStatus.REJECTED)
    assert store.get_matches_above_threshold(7) == []


def test_get_matches_for_review(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com",
                                       funding_stage="Seed", funding_amount="$5M"))
    store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="great"))
    pending = store.get_matches_for_review(7)
    assert len(pending) == 1
    assert pending[0]["company_name"] == "Acme"
    assert pending[0]["score"] == 8
    assert pending[0]["funding_stage"] == "Seed"
    # after accepting, it no longer shows in review
    store.update_match_status(pending[0]["id"], MatchStatus.ACCEPTED)
    assert store.get_matches_for_review(7) == []

def test_get_accepted_matches_needing_draft(store):
    rv_id = store.upsert_role_variant(RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid"))
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    mid = store.insert_match(Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="good"))
    # new status — not returned
    assert store.get_accepted_matches_needing_draft(7) == []
    store.update_match_status(mid, MatchStatus.ACCEPTED)
    # accepted, no draft yet — returned
    pending = store.get_accepted_matches_needing_draft(7)
    assert len(pending) == 1 and pending[0]["company_name"] == "Acme"
    # insert a draft — no longer returned
    from prospector.models import ResumeDraft
    store.insert_resume_draft(ResumeDraft(match_id=mid, role_variant_id=rv_id,
                                          company_name="Acme", job_title=None, tailored_text="resume text"))
    assert store.get_accepted_matches_needing_draft(7) == []


def test_get_contact_for_company(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://a.com"))
    assert store.get_contact_for_company(cid) is None
    store.insert_contact(Contact(company_id=cid, name="Alice", title="CEO"))
    c = store.get_contact_for_company(cid)
    assert c is not None and c.name == "Alice"


def test_get_matches_for_review_dedup(store):
    """Same company matched by two variants — only the higher-scoring one appears in review."""
    cid = store.upsert_company(Company(name="Acme", source_url="https://acme.com"))
    rv1 = store.upsert_role_variant(RoleVariant(name="ai-eng", resume_path="r.pdf", keywords=[], seniority="mid"))
    rv2 = store.upsert_role_variant(RoleVariant(name="swe", resume_path="r.pdf", keywords=[], seniority="mid"))
    store.insert_match(Match(role_variant_id=rv1, company_id=cid, score=9, reasoning="great"))
    store.insert_match(Match(role_variant_id=rv2, company_id=cid, score=7, reasoning="ok"))

    pending = store.get_matches_for_review(7)
    assert len(pending) == 1
    assert pending[0]["score"] == 9  # highest variant wins
    assert pending[0]["role_variant_name"] == "ai-eng"


def test_get_other_variant_scores(store):
    cid = store.upsert_company(Company(name="Acme", source_url="https://acme.com"))
    rv1 = store.upsert_role_variant(RoleVariant(name="ai-eng", resume_path="r.pdf", keywords=[], seniority="mid"))
    rv2 = store.upsert_role_variant(RoleVariant(name="swe", resume_path="r.pdf", keywords=[], seniority="mid"))
    mid1 = store.insert_match(Match(role_variant_id=rv1, company_id=cid, score=9, reasoning="great"))
    store.insert_match(Match(role_variant_id=rv2, company_id=cid, score=7, reasoning="ok"))

    others = store.get_other_variant_scores(cid, exclude_match_id=mid1)
    assert len(others) == 1
    assert others[0]["role_variant_name"] == "swe"
    assert others[0]["score"] == 7


def test_log_run_and_get_last_run_date(store):
    # No runs yet
    assert store.get_last_run_date() is None
    # After first run
    store.log_run()
    d = store.get_last_run_date()
    assert d is not None
    assert len(d) == 10  # YYYY-MM-DD
    # After second run, still returns a date (most recent)
    store.log_run()
    assert store.get_last_run_date() is not None
