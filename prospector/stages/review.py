# prospector/stages/review.py
"""
Interactive company review with parallel background resume tailoring.

Flow:
  1. Fetch all 'new' matches above threshold, sorted by score desc.
  2. Show each company card in the terminal; user presses a/r/s/q.
  3. On accept → submit tailoring + PDF/DOCX compilation to a thread pool.
  4. Meanwhile show the next company.
  5. After last company → wait for all background jobs, print results.
  6. Rewrite reports/live_report.md after every user action and every
     completed tailor.
"""
import logging
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import typer

from prospector.config import MatchingConfig, RoleVariantConfig
from prospector.llm.client import LLMClient, LLMError
from prospector.models import MatchStatus, ResumeDraft
from prospector.store import Store

logger = logging.getLogger(__name__)

_MAX_TAILOR_WORKERS = 4


# ── public entry point ────────────────────────────────────────────────────────

def run_review(
    store: Store,
    rv_map: dict[int, RoleVariantConfig],       # role_variant_id → config
    latex_sources: dict[int, Optional[str]],    # role_variant_id → LaTeX src or None
    resume_texts: dict[str, str],               # rv_name → plain text
    matching_config: MatchingConfig,
    llm: LLMClient,
    candidate_name: str,
    output_dir: str = "reports",
) -> dict[str, int]:
    threshold = matching_config.score_threshold_for_outreach
    pending = store.get_matches_for_review(threshold)

    if not pending:
        typer.echo("[review] No pending matches to review.")
        return {"accepted": 0, "rejected": 0, "skipped": 0}

    counts = {"accepted": 0, "rejected": 0, "skipped": 0}
    resumes_dir = Path(output_dir) / "resumes"
    resumes_dir.mkdir(parents=True, exist_ok=True)
    date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tailor_results: list[dict] = []
    results_lock = threading.Lock()

    def _on_done(future: Future) -> None:
        try:
            result = future.result()
        except Exception as exc:
            result = {"company": "?", "files": [], "ok": False, "error": str(exc)}
        with results_lock:
            tailor_results.append(result)
        icon = "✓" if result.get("ok") else "✗"
        files = result.get("files", [])
        detail = ", ".join(Path(f).name for f in files) if files else result.get("error", "no output")
        typer.echo(f"  {icon} {result['company']}: {detail}")
        _write_live_report(store, output_dir, list(tailor_results))

    executor = ThreadPoolExecutor(max_workers=_MAX_TAILOR_WORKERS)
    total = len(pending)

    try:
        for i, match in enumerate(pending, 1):
            other_variants = store.get_other_variant_scores(match["company_id"], exclude_match_id=match["id"])
            _show_company(match, i, total, other_variants=other_variants)
            choice = _prompt()

            if choice == "q":
                typer.echo("[review] Quitting — remaining matches left as pending.")
                break
            elif choice in ("a", "A"):
                store.update_match_status(match["id"], MatchStatus.ACCEPTED)
                counts["accepted"] += 1
                rv_cfg = rv_map[match["role_variant_id"]]
                latex_src = latex_sources.get(match["role_variant_id"])
                resume_text = resume_texts.get(rv_cfg.name, "")
                future = executor.submit(
                    _tailor_and_compile,
                    match, rv_cfg, latex_src, resume_text,
                    store.db_path, llm, resumes_dir, candidate_name, date_str,
                )
                future.add_done_callback(_on_done)
                typer.echo("  → Tailoring started in background…")

                if choice == "A":
                    for remaining in pending[i:]:
                        store.update_match_status(remaining["id"], MatchStatus.ACCEPTED)
                        counts["accepted"] += 1
                        rv_cfg_r = rv_map[remaining["role_variant_id"]]
                        latex_src_r = latex_sources.get(remaining["role_variant_id"])
                        resume_text_r = resume_texts.get(rv_cfg_r.name, "")
                        fut = executor.submit(
                            _tailor_and_compile,
                            remaining, rv_cfg_r, latex_src_r, resume_text_r,
                            store.db_path, llm, resumes_dir, candidate_name, date_str,
                        )
                        fut.add_done_callback(_on_done)
                    typer.echo(f"  → Accepted all {len(pending[i:])} remaining matches.")
                    _write_live_report(store, output_dir, list(tailor_results))
                    break
            elif choice == "r":
                store.update_match_status(match["id"], MatchStatus.REJECTED)
                counts["rejected"] += 1
            else:
                counts["skipped"] += 1

            _write_live_report(store, output_dir, list(tailor_results))

    except KeyboardInterrupt:
        typer.echo("\n[review] Interrupted — waiting for in-flight tailoring jobs…")

    in_flight = counts["accepted"] - len(tailor_results)
    if in_flight > 0:
        typer.echo(f"\n[review] Waiting for {in_flight} tailoring job(s) to finish…")

    executor.shutdown(wait=True)
    _write_live_report(store, output_dir, tailor_results)

    typer.echo(
        f"\n[review] Done — {counts['accepted']} accepted, "
        f"{counts['rejected']} rejected, {counts['skipped']} skipped."
    )
    if counts["accepted"]:
        typer.echo("[review] Next: uv run prospector report")

    return counts


# ── display helpers ───────────────────────────────────────────────────────────

def _show_company(match: dict, idx: int, total: int, other_variants: list[dict] | None = None) -> None:
    funding_parts = [
        match.get("funding_stage"),
        match.get("funding_amount"),
        match.get("funding_date"),
    ]
    funding = " · ".join(p for p in funding_parts if p) or "—"
    reasoning = (match.get("reasoning") or "")[:160]
    url = match.get("job_url") or match.get("source_url") or ""
    signal = (match.get("raw_signal_text") or "")[:200]
    jd = (match.get("job_description") or "")[:300]

    roles_line = " · ".join(
        [f"{match['role_variant_name']} {match['score']}/10"]
        + [f"{v['role_variant_name']} {v['score']}/10" for v in (other_variants or [])]
    )
    typer.echo(f"\n{'─' * 66}")
    typer.echo(f" {idx} / {total}  │  {roles_line}")
    typer.echo(f"{'─' * 66}")
    typer.echo(f" Company : {match['company_name']}")
    typer.echo(f" Funding : {funding}")
    if signal:
        typer.echo(f" Signal  : {signal}")
    if match.get("job_title"):
        typer.echo(f" Role    : {match['job_title']}")
    if jd:
        typer.echo(f" JD      : {jd}")
    typer.echo(f" Why     : {reasoning}")
    if url:
        typer.echo(f" URL     : {url}")
    typer.echo(f"{'─' * 66}")


def _prompt() -> str:
    while True:
        raw = input("[a]ccept  [A]ccept all  [r]eject  [s]kip  [q]uit › ").strip()
        if raw in ("a", "A", "r", "s", "q"):
            return raw
        typer.echo("  Please type a, A, r, s, or q.")


# ── background tailoring ──────────────────────────────────────────────────────

def _tailor_and_compile(
    match_dict: dict,
    rv_cfg: RoleVariantConfig,
    latex_src: Optional[str],
    resume_text: str,
    db_path: str,
    llm: LLMClient,
    resumes_dir: Path,
    candidate_name: str,
    date_str: str,
) -> dict:
    """Runs in a worker thread. Opens its own Store connection."""
    from prospector.stages.resume_tailoring import tailor_resume
    from prospector.stages.report import _compile_with_fix, _resume_stem

    thread_store = Store(db_path)
    company_name = match_dict["company_name"]
    job_title = match_dict.get("job_title")

    try:
        source = latex_src if latex_src is not None else resume_text
        tailored = tailor_resume(
            llm=llm,
            resume_text=source,
            role_variant=rv_cfg,
            company_name=company_name,
            job_title=job_title,
            job_description=match_dict.get("job_description"),
            funding_signal=match_dict.get("raw_signal_text"),
            latex_mode=latex_src is not None,
        )
        thread_store.insert_resume_draft(ResumeDraft(
            match_id=match_dict["id"],
            role_variant_id=match_dict["role_variant_id"],
            company_name=company_name,
            job_title=job_title,
            tailored_text=tailored,
        ))

        files: list[str] = []
        if latex_src is not None:
            stem = _resume_stem(candidate_name, company_name, rv_cfg.name, job_title, date_str)
            report_dir = resumes_dir.parent
            _, produced = _compile_with_fix(tailored, stem, resumes_dir, report_dir, llm)
            files = produced

        return {"company": company_name, "files": files, "ok": True}

    except Exception as exc:
        logger.error("[review] tailor failed for %s: %s", company_name, exc)
        return {"company": company_name, "files": [], "ok": False, "error": str(exc)}


# ── live report ───────────────────────────────────────────────────────────────

def _write_live_report(store: Store, output_dir: str, tailor_results: list[dict]) -> None:
    try:
        now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
        rows = store.get_all_for_report()

        status_icon = {"new": "·", "accepted": "✓", "rejected": "✗"}

        lines = [
            "# Job Agent — Live Report",
            f"_Updated: {now}_",
            "",
            f"**{len(rows)} total matches**",
            "",
            "| Score | Company | Status | Funding |",
            "|---|---|---|---|",
        ]
        for row in rows:
            st = row.get("status", "new")
            icon = status_icon.get(st, "·")
            funding_parts = [row.get("funding_stage"), row.get("funding_date")]
            funding = " · ".join(p for p in funding_parts if p) or "—"
            lines.append(
                f"| {row['score']}/10 | {row['company_name']} | {icon} {st} | {funding} |"
            )

        lines += ["", "## Tailored Resumes", ""]
        if not tailor_results:
            lines.append("_None yet._")
        else:
            for r in tailor_results:
                icon = "✓" if r.get("ok") else "✗"
                for f in r.get("files", []):
                    lines.append(f"- {icon} `{Path(f).name}`")
                if not r.get("files"):
                    detail = r.get("error", "compile failed — .tex saved")
                    lines.append(f"- {icon} {r['company']} — {detail}")

        path = Path(output_dir) / "live_report.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("\n".join(lines), encoding="utf-8")
    except Exception as exc:
        logger.debug("[review] live_report write failed: %s", exc)
