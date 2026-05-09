"""Core schemas for the redesigned game-theory agent.

Stage 1 produces ``GameBasics``: the facts needed to describe a game.
It deliberately does not contain a solving program or research questions.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    """Base model that rejects undeclared LLM fields."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class Expression(StrictModel):
    """A Mathematica-friendly mathematical expression."""

    formula: str = Field(
        ...,
        description=(
            "Mathematica syntax. Use ASCII names, explicit '*', '/', and '^'. "
            "Do not use LaTeX commands or Unicode Greek letters."
        ),
    )
    description: str | None = None

    @field_validator("formula")
    @classmethod
    def formula_not_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("formula cannot be empty")
        return value


class GameType(str, Enum):
    """High-level game class used later for solver routing."""

    BAYESIAN_BACKWARD_INDUCTION = "bayesian_backward_induction"
    STATIC_SIMULTANEOUS = "static_simultaneous"
    STACKELBERG = "stackelberg"
    SIGNALING = "signaling"
    REPEATED = "repeated"
    EVOLUTIONARY = "evolutionary"
    COOPERATIVE = "cooperative"
    AUCTION = "auction"
    MECHANISM_DESIGN = "mechanism_design"
    UNSUPPORTED = "unsupported"


class PlayerRole(str, Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    PRINCIPAL = "principal"
    AGENT = "agent"
    SYMMETRIC = "symmetric"
    UNSPECIFIED = "unspecified"


class Player(StrictModel):
    id: str = Field(..., description="Stable player id, for example R, M1, F1.")
    name: str
    role: PlayerRole = PlayerRole.UNSPECIFIED
    description: str | None = None


class VariableDomain(str, Enum):
    REALS = "Reals"
    POSITIVE = "Positive"
    NON_NEGATIVE = "NonNegative"
    UNIT_INTERVAL = "UnitInterval"
    BINARY = "Binary"
    DISCRETE = "Discrete"
    CUSTOM = "Custom"


class DecisionRole(str, Enum):
    ORDINARY_ACTION = "ordinary_action"
    MECHANISM_DESIGN = "mechanism_design"
    PARTICIPATION = "participation"
    PRICING = "pricing"
    QUANTITY = "quantity"
    ENTRY_EXIT = "entry_exit"
    INFORMATION_DISCLOSURE = "information_disclosure"
    OTHER = "other"


class DecisionVariable(StrictModel):
    name: str = Field(..., description="Mathematica-friendly variable name.")
    owner: str = Field(..., description="Player id that controls this variable.")
    domain: VariableDomain = VariableDomain.REALS
    custom_domain: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_is_identifier(cls, value: str) -> str:
        if not _is_symbol_name(value):
            raise ValueError(
                f"invalid variable name {value!r}; use ASCII letters, digits, "
                "or underscores, starting with a letter"
            )
        return value


class Parameter(StrictModel):
    name: str
    domain: VariableDomain = VariableDomain.REALS
    custom_domain: str | None = None
    fixed_value: str | None = None
    description: str | None = None

    @field_validator("name")
    @classmethod
    def name_is_identifier(cls, value: str) -> str:
        if not _is_symbol_name(value):
            raise ValueError(
                f"invalid parameter name {value!r}; use ASCII letters, digits, "
                "or underscores, starting with a letter"
            )
        return value


class ParameterConstraint(StrictModel):
    expression: str = Field(
        ...,
        description="Mathematica-style condition, for example aH > aL > 0.",
    )
    description: str | None = None
    source: str | None = Field(
        None,
        description="Short source cue such as 'explicit in assumptions section'.",
    )


class Realization(StrictModel):
    value: str
    probability: str
    description: str | None = None


class RandomVariable(StrictModel):
    name: str
    realizations: list[Realization] = Field(default_factory=list)
    description: str | None = None


class InformationAccess(StrictModel):
    player_id: str
    knows: list[str] = Field(
        default_factory=list,
        description="Random-variable names whose realization this player knows.",
    )
    when: str | None = None
    decision_stage: int | None = Field(
        None,
        description="Decision stage number if the timing is stage-specific.",
    )
    description: str | None = None


class ActionObservability(StrictModel):
    observer: str
    observed_player: str
    observed_decision_vars: list[str] = Field(default_factory=list)
    when: str | None = None
    description: str | None = None


class InformationStructure(StrictModel):
    random_variables: list[RandomVariable] = Field(default_factory=list)
    access: list[InformationAccess] = Field(default_factory=list)
    action_observability: list[ActionObservability] = Field(default_factory=list)


class StageDecision(StrictModel):
    decider: str
    decision_vars: list[str] = Field(default_factory=list)
    simultaneous_with: list[str] = Field(default_factory=list)
    move_order: int | None = Field(
        None,
        ge=1,
        description=(
            "Within-stage order. Same value means simultaneous submove; smaller "
            "value moves earlier."
        ),
    )
    observes_before_deciding: list[str] = Field(
        default_factory=list,
        description="Decision variable names observed before this decision.",
    )
    decision_role: DecisionRole = DecisionRole.ORDINARY_ACTION
    description: str | None = None


class Stage(StrictModel):
    stage_number: int = Field(..., ge=1)
    description: str | None = None
    decisions: list[StageDecision] = Field(default_factory=list)


class DecisionTiming(StrictModel):
    stages: list[Stage] = Field(default_factory=list)


class Demand(StrictModel):
    """Demand function, state equation, law of motion, or auxiliary equation."""

    name: str
    expression: Expression
    applies_when: str | None = None
    description: str | None = None


class PayoffComponentType(str, Enum):
    REVENUE = "revenue"
    COST = "cost"
    COMMISSION = "commission"
    TRANSFER = "transfer"
    UTILITY = "utility"
    PROFIT = "profit"
    OTHER = "other"


class PayoffComponent(StrictModel):
    """Atomic payoff term that Stage 2 can combine into full payoffs."""

    id: str = Field(..., description="Unique component id, e.g. reselling_margin.")
    player_id: str
    expression: Expression
    component_type: PayoffComponentType = PayoffComponentType.OTHER
    applies_to_decision_stage: int | None = None
    applies_when: str | None = None
    description: str | None = None


class ContractTerm(StrictModel):
    """Contract-level term that is not part of a pricing-stage FOC."""

    name: str
    payer: str
    payee: str
    formula: str
    triggered_when: str | None = None
    applies_to_decision_stage: int | None = None
    description: str | None = None


class ScenarioAxisValue(StrictModel):
    id: str
    description: str | None = None


class ScenarioAxis(StrictModel):
    id: str
    description: str | None = None
    values: list[ScenarioAxisValue] = Field(default_factory=list)


class ScenarioOverview(StrictModel):
    id: str
    description: str
    axis_values: dict[str, str] = Field(
        default_factory=dict,
        description="Map from scenario_axis id to scenario_axis value id.",
    )


class GameBasics(StrictModel):
    """Stage 1 output: game facts only, no solving procedure."""

    title: str
    source: str | None = None
    game_type: GameType
    unsupported_reason: str | None = None

    players: list[Player] = Field(default_factory=list)
    decision_variables: list[DecisionVariable] = Field(default_factory=list)
    parameters: list[Parameter] = Field(default_factory=list)
    parameter_constraints: list[ParameterConstraint] = Field(default_factory=list)

    information_structure: InformationStructure = Field(
        default_factory=InformationStructure
    )
    decision_timing: DecisionTiming = Field(default_factory=DecisionTiming)

    demands: list[Demand] = Field(default_factory=list)
    payoff_components: list[PayoffComponent] = Field(default_factory=list)
    contract_terms: list[ContractTerm] = Field(default_factory=list)

    scenario_axes: list[ScenarioAxis] = Field(default_factory=list)
    scenario_overview: list[ScenarioOverview] = Field(default_factory=list)

    def validate_cross_references(self) -> list[str]:
        errors: list[str] = []

        player_ids = [player.id for player in self.players]
        player_id_set = set(player_ids)
        decision_names = [var.name for var in self.decision_variables]
        decision_name_set = set(decision_names)
        parameter_names = [param.name for param in self.parameters]
        random_names = [
            rv.name for rv in self.information_structure.random_variables
        ]
        random_name_set = set(random_names)
        payoff_ids = [component.id for component in self.payoff_components]
        demand_names = [demand.name for demand in self.demands]
        demand_name_set = set(demand_names)
        axis_ids = [axis.id for axis in self.scenario_axes]
        axis_value_map = {
            axis.id: {value.id for value in axis.values}
            for axis in self.scenario_axes
        }
        scenario_ids = [scenario.id for scenario in self.scenario_overview]

        _check_unique(errors, "players.id", player_ids)
        _check_unique(errors, "decision_variables.name", decision_names)
        _check_unique(errors, "parameters.name", parameter_names)
        _check_unique(errors, "random_variables.name", random_names)
        _check_unique(errors, "payoff_components.id", payoff_ids)
        _check_unique(errors, "demands.name", demand_names)
        _check_unique(errors, "scenario_axes.id", axis_ids)
        _check_unique(errors, "scenario_overview.id", scenario_ids)
        _check_disjoint(
            errors,
            "decision_variables.name",
            decision_name_set,
            "parameters.name",
            set(parameter_names),
        )
        _check_disjoint(
            errors,
            "decision_variables.name",
            decision_name_set,
            "random_variables.name",
            random_name_set,
        )
        _check_disjoint(
            errors,
            "parameters.name",
            set(parameter_names),
            "random_variables.name",
            random_name_set,
        )

        if self.game_type == GameType.UNSUPPORTED and not self.unsupported_reason:
            errors.append("unsupported games must include unsupported_reason")

        for var in self.decision_variables:
            if var.owner not in player_id_set:
                errors.append(
                    f"decision variable {var.name!r} owner {var.owner!r} "
                    "is not defined in players"
                )

        for access in self.information_structure.access:
            if access.player_id not in player_id_set:
                errors.append(
                    f"information access player {access.player_id!r} "
                    "is not defined in players"
                )
            for known in access.knows:
                if known not in random_name_set:
                    errors.append(
                        f"information access references unknown random variable "
                        f"{known!r}"
                    )

        for obs in self.information_structure.action_observability:
            if obs.observer not in player_id_set:
                errors.append(
                    f"action observer {obs.observer!r} is not defined in players"
                )
            if obs.observed_player not in player_id_set:
                errors.append(
                    f"observed player {obs.observed_player!r} "
                    "is not defined in players"
                )
            for var_name in obs.observed_decision_vars:
                if var_name not in decision_name_set:
                    errors.append(
                        f"action observability references unknown decision "
                        f"variable {var_name!r}"
                    )

        for stage in self.decision_timing.stages:
            stage_decider_map = {
                decision.decider: decision for decision in stage.decisions
            }
            for decision in stage.decisions:
                if not decision.decision_vars:
                    errors.append(
                        f"stage {stage.stage_number} decision by "
                        f"{decision.decider!r} has no decision_vars"
                    )
                if decision.decider not in player_id_set:
                    errors.append(
                        f"stage {stage.stage_number} decider "
                        f"{decision.decider!r} is not defined in players"
                    )
                for var_name in decision.decision_vars:
                    if var_name not in decision_name_set:
                        errors.append(
                            f"stage {stage.stage_number} references unknown "
                            f"decision variable {var_name!r}"
                        )
                for partner in decision.simultaneous_with:
                    if partner not in player_id_set:
                        errors.append(
                            f"stage {stage.stage_number} simultaneous_with "
                            f"{partner!r} is not defined in players"
                        )
                    partner_decision = stage_decider_map.get(partner)
                    if (
                        partner_decision is not None
                        and decision.move_order is not None
                        and partner_decision.move_order is not None
                        and decision.move_order != partner_decision.move_order
                    ):
                        errors.append(
                            f"stage {stage.stage_number} marks "
                            f"{decision.decider!r} simultaneous_with {partner!r} "
                            "but their move_order values differ"
                        )
                for var_name in decision.observes_before_deciding:
                    if var_name not in decision_name_set:
                        errors.append(
                            f"stage {stage.stage_number} decision by "
                            f"{decision.decider!r} observes unknown decision "
                            f"variable {var_name!r}"
                        )

        for component in self.payoff_components:
            if component.player_id not in player_id_set:
                errors.append(
                    f"payoff component {component.id!r} player "
                    f"{component.player_id!r} is not defined in players"
                )
            if demand_name_set:
                for token in _symbol_tokens(component.expression.formula):
                    if token.startswith("D") and token not in demand_name_set:
                        errors.append(
                            f"payoff component {component.id!r} references "
                            f"unknown demand/equation name {token!r}"
                        )

        for term in self.contract_terms:
            if term.payer not in player_id_set:
                errors.append(
                    f"contract term {term.name!r} payer {term.payer!r} "
                    "is not defined in players"
                )
            if term.payee not in player_id_set:
                errors.append(
                    f"contract term {term.name!r} payee {term.payee!r} "
                    "is not defined in players"
                )
            if demand_name_set:
                for token in _symbol_tokens(term.formula):
                    if token in demand_name_set:
                        errors.append(
                            f"contract term {term.name!r} references "
                            f"demand/equation name {token!r}; sales-dependent "
                            "terms that affect pricing-stage objectives belong "
                            "in payoff_components"
                        )
                    elif token.startswith("D"):
                        errors.append(
                            f"contract term {term.name!r} references unknown "
                            f"demand/equation name {token!r}"
                        )

        for scenario in self.scenario_overview:
            for axis_id, value_id in scenario.axis_values.items():
                if axis_id not in axis_value_map:
                    errors.append(
                        f"scenario {scenario.id!r} references unknown axis "
                        f"{axis_id!r}"
                    )
                elif value_id not in axis_value_map[axis_id]:
                    errors.append(
                        f"scenario {scenario.id!r} references unknown value "
                        f"{value_id!r} for axis {axis_id!r}"
                    )

        return errors

    def assert_valid(self) -> None:
        errors = self.validate_cross_references()
        if errors:
            raise ValueError(
                "GameBasics cross-reference validation failed:\n  - "
                + "\n  - ".join(errors)
            )


class ConfidenceLevel(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNCERTAIN = "uncertain"


class FieldConfidence(StrictModel):
    field_path: str
    confidence: ConfidenceLevel
    source_quote: str | None = None
    note: str | None = None


class ModelMeta(StrictModel):
    implicit_assumptions: list[str] = Field(default_factory=list)
    field_confidence: list[FieldConfidence] = Field(default_factory=list)
    version: str = "modelspec-v1"


class SolvingMethod(str, Enum):
    BACKWARD_INDUCTION = "backward_induction"
    STATIC_FOC = "static_foc"
    STACKELBERG_BACKWARD_INDUCTION = "stackelberg_backward_induction"
    UNSUPPORTED = "unsupported"


class StageSolveType(str, Enum):
    SIMULTANEOUS_FOC = "simultaneous_foc"
    SEQUENTIAL_FOC = "sequential_foc"
    DISCRETE_PAYOFF_MATRIX = "discrete_payoff_matrix"
    OPTIMIZATION = "optimization"
    ENUMERATION = "enumeration"


class ExpectationHandling(str, Enum):
    NOT_NEEDED = "not_needed"
    BEFORE_FOC = "before_foc"
    PER_REALIZATION = "per_realization"
    MIXED_BY_SCENARIO = "mixed_by_scenario"


class StageDecider(StrictModel):
    player_id: str
    decision_vars: list[str] = Field(default_factory=list)
    informed_about: list[str] = Field(default_factory=list)
    description: str | None = None


class SolvingStage(StrictModel):
    """A structured solving step, usually in backward-induction order."""

    stage_id: str
    description: str
    corresponds_to_decision_stage: int
    solve_type: StageSolveType
    deciders: list[StageDecider] = Field(default_factory=list)
    profit_function_assignments: dict[str, list[str]] = Field(default_factory=dict)
    uses_demands: list[str] = Field(default_factory=list)
    uses_contract_terms: list[str] = Field(default_factory=list)
    expectation_handling: ExpectationHandling = ExpectationHandling.NOT_NEEDED
    uses_previous_stage_results: list[str] = Field(default_factory=list)
    solver_hint: str | None = None


class ScenarioDetail(StrictModel):
    """Scenario-specific solving details for Stage 2."""

    scenario_id: str
    informed_overrides: dict[str, dict[str, list[str]]] = Field(
        default_factory=dict,
        description="stage_id -> player_id -> random variable names known there",
    )
    active_demands: list[str] = Field(default_factory=list)
    active_payoff_components: dict[str, list[str]] = Field(default_factory=dict)
    active_contract_terms: list[str] = Field(default_factory=list)
    demand_overrides: dict[str, str] | None = None
    payoff_overrides: dict[str, list[str]] | None = None
    notes: str | None = None


class SolvingProcedure(StrictModel):
    method: SolvingMethod
    solving_stages: list[SolvingStage] = Field(default_factory=list)
    scenario_details: list[ScenarioDetail] = Field(default_factory=list)
    refinement: str | None = None
    description: str | None = None

    def validate_against_basics(self, basics: GameBasics) -> list[str]:
        errors: list[str] = []

        player_ids = {player.id for player in basics.players}
        decision_names = {var.name for var in basics.decision_variables}
        decision_domain_map = {
            var.name: var.domain for var in basics.decision_variables
        }
        random_names = {
            rv.name for rv in basics.information_structure.random_variables
        }
        payoff_ids = {component.id for component in basics.payoff_components}
        demand_names = {demand.name for demand in basics.demands}
        contract_names = {term.name for term in basics.contract_terms}
        decision_stage_numbers = {
            stage.stage_number for stage in basics.decision_timing.stages
        }
        scenario_ids = [scenario.id for scenario in basics.scenario_overview]
        scenario_id_set = set(scenario_ids)
        solving_stage_ids = [stage.stage_id for stage in self.solving_stages]
        solving_stage_id_set = set(solving_stage_ids)

        _check_unique(errors, "solving_stages.stage_id", solving_stage_ids)
        _check_unique(
            errors,
            "scenario_details.scenario_id",
            [detail.scenario_id for detail in self.scenario_details],
        )

        if basics.game_type == GameType.BAYESIAN_BACKWARD_INDUCTION:
            allowed = {
                SolvingMethod.BACKWARD_INDUCTION,
                SolvingMethod.STACKELBERG_BACKWARD_INDUCTION,
            }
            if self.method not in allowed:
                errors.append(
                    "bayesian_backward_induction games require a backward "
                    "induction solving method"
                )

        if not self.solving_stages:
            errors.append("procedure.solving_stages cannot be empty")

        for stage in self.solving_stages:
            if stage.corresponds_to_decision_stage not in decision_stage_numbers:
                errors.append(
                    f"solving stage {stage.stage_id!r} corresponds to unknown "
                    f"decision stage {stage.corresponds_to_decision_stage!r}"
                )
            if not stage.deciders:
                errors.append(f"solving stage {stage.stage_id!r} has no deciders")
            for decider in stage.deciders:
                if decider.player_id not in player_ids:
                    errors.append(
                        f"solving stage {stage.stage_id!r} decider "
                        f"{decider.player_id!r} is not defined in players"
                    )
                if not decider.decision_vars:
                    errors.append(
                        f"solving stage {stage.stage_id!r} decider "
                        f"{decider.player_id!r} has no decision_vars"
                    )
                for var_name in decider.decision_vars:
                    if var_name not in decision_names:
                        errors.append(
                            f"solving stage {stage.stage_id!r} references "
                            f"unknown decision variable {var_name!r}"
                        )
                for random_name in decider.informed_about:
                    if random_name not in random_names:
                        errors.append(
                            f"solving stage {stage.stage_id!r} decider "
                            f"{decider.player_id!r} references unknown random "
                            f"variable {random_name!r}"
                        )

            for player_id, components in stage.profit_function_assignments.items():
                if player_id not in player_ids:
                    errors.append(
                        f"solving stage {stage.stage_id!r} assigns profits to "
                        f"unknown player {player_id!r}"
                    )
                if not components:
                    errors.append(
                        f"solving stage {stage.stage_id!r} has an empty "
                        f"profit_function_assignments list for {player_id!r}; "
                        "omit the player or list concrete payoff components"
                    )
                for component_id in components:
                    if component_id not in payoff_ids:
                        errors.append(
                            f"solving stage {stage.stage_id!r} references "
                            f"unknown payoff component {component_id!r}"
                        )
            for demand_name in stage.uses_demands:
                if demand_name not in demand_names:
                    errors.append(
                        f"solving stage {stage.stage_id!r} references unknown "
                        f"demand/equation {demand_name!r}"
                    )
            for term_name in stage.uses_contract_terms:
                if term_name not in contract_names:
                    errors.append(
                        f"solving stage {stage.stage_id!r} references unknown "
                        f"contract term {term_name!r}"
                    )
            stage_decision_vars = [
                var_name
                for decider in stage.deciders
                for var_name in decider.decision_vars
                if var_name in decision_domain_map
            ]
            has_discrete_var = any(
                decision_domain_map[var_name]
                in {VariableDomain.BINARY, VariableDomain.DISCRETE}
                for var_name in stage_decision_vars
            )
            has_continuous_var = any(
                decision_domain_map[var_name]
                not in {VariableDomain.BINARY, VariableDomain.DISCRETE}
                for var_name in stage_decision_vars
            )
            if has_discrete_var and stage.solve_type not in {
                StageSolveType.DISCRETE_PAYOFF_MATRIX,
                StageSolveType.ENUMERATION,
            }:
                errors.append(
                    f"solving stage {stage.stage_id!r} includes discrete "
                    "decision variables and must use discrete_payoff_matrix or "
                    "enumeration"
                )
            if has_discrete_var and has_continuous_var:
                errors.append(
                    f"solving stage {stage.stage_id!r} mixes discrete and "
                    "continuous decisions; split it into separate solving "
                    "stages with the same decision stage if needed"
                )

        if scenario_id_set:
            detail_ids = {detail.scenario_id for detail in self.scenario_details}
            missing = scenario_id_set - detail_ids
            extra = detail_ids - scenario_id_set
            if missing:
                errors.append(
                    "scenario_details missing scenarios: "
                    + ", ".join(sorted(missing))
                )
            if extra:
                errors.append(
                    "scenario_details references unknown scenarios: "
                    + ", ".join(sorted(extra))
                )

        for detail in self.scenario_details:
            if detail.scenario_id not in scenario_id_set and scenario_id_set:
                continue
            for stage_id, player_map in detail.informed_overrides.items():
                if stage_id not in solving_stage_id_set:
                    errors.append(
                        f"scenario {detail.scenario_id!r} references unknown "
                        f"solving stage {stage_id!r} in informed_overrides"
                    )
                for player_id, random_list in player_map.items():
                    if player_id not in player_ids:
                        errors.append(
                            f"scenario {detail.scenario_id!r} references "
                            f"unknown player {player_id!r} in informed_overrides"
                        )
                    for random_name in random_list:
                        if random_name not in random_names:
                            errors.append(
                                f"scenario {detail.scenario_id!r} references "
                                f"unknown random variable {random_name!r}"
                            )
            for demand_name in detail.active_demands:
                if demand_name not in demand_names:
                    errors.append(
                        f"scenario {detail.scenario_id!r} references unknown "
                        f"active demand/equation {demand_name!r}"
                    )
            for player_id, components in detail.active_payoff_components.items():
                if player_id not in player_ids:
                    errors.append(
                        f"scenario {detail.scenario_id!r} references unknown "
                        f"player {player_id!r} in active_payoff_components"
                    )
                if not components:
                    errors.append(
                        f"scenario {detail.scenario_id!r} has an empty active "
                        f"payoff component list for player {player_id!r}"
                    )
                for component_id in components:
                    if component_id not in payoff_ids:
                        errors.append(
                            f"scenario {detail.scenario_id!r} references "
                            f"unknown payoff component {component_id!r}"
                        )
            for term_name in detail.active_contract_terms:
                if term_name not in contract_names:
                    errors.append(
                        f"scenario {detail.scenario_id!r} references unknown "
                        f"contract term {term_name!r}"
                    )
            for demand_name in (detail.demand_overrides or {}):
                if demand_name not in demand_names:
                    errors.append(
                        f"scenario {detail.scenario_id!r} overrides unknown "
                        f"demand/equation {demand_name!r}"
                    )
            for player_id, components in (detail.payoff_overrides or {}).items():
                if player_id not in player_ids:
                    errors.append(
                        f"scenario {detail.scenario_id!r} payoff_overrides "
                        f"uses unknown player {player_id!r}"
                    )
                for component_id in components:
                    if component_id not in payoff_ids:
                        errors.append(
                            f"scenario {detail.scenario_id!r} payoff_overrides "
                            f"references unknown payoff component {component_id!r}"
                        )

        if self.scenario_details and random_names:
            for stage in self.solving_stages:
                decider_ids = [
                    decider.player_id
                    for decider in stage.deciders
                    if decider.player_id in player_ids
                ]
                if not decider_ids:
                    continue

                default_info = {
                    decider.player_id: tuple(sorted(decider.informed_about))
                    for decider in stage.deciders
                }
                scenario_signatures = []
                for detail in self.scenario_details:
                    player_map = detail.informed_overrides.get(stage.stage_id, {})
                    signature = tuple(
                        (
                            player_id,
                            tuple(
                                sorted(
                                    player_map.get(
                                        player_id,
                                        list(default_info.get(player_id, ())),
                                    )
                                )
                            ),
                        )
                        for player_id in decider_ids
                    )
                    scenario_signatures.append(signature)

                if (
                    len(set(scenario_signatures)) > 1
                    and stage.expectation_handling
                    != ExpectationHandling.MIXED_BY_SCENARIO
                ):
                    errors.append(
                        f"solving stage {stage.stage_id!r} has scenario-specific "
                        "information differences in informed_overrides and must "
                        "use expectation_handling='mixed_by_scenario'"
                    )

        if basics.contract_terms:
            contract_stage_exists = any(
                stage.uses_contract_terms for stage in self.solving_stages
            )
            if not contract_stage_exists:
                errors.append(
                    "basics defines contract_terms, but no solving stage uses them"
                )

        if basics.information_structure.random_variables:
            expectation_mentions = any(
                stage.expectation_handling != ExpectationHandling.NOT_NEEDED
                for stage in self.solving_stages
            )
            if not expectation_mentions:
                errors.append(
                    "basics defines random variables, but no solving stage "
                    "specifies expectation handling"
                )

        return errors

    def assert_valid_against_basics(self, basics: GameBasics) -> None:
        errors = self.validate_against_basics(basics)
        if errors:
            raise ValueError(
                "SolvingProcedure validation failed:\n  - "
                + "\n  - ".join(errors)
            )


class ResearchQuestionType(str, Enum):
    OPTIMAL_CHOICE = "optimal_choice"
    COMPARATIVE_STATICS = "comparative_statics"
    PROFIT_COMPARISON = "profit_comparison"
    WELFARE_COMPARISON = "welfare_comparison"
    MECHANISM_INSIGHT = "mechanism_insight"
    OTHER = "other"


class ResearchQuestion(StrictModel):
    id: str
    question: str
    question_type: ResearchQuestionType = ResearchQuestionType.OTHER
    target_scenarios: list[str] = Field(default_factory=list)
    target_players: list[str] = Field(default_factory=list)
    target_metrics: list[str] = Field(default_factory=list)
    description: str | None = None

    def validate_against_basics(self, basics: GameBasics) -> list[str]:
        errors: list[str] = []
        scenario_ids = {scenario.id for scenario in basics.scenario_overview}
        player_ids = {player.id for player in basics.players}
        for scenario_id in self.target_scenarios:
            if scenario_ids and scenario_id not in scenario_ids:
                errors.append(
                    f"research question {self.id!r} references unknown "
                    f"scenario {scenario_id!r}"
                )
        for player_id in self.target_players:
            if player_id not in player_ids:
                errors.append(
                    f"research question {self.id!r} references unknown "
                    f"player {player_id!r}"
                )
        return errors


class ModelSpec(StrictModel):
    """Final Phase 0 artifact consumed by downstream solver generation."""

    basics: GameBasics
    procedure: SolvingProcedure
    research_questions: list[ResearchQuestion] = Field(default_factory=list)
    meta: ModelMeta = Field(default_factory=ModelMeta)

    def validate_cross_references(self) -> list[str]:
        errors: list[str] = []
        errors.extend(self.basics.validate_cross_references())
        errors.extend(self.procedure.validate_against_basics(self.basics))
        for question in self.research_questions:
            errors.extend(question.validate_against_basics(self.basics))
        return errors

    def assert_valid(self) -> None:
        errors = self.validate_cross_references()
        if errors:
            raise ValueError(
                "ModelSpec validation failed:\n  - " + "\n  - ".join(errors)
            )


def _is_symbol_name(value: str) -> bool:
    return bool(value) and value[0].isalpha() and value.replace("_", "").isalnum()


def _check_unique(errors: list[str], field_name: str, values: list[Any]) -> None:
    if len(values) != len(set(values)):
        errors.append(f"{field_name} contains duplicates")


def _check_disjoint(
    errors: list[str],
    left_name: str,
    left_values: set[Any],
    right_name: str,
    right_values: set[Any],
) -> None:
    overlap = left_values & right_values
    if overlap:
        shown = ", ".join(repr(value) for value in sorted(overlap))
        errors.append(f"{left_name} and {right_name} overlap: {shown}")


def _symbol_tokens(expression: str) -> set[str]:
    return set(re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", expression))
