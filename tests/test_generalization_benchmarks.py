"""Cross-model generalization benchmarks for Phase 1 generation.

These benchmarks are intentionally hand-authored ModelSpec fixtures. They give
us a fast regression suite for diverse game families without depending on LLM
parsing quality.
"""

from __future__ import annotations

import pytest

from agent.phase1 import generate_wolfram_scripts
from agent.schemas import ModelSpec


@pytest.mark.parametrize(
    ("case_name", "builder", "expected_method", "expected_markers"),
    [
        (
            "cournot_static",
            lambda: _cournot_modelspec(),
            "static_foc",
            [
                '"pricing_stage" -> <|',
                "simultaneous_foc",
                "q1",
                "q2",
                "Solve[",
            ],
        ),
        (
            "bertrand_static",
            lambda: _bertrand_modelspec(),
            "static_foc",
            [
                '"pricing_stage" -> <|',
                "simultaneous_foc",
                "p1",
                "p2",
                "D1Expr",
                "D2Expr",
            ],
        ),
        (
            "stackelberg_quantity",
            lambda: _stackelberg_modelspec(),
            "stackelberg_backward_induction",
            [
                '"follower_stage" -> <|',
                '"leader_stage" -> <|',
                "sequential_foc",
                "qLeader",
                "qFollower",
            ],
        ),
        (
            "binary_entry",
            lambda: _binary_entry_modelspec(),
            "static_foc",
            [
                '"entry_stage" -> <|',
                "discrete_payoff_matrix",
                "strategy_profiles",
                "pure_nash_conditions",
                "{0, 1}",
            ],
        ),
    ],
)
def test_benchmark_modelspecs_generate_phase1_scripts(
    tmp_path,
    case_name: str,
    builder,
    expected_method: str,
    expected_markers: list[str],
):
    spec = ModelSpec.model_validate(builder())
    spec.assert_valid()

    result = generate_wolfram_scripts(spec, tmp_path / case_name)

    assert result.manifest_path.exists()
    assert len(result.scenario_scripts) == 1

    manifest_text = result.manifest_path.read_text(encoding="utf-8")
    assert expected_method in manifest_text

    sample_path = next(iter(result.scenario_scripts.values()))
    sample = sample_path.read_text(encoding="utf-8")
    assert "stageResults = <||>" in sample
    assert '"stage_results" -> stageResults' in sample
    assert "scenarioMechanismProfile" in sample
    for marker in expected_markers:
        assert marker in sample


def test_unsupported_benchmark_spec_validates_without_phase1_claims():
    spec = ModelSpec.model_validate(_unsupported_modelspec())
    spec.assert_valid()

    assert spec.basics.game_type.value == "unsupported"
    assert spec.basics.unsupported_reason
    assert spec.procedure.method.value == "unsupported"


def _cournot_modelspec() -> dict:
    return {
        "basics": {
            "title": "Cournot Benchmark",
            "source": None,
            "game_type": "static_simultaneous",
            "unsupported_reason": None,
            "players": [
                {"id": "F1", "name": "Firm 1", "role": "symmetric"},
                {"id": "F2", "name": "Firm 2", "role": "symmetric"},
            ],
            "decision_variables": [
                {"name": "q1", "owner": "F1", "domain": "NonNegative"},
                {"name": "q2", "owner": "F2", "domain": "NonNegative"},
            ],
            "parameters": [
                {"name": "a", "domain": "Positive"},
                {"name": "c1", "domain": "NonNegative"},
                {"name": "c2", "domain": "NonNegative"},
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
                        "description": "Simultaneous quantity choice",
                        "decisions": [
                            {
                                "decider": "F1",
                                "decision_vars": ["q1"],
                                "simultaneous_with": ["F2"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "quantity",
                            },
                            {
                                "decider": "F2",
                                "decision_vars": ["q2"],
                                "simultaneous_with": ["F1"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "quantity",
                            },
                        ],
                    }
                ]
            },
            "demands": [
                {
                    "name": "D",
                    "expression": {"formula": "a - q1 - q2"},
                }
            ],
            "payoff_components": [
                {
                    "id": "pi_F1",
                    "player_id": "F1",
                    "expression": {"formula": "(D - c1) * q1"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
                {
                    "id": "pi_F2",
                    "player_id": "F2",
                    "expression": {"formula": "(D - c2) * q2"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
            ],
            "contract_terms": [],
            "scenario_axes": [],
            "scenario_overview": [
                {"id": "baseline", "description": "Baseline", "axis_values": {}}
            ],
        },
        "procedure": {
            "method": "static_foc",
            "solving_stages": [
                {
                    "stage_id": "pricing_stage",
                    "description": "Simultaneous Cournot FOCs",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "simultaneous_foc",
                    "deciders": [
                        {"player_id": "F1", "decision_vars": ["q1"], "informed_about": []},
                        {"player_id": "F2", "decision_vars": ["q2"], "informed_about": []},
                    ],
                    "profit_function_assignments": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "uses_demands": ["D"],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": "closed-form Cournot equilibrium",
                }
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": ["D"],
                    "active_payoff_components": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "active_contract_terms": [],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": None,
            "description": None,
        },
        "research_questions": [],
        "meta": {"implicit_assumptions": [], "field_confidence": [], "version": "modelspec-v1"},
    }


def _bertrand_modelspec() -> dict:
    return {
        "basics": {
            "title": "Bertrand Benchmark",
            "source": None,
            "game_type": "static_simultaneous",
            "unsupported_reason": None,
            "players": [
                {"id": "F1", "name": "Firm 1", "role": "symmetric"},
                {"id": "F2", "name": "Firm 2", "role": "symmetric"},
            ],
            "decision_variables": [
                {"name": "p1", "owner": "F1", "domain": "NonNegative"},
                {"name": "p2", "owner": "F2", "domain": "NonNegative"},
            ],
            "parameters": [
                {"name": "a", "domain": "Positive"},
                {"name": "b", "domain": "NonNegative"},
                {"name": "c1", "domain": "NonNegative"},
                {"name": "c2", "domain": "NonNegative"},
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
                        "description": "Simultaneous price choice",
                        "decisions": [
                            {
                                "decider": "F1",
                                "decision_vars": ["p1"],
                                "simultaneous_with": ["F2"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "pricing",
                            },
                            {
                                "decider": "F2",
                                "decision_vars": ["p2"],
                                "simultaneous_with": ["F1"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "pricing",
                            },
                        ],
                    }
                ]
            },
            "demands": [
                {"name": "D1", "expression": {"formula": "a - p1 + b * (p2 - p1)"}},
                {"name": "D2", "expression": {"formula": "a - p2 + b * (p1 - p2)"}},
            ],
            "payoff_components": [
                {
                    "id": "pi_F1",
                    "player_id": "F1",
                    "expression": {"formula": "(p1 - c1) * D1"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
                {
                    "id": "pi_F2",
                    "player_id": "F2",
                    "expression": {"formula": "(p2 - c2) * D2"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
            ],
            "contract_terms": [],
            "scenario_axes": [],
            "scenario_overview": [
                {"id": "baseline", "description": "Baseline", "axis_values": {}}
            ],
        },
        "procedure": {
            "method": "static_foc",
            "solving_stages": [
                {
                    "stage_id": "pricing_stage",
                    "description": "Simultaneous Bertrand FOCs",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "simultaneous_foc",
                    "deciders": [
                        {"player_id": "F1", "decision_vars": ["p1"], "informed_about": []},
                        {"player_id": "F2", "decision_vars": ["p2"], "informed_about": []},
                    ],
                    "profit_function_assignments": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "uses_demands": ["D1", "D2"],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": "linear Bertrand FOCs",
                }
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": ["D1", "D2"],
                    "active_payoff_components": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "active_contract_terms": [],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": None,
            "description": None,
        },
        "research_questions": [],
        "meta": {"implicit_assumptions": [], "field_confidence": [], "version": "modelspec-v1"},
    }


def _stackelberg_modelspec() -> dict:
    return {
        "basics": {
            "title": "Stackelberg Benchmark",
            "source": None,
            "game_type": "stackelberg",
            "unsupported_reason": None,
            "players": [
                {"id": "Leader", "name": "Leader", "role": "leader"},
                {"id": "Follower", "name": "Follower", "role": "follower"},
            ],
            "decision_variables": [
                {"name": "qLeader", "owner": "Leader", "domain": "NonNegative"},
                {"name": "qFollower", "owner": "Follower", "domain": "NonNegative"},
            ],
            "parameters": [
                {"name": "a", "domain": "Positive"},
                {"name": "cL", "domain": "NonNegative"},
                {"name": "cF", "domain": "NonNegative"},
            ],
            "parameter_constraints": [],
            "information_structure": {
                "random_variables": [],
                "access": [],
                "action_observability": [
                    {
                        "observer": "Follower",
                        "observed_player": "Leader",
                        "observed_decision_vars": ["qLeader"],
                        "when": "before follower move",
                    }
                ],
            },
            "decision_timing": {
                "stages": [
                    {
                        "stage_number": 1,
                        "description": "Leader moves first",
                        "decisions": [
                            {
                                "decider": "Leader",
                                "decision_vars": ["qLeader"],
                                "simultaneous_with": [],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "quantity",
                            }
                        ],
                    },
                    {
                        "stage_number": 2,
                        "description": "Follower responds",
                        "decisions": [
                            {
                                "decider": "Follower",
                                "decision_vars": ["qFollower"],
                                "simultaneous_with": [],
                                "move_order": 1,
                                "observes_before_deciding": ["qLeader"],
                                "decision_role": "quantity",
                            }
                        ],
                    },
                ]
            },
            "demands": [
                {"name": "D", "expression": {"formula": "a - qLeader - qFollower"}}
            ],
            "payoff_components": [
                {
                    "id": "pi_Leader",
                    "player_id": "Leader",
                    "expression": {"formula": "(D - cL) * qLeader"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
                {
                    "id": "pi_Follower",
                    "player_id": "Follower",
                    "expression": {"formula": "(D - cF) * qFollower"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 2,
                },
            ],
            "contract_terms": [],
            "scenario_axes": [],
            "scenario_overview": [
                {"id": "baseline", "description": "Baseline", "axis_values": {}}
            ],
        },
        "procedure": {
            "method": "stackelberg_backward_induction",
            "solving_stages": [
                {
                    "stage_id": "follower_stage",
                    "description": "Solve follower best response first",
                    "corresponds_to_decision_stage": 2,
                    "solve_type": "sequential_foc",
                    "deciders": [
                        {
                            "player_id": "Follower",
                            "decision_vars": ["qFollower"],
                            "informed_about": [],
                        }
                    ],
                    "profit_function_assignments": {"Follower": ["pi_Follower"]},
                    "uses_demands": ["D"],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": "best response",
                },
                {
                    "stage_id": "leader_stage",
                    "description": "Substitute follower response into leader objective",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "sequential_foc",
                    "deciders": [
                        {
                            "player_id": "Leader",
                            "decision_vars": ["qLeader"],
                            "informed_about": [],
                        }
                    ],
                    "profit_function_assignments": {"Leader": ["pi_Leader"]},
                    "uses_demands": ["D"],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": ["follower_stage"],
                    "solver_hint": "leader optimization after substitution",
                },
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": ["D"],
                    "active_payoff_components": {
                        "Leader": ["pi_Leader"],
                        "Follower": ["pi_Follower"],
                    },
                    "active_contract_terms": [],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": None,
            "description": None,
        },
        "research_questions": [],
        "meta": {"implicit_assumptions": [], "field_confidence": [], "version": "modelspec-v1"},
    }


def _binary_entry_modelspec() -> dict:
    return {
        "basics": {
            "title": "Binary Entry Benchmark",
            "source": None,
            "game_type": "static_simultaneous",
            "unsupported_reason": None,
            "players": [
                {"id": "F1", "name": "Firm 1", "role": "symmetric"},
                {"id": "F2", "name": "Firm 2", "role": "symmetric"},
            ],
            "decision_variables": [
                {"name": "x1", "owner": "F1", "domain": "Binary"},
                {"name": "x2", "owner": "F2", "domain": "Binary"},
            ],
            "parameters": [
                {"name": "M1", "domain": "NonNegative"},
                {"name": "M2", "domain": "NonNegative"},
                {"name": "K1", "domain": "NonNegative"},
                {"name": "K2", "domain": "NonNegative"},
                {"name": "C", "domain": "NonNegative"},
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
                        "description": "Simultaneous entry",
                        "decisions": [
                            {
                                "decider": "F1",
                                "decision_vars": ["x1"],
                                "simultaneous_with": ["F2"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "entry_exit",
                            },
                            {
                                "decider": "F2",
                                "decision_vars": ["x2"],
                                "simultaneous_with": ["F1"],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "entry_exit",
                            },
                        ],
                    }
                ]
            },
            "demands": [],
            "payoff_components": [
                {
                    "id": "pi_F1",
                    "player_id": "F1",
                    "expression": {"formula": "M1 * x1 - K1 * x1 - C * x1 * x2"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
                {
                    "id": "pi_F2",
                    "player_id": "F2",
                    "expression": {"formula": "M2 * x2 - K2 * x2 - C * x1 * x2"},
                    "component_type": "profit",
                    "applies_to_decision_stage": 1,
                },
            ],
            "contract_terms": [],
            "scenario_axes": [],
            "scenario_overview": [
                {"id": "baseline", "description": "Baseline", "axis_values": {}}
            ],
        },
        "procedure": {
            "method": "static_foc",
            "solving_stages": [
                {
                    "stage_id": "entry_stage",
                    "description": "Simultaneous binary entry game",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "discrete_payoff_matrix",
                    "deciders": [
                        {"player_id": "F1", "decision_vars": ["x1"], "informed_about": []},
                        {"player_id": "F2", "decision_vars": ["x2"], "informed_about": []},
                    ],
                    "profit_function_assignments": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "uses_demands": [],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": "enumerate pure strategy profiles",
                }
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": [],
                    "active_payoff_components": {
                        "F1": ["pi_F1"],
                        "F2": ["pi_F2"],
                    },
                    "active_contract_terms": [],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": "pure_nash",
            "description": None,
        },
        "research_questions": [],
        "meta": {"implicit_assumptions": [], "field_confidence": [], "version": "modelspec-v1"},
    }


def _unsupported_modelspec() -> dict:
    return {
        "basics": {
            "title": "Unsupported Signaling Benchmark",
            "source": None,
            "game_type": "unsupported",
            "unsupported_reason": "signaling games are not yet supported in Phase 1",
            "players": [
                {"id": "Sender", "name": "Sender", "role": "principal"},
                {"id": "Receiver", "name": "Receiver", "role": "agent"},
            ],
            "decision_variables": [
                {"name": "m", "owner": "Sender", "domain": "Discrete", "custom_domain": "{0, 1}"},
                {"name": "a", "owner": "Receiver", "domain": "Discrete", "custom_domain": "{0, 1}"},
            ],
            "parameters": [],
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
                        "description": "Sender moves",
                        "decisions": [
                            {
                                "decider": "Sender",
                                "decision_vars": ["m"],
                                "simultaneous_with": [],
                                "move_order": 1,
                                "observes_before_deciding": [],
                                "decision_role": "other",
                            }
                        ],
                    },
                    {
                        "stage_number": 2,
                        "description": "Receiver moves",
                        "decisions": [
                            {
                                "decider": "Receiver",
                                "decision_vars": ["a"],
                                "simultaneous_with": [],
                                "move_order": 1,
                                "observes_before_deciding": ["m"],
                                "decision_role": "other",
                            }
                        ],
                    },
                ]
            },
            "demands": [],
            "payoff_components": [
                {
                    "id": "u_S",
                    "player_id": "Sender",
                    "expression": {"formula": "m - a"},
                    "component_type": "utility",
                    "applies_to_decision_stage": 1,
                },
                {
                    "id": "u_R",
                    "player_id": "Receiver",
                    "expression": {"formula": "a - m"},
                    "component_type": "utility",
                    "applies_to_decision_stage": 2,
                },
            ],
            "contract_terms": [],
            "scenario_axes": [],
            "scenario_overview": [
                {"id": "baseline", "description": "Baseline", "axis_values": {}}
            ],
        },
        "procedure": {
            "method": "unsupported",
            "solving_stages": [
                {
                    "stage_id": "placeholder_stage",
                    "description": "Placeholder unsupported stage",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "enumeration",
                    "deciders": [
                        {"player_id": "Sender", "decision_vars": ["m"], "informed_about": []}
                    ],
                    "profit_function_assignments": {"Sender": ["u_S"]},
                    "uses_demands": [],
                    "uses_contract_terms": [],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": [],
                    "solver_hint": "unsupported benchmark placeholder",
                }
            ],
            "scenario_details": [
                {
                    "scenario_id": "baseline",
                    "informed_overrides": {},
                    "active_demands": [],
                    "active_payoff_components": {"Sender": ["u_S"], "Receiver": ["u_R"]},
                    "active_contract_terms": [],
                    "demand_overrides": None,
                    "payoff_overrides": None,
                    "notes": None,
                }
            ],
            "refinement": None,
            "description": None,
        },
        "research_questions": [],
        "meta": {"implicit_assumptions": [], "field_confidence": [], "version": "modelspec-v1"},
    }
