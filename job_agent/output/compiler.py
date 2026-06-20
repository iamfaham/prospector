# job_agent/output/compiler.py
"""
Compile LaTeX source to PDF (via pdflatex) and DOCX (via pandoc).

Public API
----------
try_compile_pdf(latex_src, output_path) -> (ok: bool, pages: int, error_log: str)
    Single compilation attempt.  Caller inspects pages and error_log to decide
    whether to retry or ask an LLM for a fix.

compile_pdf(latex_src, output_path) -> bool
    Backward-compatible single-attempt wrapper (no retry, no LLM).

compile_docx(latex_src, output_path) -> bool
    Convert LaTeX to DOCX via pandoc.
"""
import logging
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_PDFLATEX_CMD = [
    "pdflatex",
    "-interaction=nonstopmode",
    "-halt-on-error",
]


def _extract_page_count(stdout: str) -> int:
    """Parse 'Output written on X.pdf (N pages, ...)' from pdflatex stdout."""
    m = re.search(r"Output written on .+?\((\d+) page", stdout)
    return int(m.group(1)) if m else 0


def try_compile_pdf(latex_src: str, output_path: Path) -> tuple[bool, int, str]:
    """Single PDF compilation attempt.

    Runs pdflatex twice (needed for cross-refs).  Returns:
      ok        – True when a PDF was written to *output_path*
      pages     – page count (0 when compilation failed)
      error_log – relevant pdflatex output on failure, empty string on success
    """
    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            tex_file = tmp / "resume.tex"
            tex_file.write_text(latex_src, encoding="utf-8")

            cmd = _PDFLATEX_CMD + [f"-output-directory={tmpdir}", str(tex_file)]

            r1 = subprocess.run(cmd, capture_output=True, timeout=60)
            stdout1 = r1.stdout.decode(errors="replace")

            if r1.returncode != 0:
                # Trim to the most useful part of the log (last 1500 chars)
                error_log = stdout1[-1500:] + r1.stderr.decode(errors="replace")[-300:]
                return False, 0, error_log

            # Second pass for \ref / \label resolution
            r2 = subprocess.run(cmd, capture_output=True, timeout=60)
            stdout2 = r2.stdout.decode(errors="replace")

            pdf_src = tmp / "resume.pdf"
            if not pdf_src.exists():
                return False, 0, stdout2[-1500:]

            shutil.copy2(pdf_src, output_path)
            pages = _extract_page_count(stdout2) or _extract_page_count(stdout1)
            return True, pages, ""

    except FileNotFoundError:
        logger.warning(
            "[compiler] pdflatex not found — install MiKTeX (https://miktex.org) "
            "or TeX Live to enable PDF output"
        )
        return False, 0, "pdflatex not installed"
    except subprocess.TimeoutExpired:
        logger.warning("[compiler] pdflatex timed out after 60 s")
        return False, 0, "pdflatex timed out"


def compile_pdf(latex_src: str, output_path: Path) -> bool:
    """Single-attempt compilation — backward-compatible wrapper for tests."""
    ok, _, _ = try_compile_pdf(latex_src, output_path)
    return ok


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
                ["pandoc", str(tex_file), "--from=latex", "--to=docx",
                 f"--output={output_path}"],
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
