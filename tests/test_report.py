# tests/test_report.py
import csv
from pathlib import Path
from unittest.mock import patch

from job_agent.stages.report import _resume_stem, _title_slug, run_report
from job_agent.store import Store
from job_agent.models import Company, RoleVariant, Match, Contact, OutreachDraft, DraftType, ResumeDraft


def _full_store(tmp_path):
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    cid = store.upsert_company(Company(
        name="Acme AI", source_url="https://a.com",
        funding_stage="Seed", funding_date="2026-06",
        raw_signal_text="Raised $5M",
    ))
    mid = store.insert_match(
        Match(role_variant_id=rv_id, company_id=cid, score=8, reasoning="strong Python match")
    )
    ctid = store.insert_contact(Contact(
        company_id=cid, name="Alice Smith", title="CTO",
        email="alice@acme.com", profile_url="https://li.com/alice",
    ))
    store.insert_outreach_draft(OutreachDraft(
        match_id=mid, contact_id=ctid, draft_type=DraftType.COLD_OUTREACH,
        message_text="Hi Alice, I saw Acme raised $5M...",
    ))
    return store


def test_creates_report_files(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    assert Path(paths["markdown"]).exists()
    assert Path(paths["csv"]).exists()


def test_markdown_contains_company_and_score(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    md = Path(paths["markdown"]).read_text()
    assert "Acme AI" in md
    assert "8/10" in md
    assert "Alice Smith" in md
    assert "Hi Alice" in md


def test_csv_has_correct_columns(tmp_path):
    store = _full_store(tmp_path)
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    with open(paths["csv"], newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)
    assert len(rows) == 1
    assert rows[0]["company_name"] == "Acme AI"
    assert rows[0]["score"] == "8"
    assert rows[0]["contact_name"] == "Alice Smith"


def test_empty_store_produces_valid_report(tmp_path):
    store = Store(db_path=str(tmp_path / "empty.db"))
    paths = run_report(store, output_dir=str(tmp_path / "reports"))
    assert Path(paths["markdown"]).exists()
    md = Path(paths["markdown"]).read_text()
    assert "Total matches: 0" in md


def test_latex_resume_writes_tex_and_attempts_pdf_docx(tmp_path):
    """When resume_tailored_text is LaTeX, report writes .tex and calls compilers."""
    store = Store(db_path=str(tmp_path / "test.db"))
    rv_id = store.upsert_role_variant(
        RoleVariant(name="be", resume_path="r.txt", keywords=[], seniority="mid")
    )
    cid = store.upsert_company(Company(name="LatexCo", source_url="https://latex.co"))
    mid = store.insert_match(
        Match(role_variant_id=rv_id, company_id=cid, score=9, reasoning="great fit")
    )
    store.insert_resume_draft(ResumeDraft(
        match_id=mid, role_variant_id=rv_id,
        company_name="LatexCo", job_title="SWE",
        tailored_text=r"\documentclass{article}\begin{document}Tailored\end{document}",
    ))

    with patch("job_agent.stages.report.compile_pdf", return_value=False) as mpdf, \
         patch("job_agent.stages.report.compile_docx", return_value=False) as mdocx:
        paths = run_report(store, output_dir=str(tmp_path / "reports"),
                           candidate_name="Faham")

    # .tex file must always be written regardless of compiler availability
    report_dir = Path(paths["markdown"]).parent
    tex_files = list((report_dir / "resumes").glob("*.tex"))
    assert len(tex_files) == 1
    name = tex_files[0].name.lower()
    assert "faham" in name
    assert "latexco" in name

    # Compilers were called once each
    mpdf.assert_called_once()
    mdocx.assert_called_once()

    # Markdown links the .tex file
    md = Path(paths["markdown"]).read_text()
    assert ".tex" in md


def test_resume_stem_naming():
    stem = _resume_stem("Faham", "Acme Corp", "Senior Backend Engineer", "2026-06-17")
    # date is kept verbatim with hyphens; words are CamelCased
    assert stem == "Faham_AcmeCorp_SeniorBackendEngineer_2026-06-17"


def test_resume_stem_no_job_title():
    stem = _resume_stem("Faham", "StealthCo", None, "2026-06-17")
    # capitalize() lower-cases the tail: StealthCo → Stealthco
    assert stem == "Faham_Stealthco_2026-06-17"


def test_resume_stem_date_keeps_hyphens():
    stem = _resume_stem("Alice", "AcmeCorp", None, "2026-06-17")
    assert stem.endswith("_2026-06-17")


def test_title_slug_special_chars():
    assert _title_slug("Acme-Corp (AI)") == "AcmeCorpAi"


def test_title_slug_spaces():
    assert _title_slug("Senior Backend Engineer") == "SeniorBackendEngineer"
