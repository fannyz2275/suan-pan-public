"""Report writers for Spec C runs."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def write_json(report: dict[str, Any], out_path: Path) -> None:
    """Write the machine-readable JSON report."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(report, indent=2, default=str))


def write_markdown_summary(report: dict[str, Any], out_path: Path) -> None:
    """Write the human-readable Markdown summary (<= 800 lines)."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    h = report["header"]
    lines += [
        "# Spec C — Chat-Advisor Quality Eval",
        "",
        f"- Run date:               {h['run_date']}",
        f"- Dataset version:        {h['dataset_version']}",
        f"- System prompt version:  {h['system_prompt_version']}",
        f"- Subject model:          {h['subject_model']}",
        f"- Judge model:            {h['judge_model']}",
        f"- Suan-Pan git SHA:       {h['suan_pan_sha']}",
        "",
        "## Distribution",
    ]
    dist = report["distribution"]
    lines += [
        f"- 3/3 pass: {dist.get('3/3', 0)}",
        f"- 2/3 pass: {dist.get('2/3', 0)}",
        f"- 1/3 pass: {dist.get('1/3', 0)}",
        f"- 0/3 pass: {dist.get('0/3', 0)}",
        "",
        "## Failing scenarios",
    ]
    for scen in report["scenarios"]:
        if not scen["scenario_pass"]:
            lines.append(
                f"- `{scen['id']}` — pass_count={scen['pass_count']}/{len(scen['runs'])}"
                f" tags={sorted({t for r in scen['runs'] for t in r['tags']})}"
            )
    lines.append("")
    lines.append("## Forbidden-signal hits")
    flagged = [s for s in report["scenarios"]
               if any("[FAKE-ACTION]" in r["tags"] or "[HALLUCINATED-HOLDING]" in r["tags"]
                      for r in s["runs"])]
    if flagged:
        for s in flagged:
            lines.append(f"- `{s['id']}` — RELEASE BLOCKER")
    else:
        lines.append("- None.")
    out_path.write_text("\n".join(lines) + "\n")


def now_utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
