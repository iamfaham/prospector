# tests/test_compiler.py
"""Tests for the PDF/DOCX compiler helpers (all subprocess calls mocked)."""
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_agent.output.compiler import (
    _extract_page_count,
    compile_docx,
    compile_pdf,
    try_compile_pdf,
)


FAKE_LATEX = r"""
\documentclass{article}
\begin{document}
Hello world
\end{document}
"""

_ONE_PAGE_STDOUT = (
    "This is pdfTeX\n"
    "Output written on /tmp/resume.pdf (1 page, 12345 bytes).\n"
)
_TWO_PAGE_STDOUT = (
    "This is pdfTeX\n"
    "Output written on /tmp/resume.pdf (2 pages, 23456 bytes).\n"
)


# ── _extract_page_count ───────────────────────────────────────────────────────

def test_extract_page_count_one_page():
    assert _extract_page_count(_ONE_PAGE_STDOUT) == 1


def test_extract_page_count_two_pages():
    assert _extract_page_count(_TWO_PAGE_STDOUT) == 2


def test_extract_page_count_no_match():
    assert _extract_page_count("pdflatex: error") == 0


# ── try_compile_pdf ───────────────────────────────────────────────────────────

def test_try_compile_pdf_success_one_page(tmp_path):
    pdf_out = tmp_path / "resume.pdf"

    call_count = [0]

    def fake_run(cmd, **kwargs):
        out_dir = next(
            (Path(a.split("=", 1)[1]) for a in cmd if a.startswith("-output-directory=")),
            None,
        )
        if out_dir:
            (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        r = MagicMock()
        r.returncode = 0
        r.stdout = _ONE_PAGE_STDOUT.encode()
        r.stderr = b""
        call_count[0] += 1
        return r

    with patch("job_agent.output.compiler.subprocess.run", side_effect=fake_run):
        ok, pages, error_log = try_compile_pdf(FAKE_LATEX, pdf_out)

    assert ok is True
    assert pages == 1
    assert error_log == ""
    assert pdf_out.exists()
    assert call_count[0] == 2  # pdflatex runs twice


def test_try_compile_pdf_returns_page_count(tmp_path):
    pdf_out = tmp_path / "resume.pdf"

    def fake_run(cmd, **kwargs):
        out_dir = next(
            (Path(a.split("=", 1)[1]) for a in cmd if a.startswith("-output-directory=")),
            None,
        )
        if out_dir:
            (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        r = MagicMock()
        r.returncode = 0
        r.stdout = _TWO_PAGE_STDOUT.encode()
        r.stderr = b""
        return r

    with patch("job_agent.output.compiler.subprocess.run", side_effect=fake_run):
        ok, pages, error_log = try_compile_pdf(FAKE_LATEX, pdf_out)

    assert ok is True
    assert pages == 2


def test_try_compile_pdf_compile_error(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    bad = MagicMock()
    bad.returncode = 1
    bad.stdout = b"! LaTeX Error: something broken"
    bad.stderr = b""

    with patch("job_agent.output.compiler.subprocess.run", return_value=bad):
        ok, pages, error_log = try_compile_pdf(FAKE_LATEX, pdf_out)

    assert ok is False
    assert pages == 0
    assert "LaTeX Error" in error_log


def test_try_compile_pdf_pdflatex_not_found(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=FileNotFoundError("pdflatex not found")):
        ok, pages, error_log = try_compile_pdf(FAKE_LATEX, pdf_out)

    assert ok is False
    assert pages == 0
    assert "not installed" in error_log


def test_try_compile_pdf_timeout(tmp_path):
    pdf_out = tmp_path / "resume.pdf"
    with patch("job_agent.output.compiler.subprocess.run",
               side_effect=subprocess.TimeoutExpired("pdflatex", 60)):
        ok, pages, error_log = try_compile_pdf(FAKE_LATEX, pdf_out)

    assert ok is False
    assert "timed out" in error_log


# ── compile_pdf (backward-compat wrapper) ─────────────────────────────────────

def test_compile_pdf_success(tmp_path):
    pdf_out = tmp_path / "resume.pdf"

    def fake_run(cmd, **kwargs):
        out_dir = next(
            (Path(a.split("=", 1)[1]) for a in cmd if a.startswith("-output-directory=")),
            None,
        )
        if out_dir:
            (out_dir / "resume.pdf").write_bytes(b"%PDF-1.4 fake")
        r = MagicMock()
        r.returncode = 0
        r.stdout = _ONE_PAGE_STDOUT.encode()
        r.stderr = b""
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
    bad.stderr = b""

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
