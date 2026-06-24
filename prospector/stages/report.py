# prospector/stages/report.py
import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from prospector.output.compiler import compile_docx, try_compile_pdf
from prospector.store import Store

if TYPE_CHECKING:
    from prospector.llm.client import LLMClient

logger = logging.getLogger(__name__)

_MAX_FIX_ATTEMPTS = 3


def run_report(
    store: Store,
    output_dir: str = "reports",
    candidate_name: str = "candidate",
    llm: Optional["LLMClient"] = None,
) -> dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir) / ts
    report_dir.mkdir(parents=True, exist_ok=True)

    resumes_dir = report_dir / "resumes"
    resumes_dir.mkdir(exist_ok=True)

    rows = store.get_all_for_report()
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    for row in rows:
        tailored = row.get("resume_tailored_text")
        if not tailored:
            continue

        stem = _resume_stem(candidate_name, row.get("company_name", "unknown"),
                            row.get("role_variant_name", ""), row.get("job_title"), date_str)
        files: list[str] = []

        is_latex = tailored.lstrip().startswith("\\") or "\\documentclass" in tailored

        if is_latex:
            final_latex, produced = _compile_with_fix(
                tailored, stem, resumes_dir, report_dir, llm,
            )
            files.extend(produced)
        else:
            md_path = resumes_dir / f"{stem}.md"
            md_path.write_text(tailored, encoding="utf-8")
            files.append(str(md_path.relative_to(report_dir)))

        row["resume_files"] = files

    md_path = report_dir / "report.md"
    csv_path = report_dir / "matches.csv"

    _write_markdown(rows, md_path)
    _write_csv(rows, csv_path)

    return {"markdown": str(md_path), "csv": str(csv_path)}


def _compile_with_fix(
    latex_src: str,
    stem: str,
    resumes_dir: Path,
    report_dir: Path,
    llm: Optional["LLMClient"],
    max_attempts: int = _MAX_FIX_ATTEMPTS,
) -> tuple[str, list[str]]:
    """Agentic compile loop.

    1. Try to compile the LaTeX to PDF.
    2a. On compile error  → ask LLM to fix the source, retry.
    2b. On page overflow  → ask LLM to condense, retry.
    3. On success         → compile DOCX from the final (possibly fixed) source.
    4. Always write the final .tex regardless of PDF/DOCX outcome.

    Returns (final_latex_src, list_of_relative_file_paths).
    """
    # Lazy import to avoid circular deps at module load time
    from prospector.llm.prompts import fix_latex_compile_error_prompt, fix_latex_overflow_prompt

    src = latex_src
    pdf_path = resumes_dir / f"{stem}.pdf"
    tex_path = resumes_dir / f"{stem}.tex"
    docx_path = resumes_dir / f"{stem}.docx"

    pdf_ok = False

    for attempt in range(max_attempts):
        ok, pages, error_log = try_compile_pdf(src, pdf_path)

        if ok and pages <= 1:
            pdf_ok = True
            logger.info("[report] PDF OK (1 page): %s", pdf_path.name)
            break

        if ok and pages > 1:
            logger.warning(
                "[report] PDF is %d pages for %s (attempt %d/%d) — asking LLM to condense",
                pages, stem, attempt + 1, max_attempts,
            )
            if llm and not llm.is_over_budget():
                sys_p, usr_p = fix_latex_overflow_prompt(src, pages)
                try:
                    src = llm.call(sys_p, usr_p)
                except Exception as exc:
                    logger.error("[report] LLM overflow-fix failed: %s", exc)
                    # Keep last src, one more compile attempt with what we have
                    pdf_ok = True  # accept multi-page rather than lose PDF
                    break
            else:
                # No LLM or over budget — accept the multi-page PDF
                pdf_ok = True
                logger.warning("[report] accepting %d-page PDF (no LLM available)", pages)
                break
        else:
            # Compile error
            logger.warning(
                "[report] pdflatex error for %s (attempt %d/%d):\n%s",
                stem, attempt + 1, max_attempts, error_log[-600:],
            )
            if llm and not llm.is_over_budget():
                sys_p, usr_p = fix_latex_compile_error_prompt(src, error_log)
                try:
                    src = llm.call(sys_p, usr_p)
                except Exception as exc:
                    logger.error("[report] LLM compile-fix failed: %s", exc)
                    break
            else:
                logger.warning("[report] pdflatex unavailable or no LLM — skipping PDF")
                break

    # Always write the (possibly fixed) .tex
    tex_path.write_text(src, encoding="utf-8")
    produced: list[str] = [str(tex_path.relative_to(report_dir))]

    if pdf_ok:
        produced.append(str(pdf_path.relative_to(report_dir)))
        # DOCX converted from the final PDF (via pdf2docx, no system tool needed)
        if compile_docx(pdf_path, docx_path):
            produced.append(str(docx_path.relative_to(report_dir)))
            logger.info("[report] DOCX OK: %s", docx_path.name)
        else:
            logger.warning("[report] DOCX skipped for %s (pdf2docx unavailable/failed)", stem)
    else:
        logger.warning("[report] no PDF produced for %s after %d attempts", stem, max_attempts)

    return src, produced


def _write_markdown(rows: list[dict], path: Path) -> None:
    now = datetime.now(timezone.utc).isoformat()
    lines = [
        "# Job Agent Report",
        f"Generated: {now}",
        f"Total matches: {len(rows)}",
        "",
        "---",
        "",
    ]

    for row in rows:
        score = row.get("score", "?")
        company = row.get("company_name", "Unknown")
        lines.append(f"## {company} (Score: {score}/10)")
        lines.append(f"**Role:** {row.get('role_variant_name', '?')}")
        if row.get("job_title"):
            lines.append(f"**Job:** [{row['job_title']}]({row.get('job_url', '#')})")
        funding_parts = [row.get("funding_stage"), row.get("funding_amount"), row.get("funding_date")]
        funding = " · ".join(p for p in funding_parts if p)
        if funding:
            lines.append(f"**Funding:** {funding}")
        if row.get("source_url"):
            lines.append(f"**Source:** {row['source_url']}")
        lines += ["", f"**Match reasoning:** {row.get('reasoning', '')}", ""]
        if row.get("contact_name"):
            lines.append(f"**Contact:** {row['contact_name']} ({row.get('contact_title', '')})")
            if row.get("contact_email"):
                lines.append(f"**Email:** {row['contact_email']}")
            if row.get("contact_profile_url"):
                lines.append(f"**Profile:** {row['contact_profile_url']}")
            lines.append("")
        if row.get("message_text"):
            quoted = row["message_text"].replace("\n", "\n> ")
            lines += ["**Drafted message:**", "", f"> {quoted}", ""]
        for fpath in row.get("resume_files", []):
            ext = Path(fpath).suffix.upper().lstrip(".")
            lines.append(f"**Tailored resume ({ext}):** [{fpath}]({fpath})")
        if row.get("resume_files"):
            lines.append("")
        lines += ["---", ""]

    path.write_text("\n".join(lines), encoding="utf-8")


def _write_csv(rows: list[dict], path: Path) -> None:
    fields = [
        "company_name", "role_variant_name", "score", "job_title", "job_url",
        "funding_stage", "funding_amount", "funding_date", "source_url",
        "contact_name", "contact_title", "contact_email", "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resume_stem(candidate: str, company: str, role_variant: str, job_title: str | None, date: str) -> str:
    """Build a filename stem: Faham_AcmeCorp_AiEngineer_SeniorBackendEngineer_2026-06-17

    The date is appended verbatim (with its hyphens) so it stays human-readable.
    """
    parts = [candidate, company, role_variant]
    if job_title:
        parts.append(job_title)
    slug = "_".join(_title_slug(p) for p in parts)
    return f"{slug}_{date}"


def _title_slug(text: str) -> str:
    """CamelCase slug splitting on spaces, hyphens, and underscores.

    'Senior Backend Engineer' → 'SeniorBackendEngineer'
    'Acme-Corp (AI)'         → 'AcmeCorpAi'
    """
    parts = re.split(r"[\s\-_]+", text.strip())
    cleaned = [re.sub(r"[^\w]", "", p) for p in parts]
    return "".join(p.capitalize() for p in cleaned if p)[:40]


def _slugify(text: str) -> str:
    """Lowercase hyphenated slug for directory names."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    return text[:60]
