"""Stage 1 output models and prompt helpers."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import Field

from agent.schemas import (
    FieldConfidence,
    GameBasics,
    ResearchQuestion,
    SolvingProcedure,
    StrictModel,
)


class ClarificationQuestion(StrictModel):
    """A question that should be reviewed by the user before proceeding."""

    id: str = Field(..., description="Short stable id such as q1.")
    question: str
    context: str | None = None
    options: list[str] = Field(default_factory=list)


class BasicsRevisionSuggestion(StrictModel):
    """A Stage 2 note that confirmed Stage 1 facts may need revisiting."""

    field_path: str = Field(
        ...,
        description="Path under basics.*, for example basics.decision_variables.T.",
    )
    issue: str
    suggested_change: str
    severity: Literal["optional", "material", "blocking"] = Field(
        default="optional",
        description="optional, material, or blocking.",
    )


class Stage1Output(StrictModel):
    """Stage 1 result: game facts plus review metadata."""

    basics: GameBasics
    clarification_questions: list[ClarificationQuestion] = Field(
        default_factory=list,
        max_length=8,
        description=(
            "At most 8 material questions about GameBasics facts. "
            "Do not include generic assumptions unless the paper makes them risky."
        ),
    )
    field_confidence: list[FieldConfidence] = Field(default_factory=list)
    implicit_assumptions: list[str] = Field(default_factory=list)

    def assert_valid(self) -> None:
        self.basics.assert_valid()

    def summary_markdown(self) -> str:
        """Render a compact review summary for notebooks or the console."""

        basics = self.basics
        lines: list[str] = []

        lines.append(f"# {basics.title}")
        lines.append("")
        lines.append("## Game Type")
        lines.append(f"- `{basics.game_type.value}`")
        if basics.unsupported_reason:
            lines.append(f"- unsupported_reason: {basics.unsupported_reason}")

        lines.append("")
        lines.append("## Players")
        if basics.players:
            lines.extend(
                f"- `{p.id}`: {p.name}"
                + (f" ({p.role.value})" if p.role else "")
                + (f" - {p.description}" if p.description else "")
                for p in basics.players
            )
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Decision Variables")
        lines.extend(
            _table(
                ["Variable", "Owner", "Domain", "Description"],
                [
                    [
                        var.name,
                        var.owner,
                        var.domain.value,
                        var.description or "",
                    ]
                    for var in basics.decision_variables
                ],
            )
        )

        lines.append("")
        lines.append("## Parameters")
        lines.extend(
            _table(
                ["Parameter", "Domain", "Fixed", "Description"],
                [
                    [
                        param.name,
                        param.custom_domain or param.domain.value,
                        param.fixed_value or "",
                        param.description or "",
                    ]
                    for param in basics.parameters
                ],
            )
        )

        if basics.parameter_constraints:
            lines.append("")
            lines.append("## Parameter Constraints")
            lines.extend(
                f"- `{constraint.expression}`"
                + (f" - {constraint.description}" if constraint.description else "")
                for constraint in basics.parameter_constraints
            )

        lines.append("")
        lines.append("## Decision Timing")
        if basics.decision_timing.stages:
            for stage in basics.decision_timing.stages:
                lines.append(
                    f"- Stage {stage.stage_number}: {stage.description or ''}"
                )
                for decision in stage.decisions:
                    variables = ", ".join(decision.decision_vars)
                    simultaneous = ", ".join(decision.simultaneous_with)
                    observed = ", ".join(decision.observes_before_deciding)
                    details = []
                    if decision.move_order is not None:
                        details.append(f"order {decision.move_order}")
                    details.append(decision.decision_role.value)
                    if simultaneous:
                        details.append(f"simultaneous with {simultaneous}")
                    if observed:
                        details.append(f"observes {observed}")
                    tail = f" ({'; '.join(details)})" if details else ""
                    lines.append(f"  - `{decision.decider}` decides {variables}{tail}")
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Random Variables And Information")
        if basics.information_structure.random_variables:
            for rv in basics.information_structure.random_variables:
                realizations = ", ".join(
                    f"{r.value} ({r.probability})" for r in rv.realizations
                )
                lines.append(f"- `{rv.name}`: {realizations}")
        else:
            lines.append("- No random variables identified")
        for access in basics.information_structure.access:
            lines.append(
                f"- `{access.player_id}` knows {', '.join(access.knows) or 'nothing'}"
                + (f" when {access.when}" if access.when else "")
            )
        for obs in basics.information_structure.action_observability:
            lines.append(
                f"- `{obs.observer}` observes `{obs.observed_player}` "
                f"variables {', '.join(obs.observed_decision_vars)}"
                + (f" when {obs.when}" if obs.when else "")
            )

        lines.append("")
        lines.append("## Demands / State Equations")
        if basics.demands:
            for demand in basics.demands:
                lines.append(f"- `{demand.name}` = `{demand.expression.formula}`")
                if demand.applies_when:
                    lines.append(f"  - applies_when: {demand.applies_when}")
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Payoff Components")
        if basics.payoff_components:
            for component in basics.payoff_components:
                lines.append(
                    f"- `{component.id}` ({component.player_id}, "
                    f"{component.component_type.value}) = "
                    f"`{component.expression.formula}`"
                )
                if component.applies_when:
                    lines.append(f"  - applies_when: {component.applies_when}")
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Contract Terms")
        if basics.contract_terms:
            for term in basics.contract_terms:
                lines.append(
                    f"- `{term.name}`: {term.payer} -> {term.payee}, "
                    f"formula `{term.formula}`"
                )
                if term.triggered_when:
                    lines.append(f"  - triggered_when: {term.triggered_when}")
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Scenario Axes")
        if basics.scenario_axes:
            for axis in basics.scenario_axes:
                values = ", ".join(value.id for value in axis.values)
                lines.append(f"- `{axis.id}`: {values}")
        else:
            lines.append("- None identified")

        lines.append("")
        lines.append("## Scenario Overview")
        if basics.scenario_overview:
            lines.extend(
                _table(
                    ["Scenario", "Axis Values", "Description"],
                    [
                        [
                            scenario.id,
                            ", ".join(
                                f"{key}={value}"
                                for key, value in scenario.axis_values.items()
                            ),
                            scenario.description,
                        ]
                        for scenario in basics.scenario_overview
                    ],
                )
            )
        else:
            lines.append("- Single baseline scenario or not identified")

        high_risk = [
            confidence
            for confidence in self.field_confidence
            if confidence.confidence.value in {"inferred", "uncertain"}
        ]
        lines.append("")
        lines.append("## High-Risk Fields")
        if high_risk:
            for item in high_risk:
                lines.append(
                    f"- `{item.field_path}`: {item.confidence.value}"
                    + (f" - {item.note}" if item.note else "")
                )
                if item.source_quote:
                    lines.append(f"  - source: {item.source_quote}")
        else:
            lines.append("- None marked")

        lines.append("")
        lines.append("## Clarification Questions")
        if self.clarification_questions:
            for question in self.clarification_questions:
                lines.append(f"- [{question.id}] {question.question}")
                if question.context:
                    lines.append(f"  - context: {question.context}")
                if question.options:
                    lines.append(f"  - options: {', '.join(question.options)}")
        else:
            lines.append("- None")

        lines.append("")
        lines.append("## Implicit Assumptions")
        if self.implicit_assumptions:
            lines.extend(f"- {assumption}" for assumption in self.implicit_assumptions)
        else:
            lines.append("- None")

        return "\n".join(lines)


class Stage2Output(StrictModel):
    """Stage 2 result: solving procedure plus research questions."""

    procedure: SolvingProcedure
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    basics_revision_suggestions: list[BasicsRevisionSuggestion] = Field(
        default_factory=list,
        description=(
            "Stage 2 suggestions to revisit confirmed GameBasics. These are "
            "not normal Stage 2 clarification questions."
        ),
    )
    clarification_questions: list[ClarificationQuestion] = Field(
        default_factory=list,
        max_length=8,
        description="At most 8 material questions about the solving procedure.",
    )
    field_confidence: list[FieldConfidence] = Field(default_factory=list)

    def assert_valid(self, basics: GameBasics) -> None:
        self.procedure.assert_valid_against_basics(basics)
        errors: list[str] = []
        for question in self.research_questions:
            errors.extend(question.validate_against_basics(basics))
        for suggestion in self.basics_revision_suggestions:
            if not suggestion.field_path.startswith("basics."):
                errors.append(
                    "basics_revision_suggestions field_path must start with "
                    f"'basics.': {suggestion.field_path!r}"
                )
        if errors:
            raise ValueError(
                "Stage2Output validation failed:\n  - " + "\n  - ".join(errors)
            )

    def summary_markdown(self) -> str:
        """Render a compact Stage 2 review summary."""

        lines: list[str] = []
        procedure = self.procedure

        lines.append("# Stage 2 Solving Procedure")
        lines.append("")
        lines.append("## Method")
        lines.append(f"- `{procedure.method.value}`")
        if procedure.refinement:
            lines.append(f"- refinement: {procedure.refinement}")
        if procedure.description:
            lines.append(f"- {procedure.description}")

        lines.append("")
        lines.append("## Solving Stages")
        if procedure.solving_stages:
            for stage in procedure.solving_stages:
                lines.append(f"### {stage.stage_id}")
                lines.append(f"- decision_stage: {stage.corresponds_to_decision_stage}")
                lines.append(f"- solve_type: `{stage.solve_type.value}`")
                lines.append(f"- expectation: `{stage.expectation_handling.value}`")
                lines.append(f"- description: {stage.description}")
                if stage.deciders:
                    lines.append("- deciders:")
                    for decider in stage.deciders:
                        variables = ", ".join(decider.decision_vars)
                        informed = ", ".join(decider.informed_about) or "none"
                        lines.append(
                            f"  - `{decider.player_id}` decides {variables}; "
                            f"informed_about: {informed}"
                        )
                if stage.profit_function_assignments:
                    lines.append("- profit components:")
                    for player_id, components in stage.profit_function_assignments.items():
                        lines.append(f"  - `{player_id}`: {', '.join(components)}")
                if stage.uses_demands:
                    lines.append(f"- demands: {', '.join(stage.uses_demands)}")
                if stage.uses_contract_terms:
                    lines.append(
                        f"- contract_terms: {', '.join(stage.uses_contract_terms)}"
                    )
                if stage.uses_previous_stage_results:
                    lines.append(
                        "- uses_previous_stage_results: "
                        + ", ".join(stage.uses_previous_stage_results)
                    )
                if stage.solver_hint:
                    lines.append(f"- solver_hint: {stage.solver_hint}")
                lines.append("")
        else:
            lines.append("- None")

        lines.append("## Scenario Details")
        if procedure.scenario_details:
            for detail in procedure.scenario_details:
                lines.append(f"### {detail.scenario_id}")
                if detail.active_demands:
                    lines.append(f"- active_demands: {', '.join(detail.active_demands)}")
                if detail.active_payoff_components:
                    lines.append("- active_payoff_components:")
                    for player_id, components in detail.active_payoff_components.items():
                        lines.append(f"  - `{player_id}`: {', '.join(components)}")
                if detail.active_contract_terms:
                    lines.append(
                        f"- active_contract_terms: {', '.join(detail.active_contract_terms)}"
                    )
                if detail.informed_overrides:
                    lines.append("- informed_overrides:")
                    for stage_id, player_map in detail.informed_overrides.items():
                        parts = [
                            f"{player_id}: {', '.join(randoms) or 'none'}"
                            for player_id, randoms in player_map.items()
                        ]
                        lines.append(f"  - `{stage_id}`: " + "; ".join(parts))
                if detail.notes:
                    lines.append(f"- notes: {detail.notes}")
        else:
            lines.append("- None")

        lines.append("")
        lines.append("## Research Questions")
        if self.research_questions:
            for question in self.research_questions:
                lines.append(
                    f"- `{question.id}` ({question.question_type.value}): "
                    f"{question.question}"
                )
                if question.target_scenarios:
                    lines.append(
                        f"  - scenarios: {', '.join(question.target_scenarios)}"
                    )
                if question.target_players:
                    lines.append(f"  - players: {', '.join(question.target_players)}")
                if question.target_metrics:
                    lines.append(f"  - metrics: {', '.join(question.target_metrics)}")
        else:
            lines.append("- None")

        lines.append("")
        lines.append("## Stage 1 Revision Suggestions")
        if self.basics_revision_suggestions:
            for suggestion in self.basics_revision_suggestions:
                lines.append(
                    f"- `{suggestion.field_path}` ({suggestion.severity}): "
                    f"{suggestion.issue}"
                )
                lines.append(f"  - suggested_change: {suggestion.suggested_change}")
        else:
            lines.append("- None")

        high_risk = [
            confidence
            for confidence in self.field_confidence
            if confidence.confidence.value in {"inferred", "uncertain"}
        ]
        lines.append("")
        lines.append("## High-Risk Fields")
        if high_risk:
            for item in high_risk:
                lines.append(
                    f"- `{item.field_path}`: {item.confidence.value}"
                    + (f" - {item.note}" if item.note else "")
                )
                if item.source_quote:
                    lines.append(f"  - source: {item.source_quote}")
        else:
            lines.append("- None marked")

        lines.append("")
        lines.append("## Clarification Questions")
        if self.clarification_questions:
            for question in self.clarification_questions:
                lines.append(f"- [{question.id}] {question.question}")
                if question.context:
                    lines.append(f"  - context: {question.context}")
                if question.options:
                    lines.append(f"  - options: {', '.join(question.options)}")
        else:
            lines.append("- None")

        return "\n".join(lines)


def get_stage1_json_schema() -> dict:
    return Stage1Output.model_json_schema()


def get_stage2_json_schema() -> dict:
    return Stage2Output.model_json_schema()


def render_schema_for_prompt(schema: dict, max_chars: int = 60000) -> str:
    text = json.dumps(schema, indent=2, ensure_ascii=False)
    if len(text) > max_chars:
        text = text[:max_chars] + "\n... (schema truncated)"
    return text


def render_compact_stage1_schema_for_prompt() -> str:
    """Return a compact, LLM-facing Stage 1 format guide.

    The full Pydantic schema remains the source of truth for local validation.
    This compact guide is intentionally shorter and easier for the model to
    follow than the generated JSON Schema.
    """

    return """
Stage1Output JSON shape:

{
  "basics": {
    "title": str,
    "source": str | null,
    "game_type": one of [
      "bayesian_backward_induction", "static_simultaneous", "stackelberg",
      "signaling", "repeated", "evolutionary", "cooperative", "auction",
      "mechanism_design", "unsupported"
    ],
    "unsupported_reason": str | null,

    "players": [
      {"id": str, "name": str, "role": one of [
        "leader", "follower", "principal", "agent", "symmetric",
        "unspecified"
      ], "description": str | null}
    ],

    "decision_variables": [
      {"name": str, "owner": player_id, "domain": one of [
        "Reals", "Positive", "NonNegative", "UnitInterval", "Binary",
        "Discrete", "Custom"
      ], "custom_domain": str | null, "description": str | null}
    ],

    "parameters": [
      {"name": str, "domain": same domain enum as above,
       "custom_domain": str | null, "fixed_value": str | null,
       "description": str | null}
    ],
    "parameter_constraints": [
      {"expression": str, "description": str | null, "source": str | null}
    ],

    "information_structure": {
      "random_variables": [
        {"name": str, "realizations": [
          {"value": str, "probability": str, "description": str | null}
        ], "description": str | null}
      ],
      "access": [
        {"player_id": player_id, "knows": [random_variable_name],
         "when": str | null, "decision_stage": int | null,
         "description": str | null}
      ],
      "action_observability": [
        {"observer": player_id, "observed_player": player_id,
         "observed_decision_vars": [decision_variable_name],
         "when": str | null, "description": str | null}
      ]
    },

    "decision_timing": {
      "stages": [
        {"stage_number": int, "description": str | null, "decisions": [
          {"decider": player_id, "decision_vars": [decision_variable_name],
           "simultaneous_with": [player_id],
           "move_order": int | null,
           "observes_before_deciding": [decision_variable_name],
           "decision_role": one of [
             "ordinary_action", "mechanism_design", "participation", "pricing",
             "quantity", "entry_exit", "information_disclosure", "other"
           ],
           "description": str | null}
        ]}
      ]
    },

    "demands": [
      {"name": str, "expression": {"formula": str, "description": str | null},
       "applies_when": str | null, "description": str | null}
    ],

    "payoff_components": [
      {"id": str, "player_id": player_id,
       "expression": {"formula": str, "description": str | null},
       "component_type": one of [
        "revenue", "cost", "commission", "transfer", "utility", "profit",
        "other"
       ],
       "applies_to_decision_stage": int | null,
       "applies_when": str | null, "description": str | null}
    ],

    "contract_terms": [
      {"name": str, "payer": player_id, "payee": player_id, "formula": str,
       "triggered_when": str | null, "applies_to_decision_stage": int | null,
       "description": str | null}
    ],

    "scenario_axes": [
      {"id": str, "description": str | null,
       "values": [{"id": str, "description": str | null}]}
    ],
    "scenario_overview": [
      {"id": str, "description": str, "axis_values": {axis_id: axis_value_id}}
    ]
  },

  "clarification_questions": [
    {"id": str, "question": str, "context": str | null, "options": [str]}
  ],  // 0 to 8 questions only
  "field_confidence": [
    {"field_path": str, "confidence": one of [
      "explicit", "inferred", "uncertain"
    ], "source_quote": str | null, "note": str | null}
  ],
  "implicit_assumptions": [str]
}

Rules:
- Include every top-level field shown above.
- Use [] when a list has no entries and null when an optional scalar is unknown.
- Encode within-stage order in decision_timing.decisions using move_order.
  Same move_order means same submove; use observes_before_deciding for observed
  prior variables; use decision_role to mark mechanism_design, participation,
  pricing, quantity, entry_exit, or information_disclosure decisions.
- If a leader first chooses a fee/mechanism and followers observe it before
  subscribe/accept/reject choices, this must be explicit in move_order,
  observes_before_deciding, and decision_role.
- Decision variable, parameter, and random variable names must not overlap. If
  a symbol is uncertain with realizations/probabilities, put it in
  random_variables only; list its realization symbols as parameters if needed.
- All references must be consistent: owners/deciders/payers/payees must be
  player ids; decision_vars must be defined decision variable names; known
  random variables must be defined random variable names.
- PayoffComponent formulas must reference demand/equation names exactly as
  defined in demands. For example, if demands define D1_nb and D1_sb, do not
  write a payoff formula with undefined D1.
- Put fixed fees, information fees, license fees, subsidies, and penalties in
  contract_terms, not in pricing-stage payoff_components.
- Put sales-dependent commissions, revenue shares, per-unit royalties, or other
  payments that affect pricing/quantity objectives in payoff_components, not in
  contract_terms. Contract terms should normally not reference demands, prices,
  quantities, or realized sales.
- clarification_questions must contain at most 8 questions. Ask only questions
  that materially change players, variables, timing, information, equations,
  payoff components, contract terms, or scenario overview.
- Do not include solving procedures or research questions in Stage 1.
""".strip()


def render_compact_stage2_schema_for_prompt() -> str:
    """Return a compact, LLM-facing Stage 2 format guide."""

    return """
Stage2Output JSON shape:

{
  "procedure": {
    "method": one of [
      "backward_induction", "static_foc",
      "stackelberg_backward_induction", "unsupported"
    ],
    "solving_stages": [
      {
        "stage_id": str,
        "description": str,
        "corresponds_to_decision_stage": int,
        "solve_type": one of [
          "simultaneous_foc", "sequential_foc",
          "discrete_payoff_matrix", "optimization", "enumeration"
        ],
        "deciders": [
          {"player_id": player_id, "decision_vars": [decision_variable_name],
           "informed_about": [random_variable_name],
           "description": str | null}
        ],
        "profit_function_assignments": {player_id: [payoff_component_id]},
        "uses_demands": [demand_name],
        "uses_contract_terms": [contract_term_name],
        "expectation_handling": one of [
          "not_needed", "before_foc", "per_realization", "mixed_by_scenario"
        ],
        "uses_previous_stage_results": [str],
        "solver_hint": str | null
      }
    ],
    "scenario_details": [
      {
        "scenario_id": scenario_id,
        "informed_overrides": {
          solving_stage_id: {player_id: [random_variable_name]}
        },
        "active_demands": [demand_name],
        "active_payoff_components": {player_id: [payoff_component_id]},
        "active_contract_terms": [contract_term_name],
        "demand_overrides": {demand_name: formula} | null,
        "payoff_overrides": {player_id: [payoff_component_id]} | null,
        "notes": str | null
      }
    ],
    "refinement": str | null,
    "description": str | null
  },
  "research_questions": [
    {
      "id": str,
      "question": str,
      "question_type": one of [
        "optimal_choice", "comparative_statics", "profit_comparison",
        "welfare_comparison", "mechanism_insight", "other"
      ],
      "target_scenarios": [scenario_id],
      "target_players": [player_id],
      "target_metrics": [str],
      "description": str | null
    }
  ],
  "basics_revision_suggestions": [
    {
      "field_path": "basics." + str,
      "issue": str,
      "suggested_change": str,
      "severity": "optional" | "material" | "blocking"
    }
  ],
  "clarification_questions": [
    {"id": str, "question": str, "context": str | null, "options": [str]}
  ],
  "field_confidence": [
    {"field_path": str, "confidence": one of [
      "explicit", "inferred", "uncertain"
    ], "source_quote": str | null, "note": str | null}
  ]
}

Rules:
- Output all top-level fields shown above.
- Confirmed GameBasics is authoritative. Do not rename or modify Stage 1 facts.
- All references must point to ids/names in confirmed GameBasics.
- scenario_details must cover every scenario in GameBasics.scenario_overview.
- For bayesian_backward_induction, method must be backward_induction or
  stackelberg_backward_induction.
- solving_stages should be in actual solving order. For backward induction,
  later decision stages usually appear first.
- Use GameBasics decision_timing move_order, observes_before_deciding, and
  decision_role. A mechanism_design decision such as a leader fee should be a
  leader optimization stage that induces later participation decisions.
- contract_terms are used in contract/subscription stages, not pricing FOC.
- If random variables exist, expectation_handling must say how uncertainty is
  handled.
- If a solving stage's informed players differ across scenario_details, set
  expectation_handling to "mixed_by_scenario"; the per-scenario
  informed_overrides then decide before_foc vs per_realization for each player.
- Do not mix binary/discrete subscription decisions with a continuous fee
  optimization in one SolvingStage. Split them into separate stages with the
  same corresponds_to_decision_stage when needed.
- Do not include empty lists in profit_function_assignments.
- Use paper markdown only as auxiliary evidence for solving details and
  research questions. If paper text conflicts with GameBasics, preserve
  GameBasics and add a basics_revision_suggestions item instead of asking a
  normal Stage 2 clarification question.
- clarification_questions are only for Stage 2 procedure/research issues. Do
  not ask whether confirmed GameBasics facts should be renamed, added, or
  changed there.
""".strip()


STAGE1_EXAMPLE = """
Example output for a simple Cournot model:

```json
{
  "basics": {
    "title": "Cournot Duopoly",
    "source": null,
    "game_type": "static_simultaneous",
    "unsupported_reason": null,
    "players": [
      {"id": "F1", "name": "Firm 1", "role": "symmetric", "description": null},
      {"id": "F2", "name": "Firm 2", "role": "symmetric", "description": null}
    ],
    "decision_variables": [
      {"name": "q1", "owner": "F1", "domain": "NonNegative", "custom_domain": null, "description": "Firm 1 quantity"},
      {"name": "q2", "owner": "F2", "domain": "NonNegative", "custom_domain": null, "description": "Firm 2 quantity"}
    ],
    "parameters": [
      {"name": "a", "domain": "Positive", "custom_domain": null, "fixed_value": null, "description": "Market size"},
      {"name": "c1", "domain": "Positive", "custom_domain": null, "fixed_value": null, "description": "Firm 1 marginal cost"},
      {"name": "c2", "domain": "Positive", "custom_domain": null, "fixed_value": null, "description": "Firm 2 marginal cost"}
    ],
    "parameter_constraints": [
      {"expression": "a > c1 && a > c2", "description": "Interior solution condition", "source": "standard assumption"}
    ],
    "information_structure": {
      "random_variables": [],
      "access": [],
      "action_observability": []
    },
    "decision_timing": {
      "stages": [
        {
          "stage_number": 1,
          "description": "Firms simultaneously choose quantities",
          "decisions": [
            {"decider": "F1", "decision_vars": ["q1"], "simultaneous_with": ["F2"], "move_order": 1, "observes_before_deciding": [], "decision_role": "quantity", "description": null},
            {"decider": "F2", "decision_vars": ["q2"], "simultaneous_with": ["F1"], "move_order": 1, "observes_before_deciding": [], "decision_role": "quantity", "description": null}
          ]
        }
      ]
    },
    "demands": [
      {"name": "P", "expression": {"formula": "a - q1 - q2", "description": "Inverse demand"}, "applies_when": null, "description": null}
    ],
    "payoff_components": [
      {"id": "F1_profit", "player_id": "F1", "expression": {"formula": "(P - c1) * q1", "description": null}, "component_type": "profit", "applies_to_decision_stage": 1, "applies_when": null, "description": "Firm 1 profit"},
      {"id": "F2_profit", "player_id": "F2", "expression": {"formula": "(P - c2) * q2", "description": null}, "component_type": "profit", "applies_to_decision_stage": 1, "applies_when": null, "description": "Firm 2 profit"}
    ],
    "contract_terms": [],
    "scenario_axes": [],
    "scenario_overview": []
  },
  "clarification_questions": [],
  "field_confidence": [
    {"field_path": "basics.parameter_constraints.0", "confidence": "inferred", "source_quote": null, "note": "Interior condition not explicitly stated in the short description."}
  ],
  "implicit_assumptions": [
    "Players maximize own profit.",
    "Interior first-order conditions characterize the equilibrium."
  ]
}
```
"""


def _table(headers: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["- None identified"]
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        safe_row = [str(cell).replace("\n", " ") for cell in row]
        lines.append("| " + " | ".join(safe_row) + " |")
    return lines
