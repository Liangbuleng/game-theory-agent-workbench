"""Local tests for Phase 1 Wolfram script generation."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

from agent.phase1 import (
    WolframGenerationOptions,
    generate_wolfram_scripts,
    load_modelspec,
)
from agent.schemas import ModelSpec


def test_load_modelspec_yaml_and_generate_wolfram_scripts():
    output_dir = Path("output/test_phase1_wolfram")
    spec_path = output_dir / "modelspec.yaml"
    output_dir.mkdir(parents=True, exist_ok=True)

    spec = ModelSpec.model_validate(_minimal_modelspec())
    spec_path.write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False),
        encoding="utf-8",
    )

    loaded = load_modelspec(spec_path)
    options = WolframGenerationOptions(
        solve_timeout_seconds=45,
        simplify_timeout_seconds=10,
        solve_mode="semi_numeric",
        parameter_values={"a_H": 10},
    )
    result = generate_wolfram_scripts(loaded, output_dir / "wolfram", options=options)

    assert result.run_all_path.exists()
    assert result.readme_path.exists()
    assert result.manifest_path.exists()
    assert set(result.scenario_scripts) == {"baseline"}

    script_text = result.scenario_scripts["baseline"].read_text(encoding="utf-8")
    assert "q1" in script_text
    assert "aH" in script_text
    assert "D1Expr" in script_text
    assert "q_1 * D_1" not in script_text
    assert "active_in_scenario\" -> True" in script_text
    assert "Solve[" in script_text
    assert "stageResults = <||>" in script_text
    assert '"stage_results" -> stageResults' in script_text
    assert "TimeConstrained" in script_text
    assert 'solveMode = "semi_numeric"' in script_text
    assert "aH = 10" in script_text
    assert "Export[outputPath, result, \"JSON\"]" in script_text

    manifest = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert manifest["generator"] == "phase1-wolfram-stage-driven-v1"
    assert manifest["options"]["solve_mode"] == "semi_numeric"
    assert manifest["options"]["parameter_values"] == {"a_H": 10}
    assert manifest["scenario_count"] == 1
    assert manifest["scenarios"][0]["script"].endswith("baseline.wl")


def test_generate_real_phase0_modelspec_when_available():
    spec_path = Path("output/qwen_phase0_finalize_acceptance/modelspec_final.yaml")
    if not spec_path.exists():
        return

    result = generate_wolfram_scripts(spec_path, "output/test_phase1_real_modelspec")
    assert len(result.scenario_scripts) == 8

    sample = result.scenario_scripts["S0_no_sb"].read_text(encoding="utf-8")
    assert "D1NoSbExpr" in sample
    assert "D1_no_sbExpr" not in sample
    assert "expectedAll" in sample
    assert "scenarioInformedPlayers" in sample
    assert "scenarioMechanismProfile" in sample
    assert "mechanismHints" in sample
    assert '"pricing_stage" -> <|' in sample
    assert '"subscription_stage" -> <|' in sample
    assert '"fee_optimization_stage" -> <|' in sample
    assert "pure_nash_conditions" in sample
    assert "candidate_rules" in sample


def _minimal_modelspec() -> dict:
    return {
        "basics": {
            "title": "Underscore Smoke Model",
            "source": None,
            "game_type": "static_simultaneous",
            "unsupported_reason": None,
            "players": [
                {
                    "id": "F_1",
                    "name": "Firm 1",
                    "role": "unspecified",
                    "description": None,
                }
            ],
            "decision_variables": [
                {
                    "name": "q_1",
                    "owner": "F_1",
                    "domain": "NonNegative",
                    "custom_domain": None,
                    "description": None,
                },
                {
                    "name": "T_fee",
                    "owner": "F_1",
                    "domain": "NonNegative",
                    "custom_domain": None,
                    "description": None,
                },
            ],
            "parameters": [
                {
                    "name": "a_H",
                    "domain": "Positive",
                    "custom_domain": None,
                    "fixed_value": None,
                    "description": None,
                }
            ],
            "parameter_constraints": [],
            "information_structure": {
                "random_variables": [],
                "access": [],
                "action_observability": [],
            },
            "decision_timing": {
                "stages": [
                    {
                        "stage_number": 1,
                        "description": "Static choice",
                        "decisions": [
                            {
                                "decider": "F_1",
                                "decision_vars": ["q_1"],
                                "simultaneous_with": [],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "quantity",
                                "description": None,
                            }
                        ],
                    }
                ]
            },
            "demands": [
                {
                    "name": "D_1",
                    "expression": {
                        "formula": "a_H - q_1",
                        "description": None,
                    },
                    "applies_when": None,
                    "description": None,
                }
            ],
            "payoff_components": [
                {
                    "id": "pi_F_1",
                    "player_id": "F_1",
                    "expression": {
                        "formula": "q_1 * D_1",
                        "description": None,
                    },
                    "component_type": "revenue",
                    "applies_to_decision_stage": 1,
                    "applies_when": None,
                    "description": None,
                }
            ],
            "contract_terms": [
                {
                    "name": "fee_term",
                    "payer": "F_1",
                    "payee": "F_1",
                    "formula": "T_fee",
                    "triggered_when": None,
                    "applies_to_decision_stage": 1,
                    "description": None,
                }
            ],
            "scenario_axes": [],
            "scenario_overview": [
                {
                    "id": "baseline",
                    "description": "Baseline scenario",
                    "axis_values": {},
                }
            ],
        },
        "procedure": {
            "method": "static_foc",
            "solving_stages": [
                {
                    "stage_id": "pricing",
                    "description": "Static FOC",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "optimization",
                    "deciders": [
                        {
                            "player_id": "F_1",
                            "decision_vars": ["q_1"],
                            "informed_about": [],
                            "description": None,
                        }
                    ],
                    "profit_function_assignments": {
                        "F_1": ["pi_F_1"],
                    },
                    "uses_demands": ["D_1"],
                    "uses_contract_terms": ["fee_term"],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": None,
                }
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": ["D_1"],
                    "active_payoff_components": {"F_1": ["pi_F_1"]},
                    "active_contract_terms": ["fee_term"],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": None,
            "description": None,
        },
        "research_questions": [],
        "meta": {
            "implicit_assumptions": [],
            "field_confidence": [],
            "version": "modelspec-v1",
        },
    }
