# job_agent/stages/report.py
import csv
import logging
import re
from datetime import datetime, timezone
from pathlib import Path

from job_agent.output.compiler import compile_docx, compile_pdf
from job_agent.store import Store

logger = logging.getLogger(__name__)


def run_report(
    store: Store,
    output_dir: str = "reports",
    candidate_name: str = "candidate",
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
                            row.get("job_title"), date_str)
        files: list[str] = []

        # Detect whether the tailored text is LaTeX or markdown
        is_latex = tailored.lstrip().startswith("\\") or "\\documentclass" in tailored

        if is_latex:
            # Save raw .tex
            tex_path = resumes_dir / f"{stem}.tex"
            tex_path.write_text(tailored, encoding="utf-8")
            files.append(str(tex_path.relative_to(report_dir)))

            # Attempt PDF
            pdf_path = resumes_dir / f"{stem}.pdf"
            if compile_pdf(tailored, pdf_path):
                files.append(str(pdf_path.relative_to(report_dir)))
                logger.info("[report] PDF: %s", pdf_path.name)
            else:
                logger.warning("[report] PDF skipped for %s (pdflatex unavailable/failed)",
                               row.get("company_name"))

            # Attempt DOCX
            docx_path = resumes_dir / f"{stem}.docx"
            if compile_docx(tailored, docx_path):
                files.append(str(docx_path.relative_to(report_dir)))
                logger.info("[report] DOCX: %s", docx_path.name)
            else:
                logger.warning("[report] DOCX skipped for %s (pandoc unavailable/failed)",
                               row.get("company_name"))
        else:
            # Markdown tailored resume
            md_path = resumes_dir / f"{stem}.md"
            md_path.write_text(tailored, encoding="utf-8")
            files.append(str(md_path.relative_to(report_dir)))

        row["resume_files"] = files

    md_path = report_dir / "report.md"
    csv_path = report_dir / "matches.csv"

    _write_markdown(rows, md_path)
    _write_csv(rows, csv_path)

    return {"markdown": str(md_path), "csv": str(csv_path)}


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
        if row.get("funding_stage"):
            lines.append(f"**Funding:** {row['funding_stage']} · {row.get('funding_date', '')}")
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
        "funding_stage", "funding_date", "contact_name", "contact_title",
        "contact_email", "status",
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _resume_stem(candidate: str, company: str, job_title: str | None, date: str) -> str:
    """Build a filename stem: Faham_AcmeCorp_SeniorBackendEngineer_2026-06-17

    The date is appended verbatim (with its hyphens) so it stays human-readable.
    """
    parts = [candidate, company]
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
