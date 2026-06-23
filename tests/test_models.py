from job_agent.models import (
    Company, Job, RoleVariant, Match, Contact, OutreachDraft,
    RawResult, Score, MatchStatus, DraftType, Confidence,
)

def test_company_defaults():
    c = Company(name="Acme", source_url="https://acme.com")
    assert c.id is None
    assert c.funding_stage is None
    assert c.first_seen_at is not None  # auto-filled

def test_match_status_enum():
    assert MatchStatus.NEW.value == "new"
    assert MatchStatus.ACCEPTED.value == "accepted"
    assert MatchStatus.REJECTED.value == "rejected"

def test_draft_type_enum():
    assert DraftType.COLD_OUTREACH.value == "cold_outreach"
    assert DraftType.APPLICATION_BLURB.value == "application_blurb"

def test_raw_result():
    r = RawResult(url="https://tc.com/a", title="Acme raises $5M", snippet="Acme AI raised...")
    assert r.content is None

def test_role_variant():
    rv = RoleVariant(name="backend-eng", resume_path="resumes/backend.txt",
                     keywords=["python", "go"], seniority="mid-senior")
    assert rv.id is None
    assert rv.keywords == ["python", "go"]
