# tests/test_compiler.py
"""Tests for the PDF/DOCX compiler helpers (all subprocess calls mocked)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from job_agent.output.compiler import compile_docx, compile_pdf


FAKE_LATEX = r"""
\documentclass{article}
\begin{document}
Hello world
\end{document}
"""


# ── compile_pdf ───────────────────────────────────────────────────────────────

def test_compile_pdf_success(tmp_path):
    pdf_out = tmp_path / "resume.pdf"

    def fake_run(cmd, **kwargs):
        # Simulate pdflatex writing a PDF on first call
        out_dir = None
        for arg in cmd:
            if arg.startswith("-output-directory="):
                out_dir = Path(arg.split("=", 1)[1])
        if out_dir:
            (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        r = MagicMock()
        r.returncode = 0
        return r

    with patch("job_agent.output.compiler.subprocess.run", side_effect=fake_run):
        result = compile_pdf(FAKE_LATEX, pdf_out)

    assert result is True
    assert pdf_out.exists()


def test_compile_pdf_pdflatex_not_found(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=FileNotFoundError("pdflatex not found")):
        result = compile_pdf(FAKE_LATEX, pdf_out)

    assert result is False
    assert not pdf_out.exists()


def test_compile_pdf_nonzero_exit(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    bad = MagicMock()
    bad.returncode = 1
    bad.stdout = b"! LaTeX Error"

    with patch("job_agent.output.compiler.subprocess.run", return_value=bad):
        result = compile_pdf(FAKE_LATEX, pdf_out)

    assert result is False


def test_compile_pdf_timeout(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=subprocess.TimeoutExpired("pdflatex", 60)):
        result = compile_pdf(FAKE_LATEX, pdf_out)

    assert result is False


# ── compile_docx ──────────────────────────────────────────────────────────────

def test_compile_docx_success(tmp_path):
    docx_out = tmp_path / "resume.docx"

    def fake_run(cmd, **kwargs):
        # Simulate pandoc writing a DOCX
        for arg in cmd:
            if arg.startswith("--output="):
                Path(arg.split("=", 1)[1]).write_bytes(b"PK fake docx")
        r = MagicMock()
        r.returncode = 0
        return r

    with patch("job_agent.output.compiler.subprocess.run", side_effect=fake_run):
        result = compile_docx(FAKE_LATEX, docx_out)

    assert result is True
    assert docx_out.exists()


def test_compile_docx_pandoc_not_found(tmp_path):
    docx_out = tmp_path / "resume.docx"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=FileNotFoundError("pandoc not found")):
        result = compile_docx(FAKE_LATEX, docx_out)

    assert result is False
    assert not docx_out.exists()


def test_compile_docx_nonzero_exit(tmp_path):
    docx_out = tmp_path / "resume.docx"
    bad = MagicMock()
    bad.returncode = 2
    bad.stderr = b"pandoc: unknown format"

    with patch("job_agent.output.compiler.subprocess.run", return_value=bad):
        result = compile_docx(FAKE_LATEX, docx_out)

    assert result is False


def test_compile_docx_timeout(tmp_path):
    docx_out = tmp_path / "resume.docx"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=subprocess.TimeoutExpired("pandoc", 30)):
        result = compile_docx(FAKE_LATEX, docx_out)

    assert result is False
