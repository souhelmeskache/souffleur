"""The exceptions report (SPEC-P4 §7): the ONLY artifact a human reads.

Facts and counts only — offsets, ratios, ids — never module prose. This file
crosses to the meta post; the conformance controller still re-reads it.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path


def build(manifest_fields: dict, form_errors: list[str], coverage: dict,
          mass_alarms: list[str], recheck_alarms: list[str],
          rule_exceptions: list[str], samples_taken: int = 0,
          infos: list[str] | None = None,
          mesures_scenario: dict | None = None) -> dict:
    """Blocking = real losses/errors (form, coverage, rule gaps). Alarms are
    nominal review flags. Infos are DECLARED non-conversions whose content is
    provably still present (verbatim nodes) — they never turn the light red.
    mesures_scenario: measured facts of a stage (fiche SCÉNARIO §7) — never
    verdict-bearing on their own."""
    green = not (form_errors or coverage["gaps"] or coverage["overlaps"]
                 or coverage["unanchored_claims"] or rule_exceptions)
    report = {
        "date": date.today().isoformat(),
        "version_convertisseur": manifest_fields.get("version_convertisseur"),
        "verdict": "VERT" if green else "ROUGE",
        "comptages": {
            "form_errors": len(form_errors),
            "coverage_gaps": len(coverage["gaps"]),
            "coverage_overlaps": len(coverage["overlaps"]),
            "unanchored_claims": len(coverage["unanchored_claims"]),
            "mass_alarms": len(mass_alarms),
            "recheck_alarms": len(recheck_alarms),
            "rule_exceptions": len(rule_exceptions),
            "recheck_samples": samples_taken,
            "source_chars": coverage["text_len"],
            "infos": len(infos or []),
        },
        "details": {
            "form_errors": form_errors,
            "coverage_gaps": coverage["gaps"],
            "coverage_overlaps": coverage["overlaps"],
            "unanchored_claims": coverage["unanchored_claims"],
            "mass_alarms": mass_alarms,
            "recheck_alarms": recheck_alarms,
            "rule_exceptions": rule_exceptions,
            "infos_declarees": infos or [],
        },
    }
    if mesures_scenario is not None:
        report["mesures_scenario"] = dict(mesures_scenario)
    return report


def write_report(report: dict, path: Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    return path


def render_md(report: dict) -> str:
    c = report["comptages"]
    lines = [
        f"# rapport d'exceptions — {report['date']}",
        f"verdict: **{report['verdict']}**",
        "",
        "| mesure | valeur |", "|---|---|",
    ]
    for k, v in c.items():
        lines.append(f"| {k} | {v} |")
    if report.get("mesures_scenario"):
        lines += ["", "## mesures étage scénario", "", "| mesure | valeur |",
                  "|---|---|"]
        for k, v in report["mesures_scenario"].items():
            lines.append(f"| {k} | {v} |")
    for section, rows in report["details"].items():
        if rows:
            lines += ["", f"## {section}"]
            lines += [f"- {r}" for r in rows]
    return "\n".join(lines) + "\n"
