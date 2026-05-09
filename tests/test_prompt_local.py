"""Local tests for the redesigned Stage 1 parser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from agent.parser import Parser
from agent.parser.output_format import (
    STAGE1_EXAMPLE,
    ClarificationQuestion,
    Stage1Output,
    Stage2Output,
    get_stage1_json_schema,
    render_compact_stage1_schema_for_prompt,
    render_compact_stage2_schema_for_prompt,
    render_schema_for_prompt,
)
from agent.parser.parser import strip_jsonc_comments
from agent.schemas import (
    ContractTerm,
    DecisionTiming,
    DecisionVariable,
    Demand,
    Expression,
    GameBasics,
    GameType,
    ModelSpec,
    PayoffComponent,
    Player,
    RandomVariable,
    ScenarioOverview,
    Stage,
    StageDecision,
    VariableDomain,
)


def test_stage1_schema_rendering():
    schema_text = render_schema_for_prompt(get_stage1_json_schema())

    assert "GameBasics" in schema_text
    assert "payoff_components" in schema_text
    assert "contract_terms" in schema_text
    assert "scenario_overview" in schema_text
    assert "field_confidence" in schema_text


def test_compact_stage1_schema_is_short_and_complete():
    guide = render_compact_stage1_schema_for_prompt()

    assert len(guide) < 7000
    assert "$defs" not in guide
    assert "payoff_components" in guide
    assert "contract_terms" in guide
    assert "field_confidence" in guide
    assert "research questions" in guide


def test_compact_stage2_schema_is_short_and_complete():
    guide = render_compact_stage2_schema_for_prompt()

    assert len(guide) < 8000
    assert "$defs" not in guide
    assert "solving_stages" in guide
    assert "scenario_details" in guide
    assert "research_questions" in guide
    assert "basics_revision_suggestions" in guide
    assert "mixed_by_scenario" in guide
    assert "Confirmed GameBasics is authoritative" in guide


def test_stage1_example_is_valid_json():
    start = STAGE1_EXAMPLE.find("```json")
    end = STAGE1_EXAMPLE.find("```", start + 7)
    example_json = STAGE1_EXAMPLE[start + 7 : end].strip()

    parsed = json.loads(example_json)
    output = Stage1Output.model_validate(parsed)
    output.assert_valid()


def test_gamebasics_cross_reference_validation():
    basics = GameBasics(
        title="Bad reference example",
        game_type=GameType.STATIC_SIMULTANEOUS,
        players=[Player(id="F1", name="Firm 1")],
        decision_variables=[
            DecisionVariable(
                name="q1",
                owner="Missing",
                domain=VariableDomain.NON_NEGATIVE,
            )
        ],
        decision_timing=DecisionTiming(
            stages=[
                Stage(
                    stage_number=1,
                    decisions=[
                        StageDecision(decider="F1", decision_vars=["q1"])
                    ],
                )
            ]
        ),
        payoff_components=[
            PayoffComponent(
                id="profit",
                player_id="F1",
                expression=Expression(formula="q1"),
            )
        ],
    )

    errors = basics.validate_cross_references()
    assert any("owner" in error for error in errors)


def test_payoff_cannot_reference_undefined_demand_name():
    basics = GameBasics(
        title="Demand reference example",
        game_type=GameType.STATIC_SIMULTANEOUS,
        players=[Player(id="F1", name="Firm 1")],
        decision_variables=[
            DecisionVariable(
                name="q1",
                owner="F1",
                domain=VariableDomain.NON_NEGATIVE,
            )
        ],
        decision_timing=DecisionTiming(
            stages=[
                Stage(
                    stage_number=1,
                    decisions=[
                        StageDecision(decider="F1", decision_vars=["q1"])
                    ],
                )
            ]
        ),
        demands=[
            Demand(
                name="D1_nb",
                expression=Expression(formula="q1"),
            )
        ],
        payoff_components=[
            PayoffComponent(
                id="profit",
                player_id="F1",
                expression=Expression(formula="p1 * D1"),
            )
        ],
    )

    errors = basics.validate_cross_references()
    assert any("unknown demand" in error for error in errors)


def test_contract_term_cannot_reference_demand_name():
    basics = GameBasics(
        title="Sales dependent transfer example",
        game_type=GameType.STATIC_SIMULTANEOUS,
        players=[Player(id="R", name="Retailer"), Player(id="M", name="Maker")],
        demands=[
            Demand(
                name="D1",
                expression=Expression(formula="a - p1"),
            )
        ],
        contract_terms=[
            ContractTerm(
                name="commission",
                payer="M",
                payee="R",
                formula="alpha * p1 * D1",
            )
        ],
    )

    errors = basics.validate_cross_references()
    assert any("sales-dependent" in error for error in errors)


def test_parameter_random_variable_names_cannot_overlap():
    basics = GameBasics(
        title="Duplicate uncertainty example",
        game_type=GameType.STATIC_SIMULTANEOUS,
        parameters=[
            {"name": "a", "domain": "Reals", "custom_domain": None, "fixed_value": None, "description": None}
        ],
        information_structure={
            "random_variables": [
                RandomVariable(name="a", realizations=[])
            ],
            "access": [],
            "action_observability": [],
        },
    )

    errors = basics.validate_cross_references()
    assert any("parameters.name and random_variables.name overlap" in error for error in errors)


def test_stage1_clarification_questions_are_limited():
    basics = GameBasics(title="Tiny", game_type=GameType.STATIC_SIMULTANEOUS)

    with pytest.raises(Exception):
        Stage1Output(
            basics=basics,
            clarification_questions=[
                ClarificationQuestion(id=f"q{i}", question="?")
                for i in range(9)
            ],
        )


def test_summary_markdown_contains_review_sections():
    output = Stage1Output(
        basics=GameBasics(
            title="Tiny game",
            game_type=GameType.STATIC_SIMULTANEOUS,
            players=[Player(id="F1", name="Firm 1")],
            decision_variables=[
                DecisionVariable(
                    name="q1",
                    owner="F1",
                    domain=VariableDomain.NON_NEGATIVE,
                )
            ],
            decision_timing=DecisionTiming(
                stages=[
                    Stage(
                        stage_number=1,
                        decisions=[
                            StageDecision(decider="F1", decision_vars=["q1"])
                        ],
                    )
                ]
            ),
            payoff_components=[
                PayoffComponent(
                    id="profit",
                    player_id="F1",
                    expression=Expression(formula="q1"),
                )
            ],
        )
    )

    summary = output.summary_markdown()
    assert "## Players" in summary
    assert "## Payoff Components" in summary
    assert "`profit`" in summary


def test_parser_stage1_text_with_fake_llm():
    fake = FakeLLM(_valid_stage1_json())
    parser = Parser(llm_client=fake, auto_save=False)

    output = parser.parse_stage1_text("A firm chooses q1 and earns q1.")

    assert output.basics.title == "Fake Stage1"
    assert output.basics.players[0].id == "F1"
    assert output.basics.payoff_components[0].id == "profit"
    assert fake.sent_prompts
    assert "$defs" not in fake.sent_prompts[0]
    assert "Stage1Output Compact Format Guide" in fake.sent_prompts[0]


def test_stage1_revise_from_feedback_with_fake_llm():
    previous = Stage1Output.model_validate_json(_valid_stage1_json())
    revised_json = _valid_stage1_json(title="Revised Stage1", role="leader")
    fake = FakeLLM(revised_json)
    parser = Parser(llm_client=fake, auto_save=False)

    revised = parser.stage1_revise_from_feedback(
        previous,
        answers={"q1": "leader"},
        free_feedback="Set F1 role to leader.",
        paper_content="A firm chooses q1.",
    )

    assert revised.basics.title == "Revised Stage1"
    assert revised.basics.players[0].role.value == "leader"
    assert "Previous Stage1Output" in fake.sent_prompts[0]
    assert "Set F1 role to leader." in fake.sent_prompts[0]


def test_stage1_review_jsonc_round_trip():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    parser = Parser(llm_client=FakeLLM(_valid_stage1_json()), auto_save=False)

    jsonc = parser.export_stage1_review_jsonc(stage1)
    assert isinstance(jsonc, str)
    assert "// game_type controls later solver routing." in jsonc

    edited = jsonc.replace('"role": "unspecified"', '"role": "leader"')
    revised = parser.stage1_revise_from_json(edited, save=False)

    assert json.loads(strip_jsonc_comments(edited))["basics"]["players"][0]["role"] == "leader"
    assert revised.basics.players[0].role.value == "leader"


def test_stage1_diff_and_confirm():
    old = Stage1Output.model_validate_json(_valid_stage1_json())
    new = Stage1Output.model_validate_json(_valid_stage1_json(role="leader"))
    parser = Parser(llm_client=FakeLLM(_valid_stage1_json()), auto_save=False)

    changes = parser.diff_stage1_outputs(old, new)
    assert any(change["path"] == "basics.players[0].role" for change in changes)
    markdown = parser.format_stage1_diff_markdown(old, new)
    assert "basics.players[0].role" in markdown

    final_path = parser.confirm_stage1(new, output_dir=Path("output/test_stage1_confirm"))
    assert final_path.name == "stage1_final.json"
    assert final_path.exists()


def test_stage2_output_cross_reference_validation():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    stage2 = Stage2Output.model_validate_json(_valid_stage2_json("missing_profit"))

    with pytest.raises(ValueError, match="unknown payoff component"):
        stage2.assert_valid(stage1.basics)


def test_parser_stage2_with_fake_llm():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    fake = FakeLLM(_valid_stage2_json())
    parser = Parser(llm_client=fake, auto_save=False)

    stage2 = parser.parse_stage2(stage1, paper_content="Solve the tiny game.")

    assert stage2.procedure.method.value == "static_foc"
    assert stage2.procedure.solving_stages[0].stage_id == "static_choice"
    assert stage2.research_questions[0].target_players == ["F1"]
    assert fake.sent_prompts
    assert "Confirmed GameBasics" in fake.sent_prompts[0]


def test_stage2_revise_from_feedback_with_fake_llm():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    previous = Stage2Output.model_validate_json(_valid_stage2_json())
    revised_data = json.loads(_valid_stage2_json())
    revised_data["procedure"]["solving_stages"][0][
        "solver_hint"
    ] = "use closed-form FOC"
    revised_json = json.dumps(revised_data)
    fake = FakeLLM(revised_json)
    parser = Parser(llm_client=fake, auto_save=False)

    revised = parser.stage2_revise_from_feedback(
        previous=previous,
        stage1=stage1,
        answers={"cq1": "Use closed-form FOC."},
        free_feedback="Make the solver hint more explicit.",
        paper_content="A firm chooses q1.",
    )

    assert revised.procedure.solving_stages[0].solver_hint == "use closed-form FOC"
    assert "Previous Stage2Output" in fake.sent_prompts[0]
    assert "Make the solver hint more explicit." in fake.sent_prompts[0]


def test_stage2_review_jsonc_round_trip():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    stage2 = Stage2Output.model_validate_json(_valid_stage2_json())
    parser = Parser(llm_client=FakeLLM(_valid_stage2_json()), auto_save=False)

    jsonc = parser.export_stage2_review_jsonc(stage2)
    assert isinstance(jsonc, str)
    assert "// Stage2Output review JSONC." in jsonc
    assert "// ordered solving steps" in jsonc

    edited = jsonc.replace(
        '"solver_hint": "single first-order condition"',
        '"solver_hint": "single closed-form first-order condition"',
    )
    revised = parser.stage2_revise_from_json(edited, stage1, save=False)

    assert (
        revised.procedure.solving_stages[0].solver_hint
        == "single closed-form first-order condition"
    )


def test_stage2_diff_and_confirm():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    old = Stage2Output.model_validate_json(_valid_stage2_json())
    data = json.loads(_valid_stage2_json())
    data["research_questions"][0]["target_metrics"] = ["profit", "q1"]
    new = Stage2Output.model_validate(data)
    parser = Parser(llm_client=FakeLLM(_valid_stage2_json()), auto_save=False)

    changes = parser.diff_stage2_outputs(old, new)
    assert any(
        change["path"] == "research_questions[0].target_metrics[1]"
        for change in changes
    )
    markdown = parser.format_stage2_diff_markdown(old, new)
    assert "research_questions[0].target_metrics[1]" in markdown

    final_path = parser.confirm_stage2(
        new,
        basics=stage1.basics,
        output_dir=Path("output/test_stage2_confirm"),
    )
    assert final_path.name == "stage2_final.json"
    assert final_path.exists()


def test_stage2_basics_revision_suggestion_boundary():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    data = json.loads(_valid_stage2_json())
    data["basics_revision_suggestions"] = [
        {
            "field_path": "basics.decision_variables.T",
            "issue": "A paper passage might imply discriminatory fees.",
            "suggested_change": "Return to Stage 1 if T1/T2 are intended.",
            "severity": "optional",
        }
    ]

    output = Stage2Output.model_validate(data)
    output.assert_valid(stage1.basics)
    assert "Stage 1 Revision Suggestions" in output.summary_markdown()

    data["basics_revision_suggestions"][0]["field_path"] = "procedure.method"
    invalid = Stage2Output.model_validate(data)
    with pytest.raises(ValueError, match="field_path must start"):
        invalid.assert_valid(stage1.basics)


def test_finalize_builds_and_saves_modelspec():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    stage2 = Stage2Output.model_validate_json(_valid_stage2_json())
    parser = Parser(llm_client=FakeLLM(_valid_stage2_json()), auto_save=False)

    spec = parser.finalize(
        stage1,
        stage2,
        output_dir=Path("output/test_phase0_finalize"),
        save=True,
    )

    assert isinstance(spec, ModelSpec)
    assert spec.basics.title == "Fake Stage1"
    assert spec.procedure.solving_stages[0].stage_id == "static_choice"
    assert spec.research_questions[0].id == "rq1"
    assert spec.meta.version == "modelspec-v1"

    yaml_path = Path("output/test_phase0_finalize/modelspec_final.yaml")
    json_path = Path("output/test_phase0_finalize/modelspec_final.json")
    assert yaml_path.exists()
    assert json_path.exists()

    loaded_yaml = yaml.safe_load(yaml_path.read_text(encoding="utf-8"))
    assert loaded_yaml["basics"]["title"] == "Fake Stage1"
    loaded_json = ModelSpec.model_validate_json(json_path.read_text(encoding="utf-8"))
    loaded_json.assert_valid()


def test_finalize_blocks_material_stage1_revision_suggestions():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    data = json.loads(_valid_stage2_json())
    data["basics_revision_suggestions"] = [
        {
            "field_path": "basics.decision_variables",
            "issue": "The confirmed variables may omit a strategic fee.",
            "suggested_change": "Go back to Stage 1 and add the fee variable.",
            "severity": "material",
        }
    ]
    stage2 = Stage2Output.model_validate(data)
    parser = Parser(llm_client=FakeLLM(_valid_stage2_json()), auto_save=False)

    with pytest.raises(ValueError, match="material/blocking"):
        parser.finalize(stage1, stage2, save=False)


def test_finalize_records_optional_stage1_revision_suggestions():
    stage1 = Stage1Output.model_validate_json(_valid_stage1_json())
    data = json.loads(_valid_stage2_json())
    data["basics_revision_suggestions"] = [
        {
            "field_path": "basics.decision_variables.T",
            "issue": "A uniform fee may be too restrictive.",
            "suggested_change": "Use T1/T2 if discriminatory fees are intended.",
            "severity": "optional",
        }
    ]
    stage2 = Stage2Output.model_validate(data)
    parser = Parser(llm_client=FakeLLM(_valid_stage2_json()), auto_save=False)

    spec = parser.finalize(stage1, stage2, save=False)
    assert any(
        "Optional Stage 1 revision suggestion left unresolved" in item
        for item in spec.meta.implicit_assumptions
    )

    with pytest.raises(ValueError, match="Stage 1 revision suggestions remain"):
        parser.finalize(
            stage1,
            stage2,
            save=False,
            allow_optional_basics_revision_suggestions=False,
        )


def test_stage2_requires_mixed_expectation_for_scenario_information():
    stage1_data = json.loads(_valid_stage1_json())
    stage1_data["basics"]["information_structure"]["random_variables"] = [
        {
            "name": "a",
            "realizations": [
                {"value": "aH", "probability": "beta", "description": None},
                {"value": "aL", "probability": "1 - beta", "description": None},
            ],
            "description": None,
        }
    ]
    stage1_data["basics"]["parameters"] = [
        {
            "name": "aH",
            "domain": "Positive",
            "custom_domain": None,
            "fixed_value": None,
            "description": None,
        },
        {
            "name": "aL",
            "domain": "Positive",
            "custom_domain": None,
            "fixed_value": None,
            "description": None,
        },
        {
            "name": "beta",
            "domain": "UnitInterval",
            "custom_domain": None,
            "fixed_value": None,
            "description": None,
        },
    ]
    stage1_data["basics"]["scenario_overview"] = [
        {"id": "S0", "description": "uninformed", "axis_values": {}},
        {"id": "S1", "description": "informed", "axis_values": {}},
    ]
    stage1 = Stage1Output.model_validate(stage1_data)

    stage2_data = json.loads(_valid_stage2_json())
    stage2_data["procedure"]["solving_stages"][0][
        "expectation_handling"
    ] = "before_foc"
    stage2_data["procedure"]["scenario_details"] = [
        {
            "scenario_id": "S0",
            "informed_overrides": {"static_choice": {"F1": []}},
            "active_demands": [],
            "active_payoff_components": {"F1": ["profit"]},
            "active_contract_terms": [],
            "demand_overrides": None,
            "payoff_overrides": None,
            "notes": None,
        },
        {
            "scenario_id": "S1",
            "informed_overrides": {"static_choice": {"F1": ["a"]}},
            "active_demands": [],
            "active_payoff_components": {"F1": ["profit"]},
            "active_contract_terms": [],
            "demand_overrides": None,
            "payoff_overrides": None,
            "notes": None,
        },
    ]

    output = Stage2Output.model_validate(stage2_data)
    with pytest.raises(ValueError, match="mixed_by_scenario"):
        output.assert_valid(stage1.basics)

    stage2_data["procedure"]["solving_stages"][0][
        "expectation_handling"
    ] = "mixed_by_scenario"
    output = Stage2Output.model_validate(stage2_data)
    output.assert_valid(stage1.basics)


def _valid_stage1_json(
    *,
    title: str = "Fake Stage1",
    role: str = "unspecified",
) -> str:
    return json.dumps(
        {
            "basics": {
                "title": title,
                "source": None,
                "game_type": "static_simultaneous",
                "unsupported_reason": None,
                "players": [
                    {
                        "id": "F1",
                        "name": "Firm 1",
                        "role": role,
                        "description": None,
                    }
                ],
                "decision_variables": [
                    {
                        "name": "q1",
                        "owner": "F1",
                        "domain": "NonNegative",
                        "custom_domain": None,
                        "description": None,
                    }
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
                            "description": None,
                            "decisions": [
                                {
                                    "decider": "F1",
                                    "decision_vars": ["q1"],
                                    "simultaneous_with": [],
                                    "description": None,
                                }
                            ],
                        }
                    ]
                },
                "demands": [],
                "payoff_components": [
                    {
                        "id": "profit",
                        "player_id": "F1",
                        "expression": {
                            "formula": "q1",
                            "description": None,
                        },
                        "component_type": "profit",
                        "applies_to_decision_stage": 1,
                        "applies_when": None,
                        "description": None,
                    }
                ],
                "contract_terms": [],
                "scenario_axes": [],
                "scenario_overview": [],
            },
            "clarification_questions": [],
            "field_confidence": [],
            "implicit_assumptions": [],
        }
    )


def _valid_stage2_json(component_id: str = "profit") -> str:
    return json.dumps(
        {
            "procedure": {
                "method": "static_foc",
                "solving_stages": [
                    {
                        "stage_id": "static_choice",
                        "description": "Firm solves its one-shot choice.",
                        "corresponds_to_decision_stage": 1,
                        "solve_type": "optimization",
                        "deciders": [
                            {
                                "player_id": "F1",
                                "decision_vars": ["q1"],
                                "informed_about": [],
                                "description": None,
                            }
                        ],
                        "profit_function_assignments": {
                            "F1": [component_id]
                        },
                        "uses_demands": [],
                        "uses_contract_terms": [],
                        "expectation_handling": "not_needed",
                        "uses_previous_stage_results": [],
                        "solver_hint": "single first-order condition",
                    }
                ],
                "scenario_details": [],
                "refinement": None,
                "description": None,
            },
            "research_questions": [
                {
                    "id": "rq1",
                    "question": "What is F1's optimal q1?",
                    "question_type": "optimal_choice",
                    "target_scenarios": [],
                    "target_players": ["F1"],
                    "target_metrics": ["profit"],
                    "description": None,
                }
            ],
            "clarification_questions": [],
            "basics_revision_suggestions": [],
            "field_confidence": [],
        }
    )


class FakeLLM:
    def __init__(self, response: str) -> None:
        self.provider_config = FakeProviderConfig()
        self.response = response
        self.sent_prompts: list[str] = []

    def new_conversation(self, system: str | None = None):
        return FakeConversation(self)


class FakeProviderConfig:
    class Capabilities:
        supports_pdf = False
        supports_image = False

    capabilities = Capabilities()


class FakeConversation:
    def __init__(self, client: FakeLLM) -> None:
        self.client = client
        self.messages: list[dict] = []

    def add_user(self, text: str) -> None:
        self.messages.append({"role": "user", "content": text})
        self.client.sent_prompts.append(text)

    def send(self, **kwargs) -> str:
        return self.client.response
