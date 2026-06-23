# tests/test_report.py
import csv
from pathlib import Path
from unittest.mock import MagicMock, patch

from prospector.stages.report import _resume_stem, _title_slug, run_report
from prospector.store import Store
from prospector.models import Company, RoleVariant, Match, Contact, OutreachDraft, DraftType, ResumeDraft


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


def _latex_store(tmp_path, latex_src=None):
    """Store seeded with one high-score match that has a LaTeX resume draft."""
    src = latex_src or r"\documentclass{article}\begin{document}Tailored\end{document}"
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
        tailored_text=src,
    ))
    return store


def test_latex_resume_writes_tex_always(tmp_path):
    """The .tex file is always written even when pdflatex is unavailable."""
    store = _latex_store(tmp_path)

    # try_compile_pdf returns (False, 0, "not installed") — pdflatex absent
    with patch("prospector.stages.report.try_compile_pdf", return_value=(False, 0, "pdflatex not installed")):
        paths = run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham")

    report_dir = Path(paths["markdown"]).parent
    tex_files = list((report_dir / "resumes").glob("*.tex"))
    assert len(tex_files) == 1
    name = tex_files[0].name.lower()
    assert "faham" in name
    assert "latexco" in name
    md = Path(paths["markdown"]).read_text()
    assert ".tex" in md


def test_latex_compile_success_produces_pdf_and_docx(tmp_path):
    """When pdflatex succeeds (1 page) and pandoc succeeds, both files appear."""
    store = _latex_store(tmp_path)

    with patch("prospector.stages.report.try_compile_pdf", return_value=(True, 1, "")) as mpdf, \
         patch("prospector.stages.report.compile_docx", return_value=True) as mdocx:
        paths = run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham")

    report_dir = Path(paths["markdown"]).parent
    resumes = report_dir / "resumes"
    assert any(resumes.glob("*.tex"))
    md = Path(paths["markdown"]).read_text()
    assert ".pdf" in md
    assert ".docx" in md


def test_compile_error_triggers_llm_fix_and_retry(tmp_path):
    """On compile error, LLM is asked to fix; fixed src is retried."""
    store = _latex_store(tmp_path)
    llm = MagicMock()
    llm.is_over_budget.return_value = False
    fixed_latex = r"\documentclass{article}\begin{document}Fixed\end{document}"
    llm.call.return_value = fixed_latex

    call_count = [0]
    def fake_compile(latex_src, path):
        call_count[0] += 1
        if call_count[0] == 1:
            return (False, 0, "! LaTeX Error: undefined control sequence")
        return (True, 1, "")

    with patch("prospector.stages.report.try_compile_pdf", side_effect=fake_compile), \
         patch("prospector.stages.report.compile_docx", return_value=False):
        run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham", llm=llm)

    # LLM was called once to fix the error
    assert llm.call.call_count == 1
    # pdflatex was called twice (first fail, second success)
    assert call_count[0] == 2
    # Final .tex contains the fixed source
    report_dir = list((tmp_path / "reports").iterdir())[0]
    tex = next((report_dir / "resumes").glob("*.tex")).read_text()
    assert "Fixed" in tex


def test_overflow_triggers_llm_condense_and_retry(tmp_path):
    """On 2-page PDF, LLM is asked to condense; condensed src is retried."""
    store = _latex_store(tmp_path)
    llm = MagicMock()
    llm.is_over_budget.return_value = False
    condensed_latex = r"\documentclass{article}\begin{document}Short\end{document}"
    llm.call.return_value = condensed_latex

    call_count = [0]
    def fake_compile(latex_src, path):
        call_count[0] += 1
        if call_count[0] == 1:
            return (True, 2, "")  # first attempt: 2 pages
        return (True, 1, "")     # second attempt: 1 page

    with patch("prospector.stages.report.try_compile_pdf", side_effect=fake_compile), \
         patch("prospector.stages.report.compile_docx", return_value=False):
        run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham", llm=llm)

    assert llm.call.call_count == 1
    assert call_count[0] == 2
    report_dir = list((tmp_path / "reports").iterdir())[0]
    tex = next((report_dir / "resumes").glob("*.tex")).read_text()
    assert "Short" in tex


def test_no_llm_accepts_compile_failure_gracefully(tmp_path):
    """Without LLM, a compile failure just skips PDF — no crash."""
    store = _latex_store(tmp_path)

    with patch("prospector.stages.report.try_compile_pdf", return_value=(False, 0, "error")):
        paths = run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham")

    assert Path(paths["markdown"]).exists()


def test_no_llm_accepts_multipage_pdf(tmp_path):
    """Without LLM, a 2-page PDF is accepted rather than retried."""
    store = _latex_store(tmp_path)

    with patch("prospector.stages.report.try_compile_pdf", return_value=(True, 2, "")), \
         patch("prospector.stages.report.compile_docx", return_value=False):
        paths = run_report(store, output_dir=str(tmp_path / "reports"), candidate_name="Faham")

    md = Path(paths["markdown"]).read_text()
    assert ".pdf" in md  # PDF is linked even though it's 2 pages


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
