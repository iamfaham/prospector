# job_agent/output/compiler.py
"""
Compile LaTeX source to PDF (via pdflatex) and DOCX (via pandoc).
Both functions return True on success and False with a warning when the
required system tool is not installed — the rest of the pipeline continues.
"""
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def compile_pdf(latex_src: str, output_path: Path) -> bool:
    """Compile LaTeX source to PDF using pdflatex.

    Requires: pdflatex (MiKTeX or TeX Live).
    Runs pdflatex twice so cross-references and table of contents resolve.
    Returns True when a PDF was written to *output_path*.
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tex_file = tmp / "resume.tex"
            tex_file.write_text(latex_src, encoding="utf-8")

            cmd = [
                "pdflatex",
                "-interaction=nonstopmode",
                f"-output-directory={tmpdir}",
                str(tex_file),
            ]
            # First pass
            result = subprocess.run(cmd, capture_output=True, timeout=60)
            if result.returncode != 0:
                logger.warning(
                    "[compiler] pdflatex first pass failed:\n%s",
                    result.stdout.decode(errors="replace")[-1000:],
                )
                return False
            # Second pass — resolves \ref, \label, ToC
            subprocess.run(cmd, capture_output=True, timeout=60)

            pdf_src = tmp / "resume.pdf"
            if pdf_src.exists():
                shutil.copy2(pdf_src, output_path)
                return True

            logger.warning("[compiler] pdflatex ran but no PDF produced")
            return False

    except FileNotFoundError:
        logger.warning(
            "[compiler] pdflatex not found — install MiKTeX (https://miktex.org) "
            "or TeX Live to enable PDF output"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[compiler] pdflatex timed out after 60 s")
        return False


def compile_docx(latex_src: str, output_path: Path) -> bool:
    """Convert LaTeX source to DOCX using pandoc.

    Requires: pandoc (https://pandoc.org/installing.html).
    Returns True when a DOCX was written to *output_path*.
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tex_file = Path(tmpdir) / "resume.tex"
            tex_file.write_text(latex_src, encoding="utf-8")

            result = subprocess.run(
                [
                    "pandoc",
                    str(tex_file),
                    "--from=latex",
                    "--to=docx",
                    f"--output={output_path}",
                ],
                capture_output=True,
                timeout=30,
            )
            if result.returncode == 0 and output_path.exists():
                return True

            logger.warning(
                "[compiler] pandoc failed (exit %d): %s",
                result.returncode,
                result.stderr.decode(errors="replace")[-500:],
            )
            return False

    except FileNotFoundError:
        logger.warning(
            "[compiler] pandoc not found — install from https://pandoc.org/installing.html "
            "to enable DOCX output"
        )
        return False
    except subprocess.TimeoutExpired:
        logger.warning("[compiler] pandoc timed out after 30 s")
        return False
