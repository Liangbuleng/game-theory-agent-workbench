"""Run and diagnose Phase 1 Wolfram script outputs."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from agent.phase1.mechanisms import (
    render_mechanism_sections,
    run_mechanism_handlers,
)


@dataclass(frozen=True)
class WolframRunOptions:
    """Options for running generated Wolfram scripts."""

    wolframscript_path: str | Path | None = None
    command_prefix: tuple[str, ...] | None = None
    timeout_seconds: int = 180
    scenario_ids: tuple[str, ...] | None = None
    clear_existing_results: bool = True
    logs_dir_name: str = "run_logs"

    def __post_init__(self) -> None:
        if self.timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self.wolframscript_path and self.command_prefix:
            raise ValueError("use either wolframscript_path or command_prefix, not both")


@dataclass(frozen=True)
class ScenarioRunRecord:
    scenario_id: str
    script_path: Path
    result_path: Path
    stdout_path: Path
    stderr_path: Path
    command: list[str]
    returncode: int | None
    timed_out: bool
    duration_seconds: float
    process_status: str
    error: str | None = None

    def to_dict(self, output_dir: Path) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "script": _relative_or_string(self.script_path, output_dir),
            "result": _relative_or_string(self.result_path, output_dir),
            "stdout": _relative_or_string(self.stdout_path, output_dir),
            "stderr": _relative_or_string(self.stderr_path, output_dir),
            "command": self.command,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "duration_seconds": round(self.duration_seconds, 3),
            "process_status": self.process_status,
            "error": self.error,
        }


@dataclass(frozen=True)
class ScenarioDiagnostics:
    scenario_id: str
    script_path: Path
    result_path: Path
    result_found: bool
    result_status: str
    process_status: str | None
    returncode: int | None
    timed_out: bool
    failed_at: str
    warnings: list[str]
    stage_ids: list[str]
    equilibrium_vars: list[str]
    missing_sections: list[str] = field(default_factory=list)
    issue_summary: list[str] = field(default_factory=list)

    @property
    def outcome(self) -> str:
        if self.timed_out:
            return "timeout"
        if not self.result_found:
            return "missing_result"
        if self.process_status not in {None, "success"}:
            return "process_error"
        if self.result_status != "success":
            return "solver_issue"
        if self.warnings or self.missing_sections:
            return "needs_review"
        return "ok"

    def to_dict(self, output_dir: Path) -> dict[str, object]:
        return {
            "scenario_id": self.scenario_id,
            "outcome": self.outcome,
            "script": _relative_or_string(self.script_path, output_dir),
            "result": _relative_or_string(self.result_path, output_dir),
            "result_found": self.result_found,
            "result_status": self.result_status,
            "process_status": self.process_status,
            "returncode": self.returncode,
            "timed_out": self.timed_out,
            "failed_at": self.failed_at,
            "warnings": self.warnings,
            "stage_ids": self.stage_ids,
            "equilibrium_vars": self.equilibrium_vars,
            "missing_sections": self.missing_sections,
            "issue_summary": self.issue_summary,
        }


@dataclass(frozen=True)
class Phase1Diagnostics:
    output_dir: Path
    generated_at: str
    manifest: dict[str, object]
    scenarios: list[ScenarioDiagnostics]

    @property
    def counts(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for scenario in self.scenarios:
            counts[scenario.outcome] = counts.get(scenario.outcome, 0) + 1
        counts["total"] = len(self.scenarios)
        return counts

    def to_dict(self) -> dict[str, object]:
        return {
            "generated_at": self.generated_at,
            "output_dir": str(self.output_dir),
            "manifest": self.manifest,
            "counts": self.counts,
            "scenarios": [
                scenario.to_dict(self.output_dir) for scenario in self.scenarios
            ],
        }


@dataclass(frozen=True)
class WolframRunResult:
    output_dir: Path
    run_summary_path: Path
    diagnostics_path: Path
    report_path: Path
    all_results_path: Path
    mechanism_summaries_path: Path
    run_records: list[ScenarioRunRecord]
    diagnostics: Phase1Diagnostics


def run_wolfram_scripts(
    output_dir: str | Path,
    *,
    wolframscript_path: str | Path | None = None,
    command_prefix: Iterable[str] | None = None,
    timeout_seconds: int = 180,
    scenario_ids: Iterable[str] | None = None,
    clear_existing_results: bool = True,
) -> WolframRunResult:
    """Run generated scenario scripts and write Phase 1.5 diagnostics."""

    options = WolframRunOptions(
        wolframscript_path=wolframscript_path,
        command_prefix=tuple(command_prefix) if command_prefix is not None else None,
        timeout_seconds=timeout_seconds,
        scenario_ids=tuple(scenario_ids) if scenario_ids is not None else None,
        clear_existing_results=clear_existing_results,
    )
    root = Path(output_dir).resolve()
    manifest = load_phase1_manifest(root)
    entries = _selected_entries(manifest, options.scenario_ids)
    command_prefix_resolved = _resolve_command_prefix(options)

    logs_dir = root / options.logs_dir_name
    logs_dir.mkdir(parents=True, exist_ok=True)

    records: list[ScenarioRunRecord] = []
    for entry in entries:
        records.append(
            _run_one_scenario(root, entry, command_prefix_resolved, logs_dir, options)
        )

    diagnostics = diagnose_wolfram_results(root, run_records=records)
    run_summary_path = root / "run_summary.json"
    diagnostics_path = root / "phase1_diagnostics.json"
    report_path = root / "phase1_report.md"
    all_results_path = root / "all_results.json"
    mechanism_summaries_path = root / "mechanism_summaries.json"

    all_results = _collect_all_results(root, manifest)
    all_results_path.write_text(
        json.dumps(all_results, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    mechanism_summaries = run_mechanism_handlers(all_results, manifest)
    mechanism_summaries_path.write_text(
        json.dumps(mechanism_summaries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    run_summary = {
        "generated_at": _now_iso(),
        "output_dir": str(root),
        "records": [record.to_dict(root) for record in records],
        "counts": diagnostics.counts,
    }
    run_summary_path.write_text(
        json.dumps(run_summary, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    diagnostics_path.write_text(
        json.dumps(diagnostics.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    report_path.write_text(
        render_phase1_report(
            diagnostics,
            all_results=all_results,
            mechanism_summaries=mechanism_summaries,
        ),
        encoding="utf-8",
    )

    return WolframRunResult(
        output_dir=root,
        run_summary_path=run_summary_path,
        diagnostics_path=diagnostics_path,
        report_path=report_path,
        all_results_path=all_results_path,
        mechanism_summaries_path=mechanism_summaries_path,
        run_records=records,
        diagnostics=diagnostics,
    )


def diagnose_wolfram_results(
    output_dir: str | Path,
    *,
    run_records: Iterable[ScenarioRunRecord] | None = None,
) -> Phase1Diagnostics:
    """Read scenario result JSON files and summarize Phase 1 health."""

    root = Path(output_dir).resolve()
    manifest = load_phase1_manifest(root)
    record_map = {
        record.scenario_id: record for record in (run_records or [])
    }

    scenarios = []
    for entry in manifest.get("scenarios", []):
        scenario_id = str(entry["scenario_id"])
        script_path = root / str(entry["script"])
        result_path = root / str(entry["result"])
        record = record_map.get(scenario_id)
        result = _read_json(result_path)
        diagnostics = _diagnose_scenario(
            scenario_id=scenario_id,
            script_path=script_path,
            result_path=result_path,
            result=result,
            record=record,
        )
        scenarios.append(diagnostics)

    return Phase1Diagnostics(
        output_dir=root,
        generated_at=_now_iso(),
        manifest=manifest,
        scenarios=scenarios,
    )


def write_phase1_diagnostics(
    output_dir: str | Path,
    *,
    run_records: Iterable[ScenarioRunRecord] | None = None,
) -> Phase1Diagnostics:
    """Write diagnostics JSON and Markdown report for an existing output dir."""

    root = Path(output_dir).resolve()
    diagnostics = diagnose_wolfram_results(root, run_records=run_records)
    all_results = _collect_all_results(root, diagnostics.manifest)
    mechanism_summaries = run_mechanism_handlers(all_results, diagnostics.manifest)
    (root / "phase1_diagnostics.json").write_text(
        json.dumps(diagnostics.to_dict(), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "mechanism_summaries.json").write_text(
        json.dumps(mechanism_summaries, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "phase1_report.md").write_text(
        render_phase1_report(
            diagnostics,
            all_results=all_results,
            mechanism_summaries=mechanism_summaries,
        ),
        encoding="utf-8",
    )
    return diagnostics


def render_phase1_report(
    diagnostics: Phase1Diagnostics,
    *,
    all_results: dict[str, object] | None = None,
    mechanism_summaries: dict[str, object] | None = None,
) -> str:
    """Render a human-readable Phase 1.5 report."""

    lines: list[str] = []
    emit = lines.append
    manifest = diagnostics.manifest
    options = manifest.get("options", {})
    result_map = all_results or _collect_all_results(
        diagnostics.output_dir,
        diagnostics.manifest,
    )
    scenario_by_id = {scenario.scenario_id: scenario for scenario in diagnostics.scenarios}
    successful_ids = [
        scenario.scenario_id
        for scenario in diagnostics.scenarios
        if scenario.outcome in {"ok", "needs_review", "solver_issue"}
    ]
    failed_ids = [
        scenario.scenario_id
        for scenario in diagnostics.scenarios
        if scenario.outcome not in {"ok", "needs_review", "solver_issue"}
    ]

    emit("# Phase 1.5 Wolfram Run Report")
    emit("")
    emit(f"- Title: {manifest.get('title', '')}")
    emit(f"- Method: {manifest.get('method', '')}")
    emit(f"- Output dir: `{diagnostics.output_dir}`")
    if options:
        emit(f"- Solve mode: `{options.get('solve_mode', '')}`")
        emit(f"- Solve timeout: `{options.get('solve_timeout_seconds', '')}` seconds")
        emit(
            f"- Simplify timeout: `{options.get('simplify_timeout_seconds', '')}` seconds"
        )
    emit("")
    emit("## Summary")
    emit("")
    for key in ["total", "ok", "needs_review", "solver_issue", "timeout", "missing_result", "process_error"]:
        if key in diagnostics.counts:
            emit(f"- {key}: {diagnostics.counts[key]}")
    emit("")
    emit("## Executive Summary")
    emit("")
    emit(_render_executive_summary(diagnostics, result_map))
    emit("")
    emit("## Scenario Outcome Table")
    emit("")
    emit("| Scenario | Outcome | Meaning | Equilibrium | Payoffs | Subscriptions | Stages |")
    emit("|---|---|---|---|---|---|---|")
    for scenario in diagnostics.scenarios:
        result = _scenario_result(result_map, scenario.scenario_id)
        emit(
            "| "
            + " | ".join(
                [
                    _md_cell(scenario.scenario_id),
                    _md_cell(scenario.outcome),
                    _md_cell(_outcome_meaning(scenario)),
                    _md_cell(_compact_mapping(result.get("equilibrium"))),
                    _md_cell(_compact_mapping(result.get("expected_pricing_profits"))),
                    _md_cell(_compact_list(result.get("subscribed_players"))),
                    _md_cell(", ".join(scenario.stage_ids) or "none"),
                ]
            )
            + " |"
        )

    if successful_ids:
        emit("")
        emit("## Equilibrium Decisions")
        emit("")
        decision_names = _ordered_result_keys(result_map, "equilibrium", successful_ids)
        emit("| Scenario | " + " | ".join(_md_cell(name) for name in decision_names) + " |")
        emit("|---" + "|---" * len(decision_names) + "|")
        for scenario_id in successful_ids:
            result = _scenario_result(result_map, scenario_id)
            equilibrium = _mapping(result.get("equilibrium"))
            emit(
                "| "
                + " | ".join(
                    [_md_cell(scenario_id)]
                    + [_md_cell(_display_value(equilibrium.get(name, ""))) for name in decision_names]
                )
                + " |"
            )

        payoff_names = _ordered_result_keys(
            result_map,
            "expected_pricing_profits",
            successful_ids,
        )
        if payoff_names:
            emit("")
            emit("## Expected Payoffs")
            emit("")
            emit("| Scenario | " + " | ".join(_md_cell(name) for name in payoff_names) + " |")
            emit("|---" + "|---" * len(payoff_names) + "|")
            for scenario_id in successful_ids:
                result = _scenario_result(result_map, scenario_id)
                payoffs = _mapping(result.get("expected_pricing_profits"))
                emit(
                    "| "
                    + " | ".join(
                        [_md_cell(scenario_id)]
                        + [_md_cell(_display_value(payoffs.get(name, ""))) for name in payoff_names]
                    )
                    + " |"
                )

        emit("")
        emit("## Scenario Result Cards")
        emit("")
        for scenario_id in successful_ids:
            scenario = scenario_by_id[scenario_id]
            result = _scenario_result(result_map, scenario_id)
            emit(f"### {scenario_id}")
            emit("")
            emit(f"- Status: `{scenario.outcome}`")
            emit(f"- Meaning: {_outcome_meaning(scenario)}")
            emit(f"- Equilibrium decisions: {_compact_mapping(result.get('equilibrium'))}")
            emit(f"- Expected payoffs: {_compact_mapping(result.get('expected_pricing_profits'))}")
            emit(f"- Subscribed players: {_compact_list(result.get('subscribed_players'))}")
            contract_summary = _contract_summary(result.get("contract_terms"))
            if contract_summary:
                emit(f"- Contract terms: {contract_summary}")
            emit(f"- Solving stages: {', '.join(scenario.stage_ids) or 'none'}")
            if scenario.warnings:
                emit(f"- Warnings: {'; '.join(scenario.warnings)}")
            emit("")

    issue_scenarios = [
        scenario for scenario in diagnostics.scenarios if scenario.outcome != "ok"
    ]
    if issue_scenarios:
        emit("")
        emit("## Warnings And Missing Results")
        emit("")
        for scenario in issue_scenarios:
            emit(f"### {scenario.scenario_id}")
            emit("")
            emit(f"- Meaning: {_outcome_meaning(scenario)}")
            for item in scenario.issue_summary or ["needs manual review"]:
                emit(f"- {item}")
            emit("")

    mechanism_lines = render_mechanism_sections(mechanism_summaries)
    if mechanism_lines:
        emit("")
        lines.extend(mechanism_lines)

    emit("")
    emit("## Raw Artifact Index")
    emit("")
    for scenario in diagnostics.scenarios:
        result = _scenario_result(result_map, scenario.scenario_id)
        emit(f"### {scenario.scenario_id}")
        emit("")
        emit(f"- Result file: `{_relative_or_string(scenario.result_path, diagnostics.output_dir)}`")
        emit(f"- Process status: `{scenario.process_status or ''}`")
        emit(f"- Return code: `{scenario.returncode}`")
        emit(f"- Timed out: `{scenario.timed_out}`")
        emit(f"- Result status: `{_display_value(result.get('status', scenario.result_status))}`")
        if scenario.failed_at:
            emit(f"- Failed at: `{scenario.failed_at}`")
        emit(f"- Stage result keys: {', '.join(scenario.stage_ids) or 'none'}")
        emit("")

    return "\n".join(lines).rstrip() + "\n"


def _render_executive_summary(
    diagnostics: Phase1Diagnostics,
    all_results: dict[str, object],
) -> str:
    total = diagnostics.counts.get("total", len(diagnostics.scenarios))
    ok = diagnostics.counts.get("ok", 0)
    review = diagnostics.counts.get("needs_review", 0)
    solver_issue = diagnostics.counts.get("solver_issue", 0)
    missing = diagnostics.counts.get("missing_result", 0)
    timeout = diagnostics.counts.get("timeout", 0)
    process_error = diagnostics.counts.get("process_error", 0)

    if total == 0:
        return "No scenarios were found in the Phase 1 manifest."
    if ok + review + solver_issue == 0:
        if missing == total:
            return (
                f"All {total} scenarios ran without producing result JSON files. "
                "The current run cannot support equilibrium, payoff, or mechanism "
                "comparisons yet; inspect the Wolfram stdout/stderr logs and rerun "
                "after the script-generation/runtime issue is fixed."
            )
        return (
            f"No scenario produced a usable equilibrium result. Missing results: "
            f"{missing}; process errors: {process_error}; timeouts: {timeout}."
        )

    usable = ok + review + solver_issue
    first_success = next(
        (
            scenario.scenario_id
            for scenario in diagnostics.scenarios
            if scenario.outcome in {"ok", "needs_review", "solver_issue"}
        ),
        "",
    )
    result = _scenario_result(all_results, first_success) if first_success else {}
    decisions = _compact_mapping(result.get("equilibrium"))
    payoffs = _compact_mapping(result.get("expected_pricing_profits"))
    return (
        f"{usable} of {total} scenarios produced usable result structures. "
        f"The first usable scenario is `{first_success}` with equilibrium decisions "
        f"{decisions} and expected payoffs {payoffs}. "
        f"Scenarios requiring attention: {total - usable}."
    )


def _outcome_meaning(scenario: ScenarioDiagnostics) -> str:
    if scenario.outcome == "ok":
        return "usable result"
    if scenario.outcome == "needs_review":
        return "usable result with warnings"
    if scenario.outcome == "solver_issue":
        return "result JSON exists but the solver reported an issue"
    if scenario.outcome == "missing_result":
        return "Wolfram ran or was diagnosed, but no result JSON was produced"
    if scenario.outcome == "timeout":
        return "wolframscript exceeded the configured timeout"
    if scenario.outcome == "process_error":
        return "wolframscript returned an execution error"
    return "needs manual review"


def _scenario_result(all_results: dict[str, object], scenario_id: str) -> dict[str, object]:
    value = all_results.get(scenario_id, {})
    return value if isinstance(value, dict) else {}


def _ordered_result_keys(
    all_results: dict[str, object],
    field: str,
    scenario_ids: list[str],
) -> list[str]:
    keys: list[str] = []
    seen: set[str] = set()
    for scenario_id in scenario_ids:
        result = _scenario_result(all_results, scenario_id)
        for key in _mapping(result.get(field)):
            if key == "none" or key in seen:
                continue
            seen.add(key)
            keys.append(key)
    return keys


def _mapping(value: object) -> dict[str, object]:
    return value if isinstance(value, dict) else {}


def _compact_mapping(value: object, *, max_items: int = 4) -> str:
    mapping = _mapping(value)
    if not mapping:
        return "none"
    items = [
        f"{key}={_display_value(item)}"
        for key, item in mapping.items()
        if key != "none"
    ]
    if not items:
        return _display_value(next(iter(mapping.values()), "none"))
    if len(items) > max_items:
        return ", ".join(items[:max_items]) + f", ... (+{len(items) - max_items})"
    return ", ".join(items)


def _compact_list(value: object) -> str:
    if isinstance(value, list):
        return ", ".join(str(item) for item in value) or "none"
    if value is None or value == "":
        return "none"
    return str(value)


def _contract_summary(value: object) -> str:
    terms = _mapping(value)
    if not terms:
        return ""
    summaries = []
    for name, raw_term in terms.items():
        term = _mapping(raw_term)
        payer = _display_value(term.get("payer", "?"))
        payee = _display_value(term.get("payee", "?"))
        amount = _display_value(term.get("amount", "?"))
        active = term.get("active_in_scenario")
        active_text = "" if active is None else f", active={active}"
        summaries.append(f"{name}: {payer}->{payee}, amount={amount}{active_text}")
    return "; ".join(summaries)


def _display_value(value: object) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if text else ""


def _md_cell(value: object) -> str:
    text = _display_value(value)
    return text.replace("|", "\\|")


def load_phase1_manifest(output_dir: str | Path) -> dict[str, object]:
    manifest_path = Path(output_dir) / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"missing Phase 1 manifest: {manifest_path}")
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def _run_one_scenario(
    root: Path,
    entry: dict[str, object],
    command_prefix: list[str],
    logs_dir: Path,
    options: WolframRunOptions,
) -> ScenarioRunRecord:
    scenario_id = str(entry["scenario_id"])
    script_path = root / str(entry["script"])
    result_path = root / str(entry["result"])
    stdout_path = logs_dir / f"{_safe_filename(scenario_id)}.stdout.txt"
    stderr_path = logs_dir / f"{_safe_filename(scenario_id)}.stderr.txt"
    command = [*command_prefix, "-file", str(script_path)]

    if options.clear_existing_results and result_path.exists():
        result_path.unlink()

    started = time.perf_counter()
    returncode: int | None = None
    timed_out = False
    error: str | None = None
    stdout_text = ""
    stderr_text = ""
    try:
        completed = subprocess.run(
            command,
            cwd=root,
            capture_output=True,
            text=True,
            timeout=options.timeout_seconds,
            check=False,
        )
        returncode = completed.returncode
        stdout_text = completed.stdout or ""
        stderr_text = completed.stderr or ""
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout_text = _decode_process_text(exc.stdout)
        stderr_text = _decode_process_text(exc.stderr)
        error = f"timed out after {options.timeout_seconds} seconds"
    except OSError as exc:
        error = str(exc)

    duration = time.perf_counter() - started
    stdout_path.write_text(stdout_text, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr_text, encoding="utf-8", errors="replace")

    if timed_out:
        process_status = "timeout"
    elif error:
        process_status = "process_error"
    elif returncode == 0:
        process_status = "success"
    else:
        process_status = "process_error"

    return ScenarioRunRecord(
        scenario_id=scenario_id,
        script_path=script_path,
        result_path=result_path,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        command=command,
        returncode=returncode,
        timed_out=timed_out,
        duration_seconds=duration,
        process_status=process_status,
        error=error,
    )


def _diagnose_scenario(
    *,
    scenario_id: str,
    script_path: Path,
    result_path: Path,
    result: dict[str, object] | None,
    record: ScenarioRunRecord | None,
) -> ScenarioDiagnostics:
    result_found = result is not None
    result_status = str(result.get("status", "missing_result")) if result else "missing_result"
    failed_at = str(result.get("failed_at", "")) if result else ""
    warnings = [str(item) for item in result.get("warnings", [])] if result else []
    stage_results = result.get("stage_results", {}) if result else {}
    if not isinstance(stage_results, dict):
        stage_results = {}
    equilibrium = result.get("equilibrium", {}) if result else {}
    if not isinstance(equilibrium, dict):
        equilibrium = {}

    missing_sections: list[str] = []
    issues: list[str] = []
    if not script_path.exists():
        missing_sections.append("script")
        issues.append("scenario script is missing")
    if not result_found:
        missing_sections.append("result_json")
        issues.append("result JSON is missing")
        issues.extend(_log_issue_hints(result_path.parent.parent, scenario_id))
    if result_found and not stage_results:
        missing_sections.append("stage_results")
        issues.append("stage_results is empty or missing")
    if result_found and result_status != "success":
        issues.append(f"Wolfram result status is {result_status!r}")
    if failed_at:
        issues.append(f"failed_at: {failed_at}")
    if warnings:
        issues.extend(f"warning: {warning}" for warning in warnings)

    stage_ids = list(stage_results.keys())
    for stage_id, stage_data in stage_results.items():
        if not isinstance(stage_data, dict):
            continue
        solve_type = stage_data.get("solve_type")
        if solve_type in {"enumeration", "discrete_payoff_matrix"}:
            if "strategy_profiles" not in stage_data:
                missing_sections.append(f"{stage_id}.strategy_profiles")
            if "pure_nash_conditions" not in stage_data:
                missing_sections.append(f"{stage_id}.pure_nash_conditions")
        if solve_type == "optimization":
            if "objectives" not in stage_data:
                missing_sections.append(f"{stage_id}.objectives")
            if "candidate_rules" not in stage_data:
                missing_sections.append(f"{stage_id}.candidate_rules")

    equilibrium_vars = [
        key
        for key, value in equilibrium.items()
        if key != "none" and str(value).strip()
    ]

    return ScenarioDiagnostics(
        scenario_id=scenario_id,
        script_path=script_path,
        result_path=result_path,
        result_found=result_found,
        result_status=result_status,
        process_status=record.process_status if record else None,
        returncode=record.returncode if record else None,
        timed_out=record.timed_out if record else False,
        failed_at=failed_at,
        warnings=warnings,
        stage_ids=stage_ids,
        equilibrium_vars=equilibrium_vars,
        missing_sections=_dedupe(missing_sections),
        issue_summary=_dedupe(issues),
    )


def _resolve_command_prefix(options: WolframRunOptions) -> list[str]:
    if options.command_prefix is not None:
        return list(options.command_prefix)
    if options.wolframscript_path:
        path = Path(options.wolframscript_path)
        if not path.exists():
            raise FileNotFoundError(f"wolframscript not found: {path}")
        return [str(path)]

    env_path = os.environ.get("WOLFRAMSCRIPT_PATH")
    if env_path:
        path = Path(env_path)
        if path.exists():
            return [str(path)]

    found = shutil.which("wolframscript")
    if found:
        return [found]

    windows_default = Path(
        "C:/Program Files/Wolfram Research/WolframScript/wolframscript.exe"
    )
    if windows_default.exists():
        return [str(windows_default)]

    raise FileNotFoundError(
        "wolframscript not found. Pass wolframscript_path or set WOLFRAMSCRIPT_PATH."
    )


def _selected_entries(
    manifest: dict[str, object],
    scenario_ids: tuple[str, ...] | None,
) -> list[dict[str, object]]:
    entries = list(manifest.get("scenarios", []))
    if scenario_ids is None:
        return entries
    wanted = set(scenario_ids)
    return [entry for entry in entries if str(entry.get("scenario_id")) in wanted]


def _collect_all_results(
    root: Path,
    manifest: dict[str, object],
) -> dict[str, object]:
    results = {}
    for entry in manifest.get("scenarios", []):
        scenario_id = str(entry["scenario_id"])
        result_path = root / str(entry["result"])
        results[scenario_id] = _read_json(result_path) or {
            "status": "missing_result",
            "result": str(result_path),
        }
    return results


def _read_json(path: Path) -> dict[str, object] | None:
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {
            "status": "invalid_json",
            "failed_at": "json_decode",
            "warnings": [f"could not parse {path}"],
        }
    return data if isinstance(data, dict) else {"status": "invalid_json"}


def _decode_process_text(value: str | bytes | None) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def _log_issue_hints(root: Path, scenario_id: str, *, max_items: int = 3) -> list[str]:
    logs_dir = root / "run_logs"
    if not logs_dir.exists():
        return []

    hints: list[str] = []
    for suffix in ["stderr", "stdout"]:
        path = logs_dir / f"{_safe_filename(scenario_id)}.{suffix}.txt"
        if not path.exists():
            continue
        lines = [
            line.strip()
            for line in path.read_text(encoding="utf-8", errors="replace").splitlines()
            if line.strip()
        ]
        for line in lines[:max_items]:
            hints.append(f"{suffix}: {line}")
            if len(hints) >= max_items:
                return hints
    return hints


def _relative_or_string(path: Path, root: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _safe_filename(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
