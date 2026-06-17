# job_agent/stages/report.py
import csv
from datetime import datetime, timezone
from pathlib import Path
from job_agent.store import Store


def run_report(store: Store, output_dir: str = "reports") -> dict[str, str]:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    report_dir = Path(output_dir) / ts
    report_dir.mkdir(parents=True, exist_ok=True)

    rows = store.get_all_for_report()
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
