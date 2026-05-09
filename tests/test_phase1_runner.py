"""Tests for Phase 1.5 Wolfram run diagnostics."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from agent.phase1 import (
    build_information_fee_summary,
    diagnose_wolfram_results,
    run_wolfram_scripts,
    write_phase1_diagnostics,
)


def test_run_wolfram_scripts_with_fake_command():
    output_dir = Path("output/test_phase1_runner")
    scenario_dir = output_dir / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "baseline.wl").write_text("(* fake script *)\n", encoding="utf-8")
    _write_manifest(output_dir, ["baseline"])

    fake_runner = output_dir / "fake_wolfram.py"
    fake_runner.write_text(
        """
import json
import sys
from pathlib import Path

script = Path(sys.argv[sys.argv.index("-file") + 1])
scenario_id = script.stem
result_path = script.with_name(f"{scenario_id}_result.json")
result_path.write_text(json.dumps({
    "scenario_id": scenario_id,
    "status": "success",
    "failed_at": "",
    "warnings": [],
    "stage_results": {
        "pricing": {"solve_type": "simultaneous_foc", "rules": "{}"},
        "entry": {
            "solve_type": "enumeration",
            "strategy_profiles": [],
            "pure_nash_conditions": []
        },
        "design": {
            "solve_type": "optimization",
            "objectives": {},
            "candidate_rules": {}
        }
    },
    "equilibrium": {"q_1": "1"},
    "subscribed_players": [],
    "expected_pricing_profits": {"R": "1", "F_1": "1"},
    "contract_terms": {
        "fee": {
            "payer": "F_1",
            "payee": "R",
            "amount": "T",
            "active_in_scenario": False
        }
    },
    "phase1_options": {"solve_mode": "fake"}
}), encoding="utf-8")
print("fake wolfram ran", scenario_id)
""".strip(),
        encoding="utf-8",
    )

    result = run_wolfram_scripts(
        output_dir,
        command_prefix=(sys.executable, str(fake_runner.resolve())),
        timeout_seconds=10,
    )

    assert result.run_summary_path.exists()
    assert result.diagnostics_path.exists()
    assert result.report_path.exists()
    assert result.all_results_path.exists()
    assert result.mechanism_summaries_path.exists()
    assert result.diagnostics.counts["ok"] == 1
    assert result.run_records[0].process_status == "success"

    report = result.report_path.read_text(encoding="utf-8")
    assert "baseline" in report
    assert "pricing, entry, design" in report
    assert "Mechanism: Information Fee" not in report
    mechanism_summaries = json.loads(
        result.mechanism_summaries_path.read_text(encoding="utf-8")
    )
    assert mechanism_summaries["status"] == "not_applicable"


def test_diagnose_wolfram_results_marks_missing_result():
    output_dir = Path("output/test_phase1_missing_result")
    scenario_dir = output_dir / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "missing.wl").write_text("(* fake script *)\n", encoding="utf-8")
    _write_manifest(output_dir, ["missing"])

    diagnostics = diagnose_wolfram_results(output_dir)

    assert diagnostics.counts["missing_result"] == 1
    scenario = diagnostics.scenarios[0]
    assert scenario.scenario_id == "missing"
    assert "result_json" in scenario.missing_sections


def test_information_fee_handler_groups_profiles():
    summary = build_information_fee_summary(
        {
            "S0_no_sb": _result(
                subscribers=[],
                r_profit="10",
                m1_profit="5",
                m2_profit="7",
            ),
            "S11_no_sb": _result(
                subscribers=["M1"],
                r_profit="11",
                m1_profit="8",
                m2_profit="6",
            ),
            "S2_no_sb": _result(
                subscribers=["M1", "M2"],
                r_profit="12",
                m1_profit="9",
                m2_profit="10",
            ),
        }
    )

    group = summary["groups"]["no_sb"]
    assert group["baseline"] == "S0_no_sb"
    assert group["profiles"]["S11_no_sb"]["candidate_T"] == "(8) - (5)"
    assert group["profiles"]["S2_no_sb"]["candidate_T"] == "Min[(9) - (5), (10) - (7)]"
    assert group["profiles"]["S0_no_sb"]["feasible_T_conditions"] == ["T >= 0"]
    assert group["profiles"]["S2_no_sb"]["candidate_T_value"] == "3"
    assert group["profiles"]["S2_no_sb"]["platform_objective_value"] == "18"
    assert group["comparison"]["best_profile"] == "S2_no_sb"
    assert group["comparison"]["best_objective_value"] == "18"


def test_write_phase1_diagnostics_skips_mechanisms_for_plain_game():
    output_dir = Path("output/test_phase1_plain_game")
    scenario_dir = output_dir / "scenarios"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    (scenario_dir / "plain.wl").write_text("(* fake script *)\n", encoding="utf-8")
    _write_manifest(output_dir, ["plain"])
    (scenario_dir / "plain_result.json").write_text(
        json.dumps(
            {
                "scenario_id": "plain",
                "status": "success",
                "failed_at": "",
                "warnings": [],
                "stage_results": {
                    "quantity": {
                        "solve_type": "simultaneous_foc",
                        "rules": "{q -> 1}",
                    }
                },
                "equilibrium": {"q": "1"},
                "expected_pricing_profits": {"Firm": "10"},
                "phase1_options": {"solve_mode": "symbolic"},
            }
        ),
        encoding="utf-8",
    )

    diagnostics = write_phase1_diagnostics(output_dir)

    assert diagnostics.counts["ok"] == 1
    mechanism_summaries = json.loads(
        (output_dir / "mechanism_summaries.json").read_text(encoding="utf-8")
    )
    report = (output_dir / "phase1_report.md").read_text(encoding="utf-8")
    assert mechanism_summaries["status"] == "not_applicable"
    assert mechanism_summaries["handlers"] == {}
    assert "Mechanism: Information Fee" not in report


def _write_manifest(output_dir: Path, scenario_ids: list[str]) -> None:
    manifest = {
        "generator": "phase1-wolfram-stage-driven-v1",
        "title": "Runner Smoke",
        "method": "static_foc",
        "options": {"solve_mode": "symbolic"},
        "scenario_count": len(scenario_ids),
        "scenarios": [
            {
                "scenario_id": scenario_id,
                "script": f"scenarios/{scenario_id}.wl",
                "result": f"scenarios/{scenario_id}_result.json",
            }
            for scenario_id in scenario_ids
        ],
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )


def _result(
    *,
    subscribers: list[str],
    r_profit: str,
    m1_profit: str,
    m2_profit: str,
) -> dict:
    return {
        "status": "success",
        "subscribed_players": subscribers,
        "expected_pricing_profits": {
            "R": r_profit,
            "M1": m1_profit,
            "M2": m2_profit,
        },
        "contract_terms": {
            "T_M1": {
                "payer": "M1",
                "payee": "R",
                "amount": "T",
                "active_in_scenario": "M1" in subscribers,
            },
            "T_M2": {
                "payer": "M2",
                "payee": "R",
                "amount": "T",
                "active_in_scenario": "M2" in subscribers,
            },
        },
    }
