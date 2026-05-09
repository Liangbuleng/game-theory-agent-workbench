"""Generate Wolfram Language scripts from a finalized ModelSpec.

Phase 1 is intentionally deterministic: it does not ask an LLM to write code.
The v1 generator supports the backward-induction / FOC style used by the
current ModelSpec schema and emits one scenario script plus a runner.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable

import yaml

from agent.schemas import (
    ModelSpec,
    PayoffComponent,
    PayoffComponentType,
    ScenarioDetail,
    SolvingStage,
    StageSolveType,
    VariableDomain,
)


@dataclass(frozen=True)
class WolframGenerationOptions:
    """Options controlling the generated Wolfram solving strategy."""

    solve_timeout_seconds: int = 120
    simplify_timeout_seconds: int = 30
    solve_mode: str = "symbolic"
    parameter_values: dict[str, str | int | float] = field(default_factory=dict)
    export_intermediates: bool = True

    def __post_init__(self) -> None:
        if self.solve_mode not in {"symbolic", "semi_numeric", "numeric"}:
            raise ValueError(
                "solve_mode must be one of: symbolic, semi_numeric, numeric"
            )
        if self.solve_timeout_seconds <= 0:
            raise ValueError("solve_timeout_seconds must be positive")
        if self.simplify_timeout_seconds <= 0:
            raise ValueError("simplify_timeout_seconds must be positive")


@dataclass(frozen=True)
class WolframGenerationResult:
    output_dir: Path
    scenario_scripts: dict[str, Path]
    run_all_path: Path
    readme_path: Path
    manifest_path: Path


def load_modelspec(path: str | Path) -> ModelSpec:
    """Load a finalized ModelSpec from YAML or JSON."""

    spec_path = Path(path)
    text = spec_path.read_text(encoding="utf-8")
    if spec_path.suffix.lower() in {".yaml", ".yml"}:
        data = yaml.safe_load(text)
        spec = ModelSpec.model_validate(data)
    else:
        spec = ModelSpec.model_validate_json(text)
    spec.assert_valid()
    return spec


def generate_wolfram_scripts(
    modelspec: ModelSpec | str | Path,
    output_dir: str | Path,
    options: WolframGenerationOptions | None = None,
) -> WolframGenerationResult:
    """Generate Wolfram scripts for all scenarios in a ModelSpec."""

    spec = load_modelspec(modelspec) if isinstance(modelspec, (str, Path)) else modelspec
    return WolframScriptGenerator(spec, options=options).generate(output_dir)


class WolframScriptGenerator:
    """Template-based ModelSpec -> Wolfram Language script generator."""

    def __init__(
        self,
        spec: ModelSpec,
        *,
        options: WolframGenerationOptions | None = None,
    ) -> None:
        spec.assert_valid()
        self.spec = spec
        self.options = options or WolframGenerationOptions()
        self._symbol_map = self._build_symbol_map()

    def generate(self, output_dir: str | Path) -> WolframGenerationResult:
        output = Path(output_dir)
        scenario_dir = output / "scenarios"
        scenario_dir.mkdir(parents=True, exist_ok=True)

        scripts: dict[str, Path] = {}
        for detail in self.spec.procedure.scenario_details:
            path = scenario_dir / f"{_safe_filename(detail.scenario_id)}.wl"
            path.write_text(self.render_scenario_script(detail), encoding="utf-8")
            scripts[detail.scenario_id] = path

        run_all_path = output / "run_all.wl"
        run_all_path.write_text(self.render_run_all(scripts), encoding="utf-8")

        readme_path = output / "README.md"
        readme_path.write_text(self.render_readme(scripts), encoding="utf-8")

        manifest_path = output / "manifest.json"
        manifest = {
            "generator": "phase1-wolfram-stage-driven-v1",
            "title": self.spec.basics.title,
            "method": self.spec.procedure.method.value,
            "options": self._options_manifest(),
            "scenario_count": len(scripts),
            "scenarios": [
                {
                    "scenario_id": scenario_id,
                    "script": str(path.relative_to(output)),
                    "result": str(
                        (Path("scenarios") / f"{_safe_filename(scenario_id)}_result.json")
                    ),
                }
                for scenario_id, path in scripts.items()
            ],
            "run_all": "run_all.wl",
        }
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        return WolframGenerationResult(
            output_dir=output,
            scenario_scripts=scripts,
            run_all_path=run_all_path,
            readme_path=readme_path,
            manifest_path=manifest_path,
        )

    def render_scenario_script(self, detail: ScenarioDetail) -> str:
        scenario = self._scenario_overview(detail.scenario_id)
        active_demands = self._active_demands(detail)
        active_components = self._active_components(detail)

        lines: list[str] = []
        emit = lines.append

        emit("(* Generated by game-theory-agent Phase 1: Wolfram script v1. *)")
        emit(f"(* Title: {self.spec.basics.title} *)")
        emit(f"(* Scenario: {detail.scenario_id} - {scenario.description} *)")
        emit("(* Edit the generated script only for local experiments; regenerate from ModelSpec for canonical artifacts. *)")
        emit("")
        emit('ClearAll["Global`*"];')
        emit(f'scenarioId = "{_wl_string(detail.scenario_id)}";')
        emit(f'scenarioDescription = "{_wl_string(scenario.description)}";')
        emit('status = "success";')
        emit('failedAt = "";')
        emit("warnings = {};")
        emit("solveDiagnostics = <||>;")
        emit("")
        self._emit_runtime_helpers(emit)

        self._emit_symbol_map(emit)
        self._emit_assumptions(emit)
        self._emit_expectation_helpers(emit)
        self._emit_demands(emit, active_demands)
        self._emit_payoff_components(emit, active_components)
        self._emit_raw_payoffs(emit, active_components)
        self._emit_stage_driven_solver(emit, detail, active_components)
        self._emit_compatibility_summary(emit, detail)
        self._emit_result_export(emit, detail, active_components)

        return "\n".join(lines) + "\n"

    def render_run_all(self, scripts: dict[str, Path]) -> str:
        entries = ",\n  ".join(
            f'<| "scenario_id" -> "{_wl_string(sid)}", "script" -> "{_wl_string(path.name)}", "result" -> "{_wl_string(_safe_filename(sid))}_result.json" |>'
            for sid, path in scripts.items()
        )
        return f"""(* Generated by game-theory-agent Phase 1. *)
ClearAll["Global`*"];

rootDir = DirectoryName[$InputFileName];
scenarioDir = FileNameJoin[{{rootDir, "scenarios"}}];
scenarioEntries = {{
  {entries}
}};

runResults = Association[];
Do[
  scriptPath = FileNameJoin[{{scenarioDir, entry["script"]}}];
  resultPath = FileNameJoin[{{scenarioDir, entry["result"]}}];
  Print["Running scenario ", entry["scenario_id"], " from ", scriptPath];
  Get[scriptPath];
  If[FileExistsQ[resultPath],
    AssociateTo[runResults, entry["scenario_id"] -> Import[resultPath, "JSON"]],
    AssociateTo[runResults, entry["scenario_id"] -> <|"status" -> "missing_result", "script" -> scriptPath|>]
  ],
  {{entry, scenarioEntries}}
];

Export[FileNameJoin[{{rootDir, "all_results.json"}}], runResults, "JSON"];
Print["Phase 1 run complete. Results: ", FileNameJoin[{{rootDir, "all_results.json"}}]];
"""

    def render_readme(self, scripts: dict[str, Path]) -> str:
        script_lines = "\n".join(
            f"- `{path.as_posix()}` -> `scenarios/{_safe_filename(scenario_id)}_result.json`"
            for scenario_id, path in scripts.items()
        )
        return f"""# Phase 1 Wolfram Scripts

Generated from `ModelSpec` for:

`{self.spec.basics.title}`

## How To Run

From Wolfram/Mathematica:

```wolfram
Get["run_all.wl"]
```

Or run one scenario directly:

```wolfram
Get["scenarios/{next(iter(scripts.values())).name if scripts else '<scenario>.wl'}"]
```

## Generated Files

- `run_all.wl`: runs all scenario scripts and writes `all_results.json`.
- `manifest.json`: machine-readable file list.
- Scenario scripts:
{script_lines}

## Solver Options

The generated scripts include `phase1Options`, `TimeConstrained` wrappers for
symbolic solving and simplification, and optional parameter substitutions.
`solve_mode` can be `symbolic`, `semi_numeric`, or `numeric`.

## Current Scope

This v1 generator is stage-driven: it reads
`ModelSpec.procedure.solving_stages` and dispatches by `solve_type`.
Continuous FOC stages emit executable symbolic Wolfram code. Discrete,
enumeration, and non-FOC optimization stages emit structured `stageResults`
summaries with strategy profiles, objectives, contract terms, and solver hints.
Later Phase 1 iterations can add stronger symbolic/numeric solving inside each
stage handler without changing the ModelSpec contract.
"""

    def _options_manifest(self) -> dict[str, object]:
        return {
            "solve_timeout_seconds": self.options.solve_timeout_seconds,
            "simplify_timeout_seconds": self.options.simplify_timeout_seconds,
            "solve_mode": self.options.solve_mode,
            "parameter_values": dict(self.options.parameter_values),
            "export_intermediates": self.options.export_intermediates,
        }

    def _emit_runtime_helpers(self, emit) -> None:
        emit("(* Runtime options and safe solver helpers. *)")
        emit(f"solveTimeoutSeconds = {self.options.solve_timeout_seconds};")
        emit(f"simplifyTimeoutSeconds = {self.options.simplify_timeout_seconds};")
        emit(f'solveMode = "{_wl_string(self.options.solve_mode)}";')
        emit(f"exportIntermediates = {_wl_bool(self.options.export_intermediates)};")
        emit("phase1Options = <|")
        emit(f'  "solve_timeout_seconds" -> solveTimeoutSeconds,')
        emit(f'  "simplify_timeout_seconds" -> simplifyTimeoutSeconds,')
        emit(f'  "solve_mode" -> solveMode,')
        emit(f'  "export_intermediates" -> exportIntermediates,')
        emit('  "parameter_values" -> <|')
        items = list(self.options.parameter_values.items())
        for index, (name, value) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            emit(f'    "{_wl_string(name)}" -> "{_wl_string(value)}"{comma}')
        emit("  |>")
        emit("|>;")
        emit("markPartial[label_] := (If[status === \"success\", status = \"partial\"]; If[failedAt === \"\", failedAt = label]; AppendTo[warnings, label]);")
        emit("exact[expr_] := Rationalize[expr, 0];")
        emit("safeSimplify[expr_, label_] := Module[{value},")
        emit("  value = Quiet[TimeConstrained[FullSimplify[expr, $Assumptions], simplifyTimeoutSeconds, $Failed]];")
        emit("  If[value === $Failed, markPartial[label <> \" simplify timeout\"]; expr, value]")
        emit("];")
        emit("ruleListQ[item_] := ListQ[item] && AllTrue[item, MatchQ[#, _Rule] &];")
        emit("normalizeRules[rules_] := Which[Head[rules] === Rule, {rules}, ruleListQ[rules], rules, True, {}];")
        emit("normalizeRuleSets[sols_] := Which[")
        emit("  sols === $Failed, {},")
        emit("  Head[sols] === Rule, {{sols}},")
        emit("  ruleListQ[sols], {sols},")
        emit("  ListQ[sols], Select[sols, ruleListQ],")
        emit("  True, {}")
        emit("];")
        emit("firstRuleSet[sets_] := If[ListQ[sets] && Length[sets] > 0, First[sets], {}];")
        emit("substituteRuleRHS[rule_Rule, rules_] := rule[[1]] -> (rule[[2]] /. rules);")
        emit("substituteRulesRHS[rules_, allRules_] := substituteRuleRHS[#, allRules] & /@ rules;")
        emit("solveRuleSets[equations_, vars_, label_] := Module[{sols, reduced, rules, numeric, ruleSets},")
        emit("  If[Length[vars] == 0, Return[{}]];")
        emit("  sols = If[solveMode === \"numeric\",")
        emit("    Quiet[TimeConstrained[NSolve[N[equations], vars, Reals], solveTimeoutSeconds, $Failed]],")
        emit("    Quiet[TimeConstrained[Solve[equations, vars, Reals], solveTimeoutSeconds, $Failed]]")
        emit("  ];")
        emit("  If[sols === $Failed, markPartial[label <> \" solve timeout\"], ruleSets = normalizeRuleSets[sols]; If[Length[ruleSets] > 0, Return[ruleSets]]];")
        emit("  If[solveMode =!= \"numeric\",")
        emit("    reduced = Quiet[TimeConstrained[Reduce[equations, vars, Reals], solveTimeoutSeconds, $Failed]];")
        emit("    If[reduced === $Failed, markPartial[label <> \" reduce timeout\"],")
        emit("      rules = normalizeRules[Quiet[ToRules[reduced]]];")
        emit("      If[Length[rules] > 0, Return[{rules}]]")
        emit("    ];")
        emit("  ];")
        emit("  If[solveMode =!= \"symbolic\",")
        emit("    numeric = Quiet[TimeConstrained[NSolve[N[equations], vars, Reals], solveTimeoutSeconds, $Failed]];")
        emit("    If[numeric =!= $Failed, ruleSets = normalizeRuleSets[numeric]; If[Length[ruleSets] > 0, Return[ruleSets]]];")
        emit("  ];")
        emit("  markPartial[label <> \" returned no solution\"];")
        emit("  {}")
        emit("];")
        emit("solveRules[equations_, vars_, label_] := firstRuleSet[solveRuleSets[equations, vars, label]];")
        emit("safeTruth[expr_, label_] := Module[{value},")
        emit("  value = Quiet[TimeConstrained[FullSimplify[expr, $Assumptions], simplifyTimeoutSeconds, $Failed]];")
        emit("  Which[value === True, True, value === False, False, value === $Failed, markPartial[label <> \" truth timeout\"]; \"unknown\", TrueQ[value], True, TrueQ[Not[value]], False, True, \"unknown\"]")
        emit("];")
        emit("optimizeResult[objective_, vars_, constraints_, label_] := Module[{symbolic, numeric},")
        emit("  If[Length[vars] == 0, Return[<|\"status\" -> \"skipped\", \"value\" -> ToString[objective, InputForm], \"rules\" -> \"{}\", \"raw_rules\" -> {}|>]];")
        emit("  symbolic = Quiet[TimeConstrained[Maximize[{objective, constraints}, vars, Reals], solveTimeoutSeconds, $Failed]];")
        emit("  If[ListQ[symbolic] && Length[symbolic] == 2, Return[<|\"status\" -> \"symbolic\", \"value\" -> ToString[First[symbolic], InputForm], \"rules\" -> ToString[Last[symbolic], InputForm], \"raw_rules\" -> Last[symbolic]|>]];")
        emit("  If[symbolic === $Failed, markPartial[label <> \" maximize timeout\"]];")
        emit("  If[solveMode =!= \"symbolic\",")
        emit("    numeric = Quiet[TimeConstrained[NMaximize[{N[objective], constraints}, vars], solveTimeoutSeconds, $Failed]];")
        emit("    If[ListQ[numeric] && Length[numeric] == 2, Return[<|\"status\" -> \"numeric\", \"value\" -> ToString[First[numeric], InputForm], \"rules\" -> ToString[Last[numeric], InputForm], \"raw_rules\" -> Last[numeric]|>]];")
        emit("    If[numeric === $Failed, markPartial[label <> \" nmaximize timeout\"]];")
        emit("  ];")
        emit("  markPartial[label <> \" optimize returned no solution\"];")
        emit("  <|\"status\" -> \"no_solution\", \"value\" -> \"\", \"rules\" -> \"{}\", \"raw_rules\" -> {}|>")
        emit("];")
        emit("")

    def _emit_symbol_map(self, emit) -> None:
        emit("(* ModelSpec name -> Wolfram-safe symbol map. *)")
        emit("nameMap = <|")
        items = sorted(self._symbol_map.items())
        for index, (original, safe) in enumerate(items):
            comma = "," if index < len(items) - 1 else ""
            emit(f'  "{_wl_string(original)}" -> "{_wl_string(safe)}"{comma}')
        emit("|>;")
        emit("")

        decision_symbols = [self._sym(var.name) for var in self.spec.basics.decision_variables]
        parameter_symbols = [self._sym(param.name) for param in self.spec.basics.parameters]
        random_symbols = [
            self._sym(rv.name) for rv in self.spec.basics.information_structure.random_variables
        ]
        emit(f"decisionVariables = {{{', '.join(decision_symbols)}}};")
        emit(f"parameterSymbols = {{{', '.join(parameter_symbols)}}};")
        emit(f"randomVariables = {{{', '.join(random_symbols)}}};")
        emit("")

    def _emit_assumptions(self, emit) -> None:
        emit("(* Parameters, fixed values, and assumptions. *)")
        for param in self.spec.basics.parameters:
            if param.fixed_value:
                emit(f"{self._sym(param.name)} = {self._expr(param.fixed_value)};")
        for name, value in self.options.parameter_values.items():
            if name in self._symbol_map:
                emit(f"{self._sym(name)} = {self._wl_value(value)};")

        assumptions = []
        for param in self.spec.basics.parameters:
            if param.fixed_value:
                continue
            assumptions.extend(self._domain_assumptions(param.name, param.domain))
            if param.custom_domain:
                assumptions.append(self._constraint(param.custom_domain))
        for var in self.spec.basics.decision_variables:
            assumptions.extend(self._domain_assumptions(var.name, var.domain))
        for constraint in self.spec.basics.parameter_constraints:
            assumptions.append(self._constraint(constraint.expression))

        assumptions = [item for item in assumptions if item]
        if assumptions:
            emit("$Assumptions = FullSimplify[")
            emit("  exact[")
            emit("    " + " &&\n    ".join(f"({item})" for item in assumptions))
            emit("  ]")
            emit("];")
        else:
            emit("$Assumptions = True;")
        emit("")

    def _emit_expectation_helpers(self, emit) -> None:
        emit("(* Expectation helpers generated from random variable realizations. *)")
        emit("expectedAll[expr_] := safeSimplify[")
        emit("  " + self._expectation_expr("expr", self._random_names()))
        emit("  , \"expectedAll\"")
        emit("];")
        emit("")

    def _emit_demands(self, emit, active_demands) -> None:
        emit("(* Active demand/equation definitions for this scenario. *)")
        for demand in active_demands:
            safe = self._sym(demand.name)
            expr = self._expr(demand.expression.formula)
            emit(f"(* {demand.name}: {demand.expression.description or demand.description or ''} *)")
            emit(f"{safe}Expr = safeSimplify[exact[{expr}], \"demand {safe}\"];")
            emit(f"{safe} = {safe}Expr;")
        emit("")

    def _emit_payoff_components(self, emit, active_components: list[PayoffComponent]) -> None:
        emit("(* Active payoff component definitions for this scenario. *)")
        for component in active_components:
            safe = self._component_expr_name(component.id)
            expr = self._expr(component.expression.formula)
            emit(f"(* {component.id}: player={component.player_id}, type={component.component_type.value} *)")
            emit(f"{safe} = safeSimplify[exact[{expr}], \"payoff component {safe}\"];")
        emit("")

    def _emit_raw_payoffs(self, emit, active_components: list[PayoffComponent]) -> None:
        emit("(* Raw player payoffs assembled from active payoff components. *)")
        by_player: dict[str, list[PayoffComponent]] = {}
        for component in active_components:
            by_player.setdefault(component.player_id, []).append(component)

        for player in self.spec.basics.players:
            components = by_player.get(player.id, [])
            terms = [self._signed_component_term(component) for component in components]
            payoff_expr = " + ".join(terms).replace("+ -", "- ") if terms else "0"
            emit(f"{self._payoff_name(player.id)} = safeSimplify[{payoff_expr}, \"raw payoff {self._payoff_name(player.id)}\"];")
        emit("")

    def _emit_stage_driven_solver(
        self,
        emit,
        detail: ScenarioDetail,
        active_components: list[PayoffComponent],
    ) -> None:
        emit("(* Stage-driven solving program generated from procedure.solving_stages. *)")
        emit("stageResults = <||>;")
        emit("equilibriumRules = {};")
        emit("")

        for stage in self.spec.procedure.solving_stages:
            self._emit_solving_stage(emit, stage, detail, active_components)

    def _emit_solving_stage(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
        active_components: list[PayoffComponent],
    ) -> None:
        if stage.solve_type in {
            StageSolveType.SIMULTANEOUS_FOC,
            StageSolveType.SEQUENTIAL_FOC,
        }:
            self._emit_continuous_foc_stage(emit, stage, detail)
            return

        if stage.solve_type == StageSolveType.OPTIMIZATION:
            if self._stage_has_active_continuous_formula_vars(stage, detail, active_components):
                self._emit_continuous_foc_stage(emit, stage, detail)
            else:
                self._emit_optimization_summary_stage(emit, stage, detail)
            return

        if stage.solve_type in {
            StageSolveType.DISCRETE_PAYOFF_MATRIX,
            StageSolveType.ENUMERATION,
        }:
            self._emit_discrete_stage(emit, stage, detail)
            return

        self._emit_unsupported_stage(emit, stage)

    def _emit_continuous_foc_stage(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
    ) -> None:
        stage_var = self._stage_var(stage.stage_id)
        emit(f"(* Solving stage: {stage.stage_id} ({stage.solve_type.value}). *)")
        emit(f"(* {stage.description} *)")
        emit(f"{stage_var}BaseRules = equilibriumRules;")

        info_map = self._stage_information(stage, detail)
        for player_id, known in info_map.items():
            known_text = ", ".join(known) if known else "none"
            emit(f"(* information: {player_id} knows {known_text} *)")

        groups = self._move_groups(
            stage,
            detail,
            sequential=stage.solve_type == StageSolveType.SEQUENTIAL_FOC,
        )
        solved_rule_names: list[str] = []
        if not groups:
            emit(f"markPartial[\"No active continuous decision variables found for stage {stage.stage_id}\"];")
            emit(f'AssociateTo[stageResults, "{_wl_string(stage.stage_id)}" -> <|"solve_type" -> "{stage.solve_type.value}", "status" -> "skipped", "reason" -> "no active continuous decision variables"|>];')
            emit("")
            return

        for order, decider_ids, variables in groups:
            suffix = f"{stage_var}Move{order}"
            local_later_rules = self._join_rules(solved_rule_names)
            later_rules = (
                f"Join[{local_later_rules}, {stage_var}BaseRules]"
                if local_later_rules != "{}"
                else f"{stage_var}BaseRules"
            )
            emit(f"(* Solve move_order={order}: players {', '.join(decider_ids)}. *)")
            foc_entries: list[str] = []

            for player_id in decider_ids:
                player_vars = [
                    var
                    for var in variables
                    if self._decision_owner(var) == player_id
                ]
                if not player_vars:
                    continue
                payoff_base = f"{self._payoff_name(player_id)}Assigned{suffix}"
                reduced_name = f"{payoff_base}Reduced{suffix}"
                objective_name = f"{payoff_base}Objective{suffix}"
                emit(f"{payoff_base} = safeSimplify[{self._stage_payoff_expr(stage, player_id, detail)}, \"{suffix} assigned payoff {player_id}\"];")
                reduced_expr = f"({payoff_base} /. {later_rules})"
                emit(f"{reduced_name} = safeSimplify[{reduced_expr}, \"{suffix} reduced payoff {player_id}\"];")
                unknown_randoms = [
                    name for name in self._random_names() if name not in info_map.get(player_id, set())
                ]
                objective_expr = self._expectation_expr(reduced_name, unknown_randoms)
                emit(f"{objective_name} = safeSimplify[{objective_expr}, \"{suffix} objective {player_id}\"];")
                for var in player_vars:
                    foc_entries.append(f"D[{objective_name}, {self._sym(var)}] == 0")

            if not foc_entries:
                emit(f"solutionRules{suffix} = {{}};")
                continue

            wl_vars = "{" + ", ".join(self._sym(var) for var in variables) + "}"
            foc_name = f"focs{suffix}"
            solutions_name = f"solutions{suffix}"
            rules_name = f"solutionRules{suffix}"
            emit(f"{foc_name} = {{{', '.join(foc_entries)}}};")
            emit(f'{solutions_name} = "handled by solveRules";')
            emit(f"{rules_name} = solveRules[{foc_name}, {wl_vars}, \"{suffix}\"];")
            emit(f"AssociateTo[solveDiagnostics, \"{suffix}\" -> <|\"focs\" -> ToString[{foc_name}, InputForm], \"solve_candidates\" -> ToString[{solutions_name}, InputForm], \"rules\" -> ToString[{rules_name}, InputForm]|>];")
            solved_rule_names.append(rules_name)
            emit("")

        emit(f"{stage_var}LocalRulesRaw = {self._join_rules(list(reversed(solved_rule_names)))};")
        emit(f"{stage_var}RulesRaw = Join[{stage_var}LocalRulesRaw, {stage_var}BaseRules];")
        emit(f"equilibriumRules = {stage_var}RulesRaw;")
        emit(f"Do[equilibriumRules = substituteRulesRHS[equilibriumRules, {stage_var}RulesRaw], {{5}}];")
        emit(f'AssociateTo[stageResults, "{_wl_string(stage.stage_id)}" -> <|"solve_type" -> "{stage.solve_type.value}", "status" -> status, "rules" -> ToString[equilibriumRules, InputForm]|>];')
        emit("")

    def _emit_discrete_stage(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
    ) -> None:
        stage_var = self._stage_var(stage.stage_id)
        decision_vars = self._stage_decision_vars(stage)
        symbols = "{" + ", ".join(self._sym(var) for var in decision_vars) + "}"
        names = "{" + ", ".join(_wl_quoted(var) for var in decision_vars) + "}"
        domains = "{" + ", ".join(self._wl_domain_values(var) for var in decision_vars) + "}"
        decider_ids = "{" + ", ".join(_wl_quoted(decider.player_id) for decider in stage.deciders) + "}"
        position_lines = []
        domain_lines = []
        for decider in stage.deciders:
            positions = [
                str(index + 1)
                for index, var_name in enumerate(decision_vars)
                if var_name in decider.decision_vars
            ]
            domains_for_player = [
                self._wl_domain_values(var_name)
                for var_name in decision_vars
                if var_name in decider.decision_vars
            ]
            position_lines.append(
                f'  "{_wl_string(decider.player_id)}" -> {{{", ".join(positions)}}}'
            )
            domain_lines.append(
                f'  "{_wl_string(decider.player_id)}" -> {{{", ".join(domains_for_player)}}}'
            )

        emit(f"(* Discrete/enumeration stage: {stage.stage_id} ({stage.solve_type.value}). *)")
        emit(f"(* {stage.description} *)")
        emit(f"{stage_var}DecisionNames = {names};")
        emit(f"{stage_var}DecisionSymbols = {symbols};")
        emit(f"{stage_var}DecisionDomains = {domains};")
        emit(f"{stage_var}DeciderIds = {decider_ids};")
        emit(f"{stage_var}PlayerPositions = <|")
        emit(",\n".join(position_lines))
        emit("|>;")
        emit(f"{stage_var}PlayerDomains = <|")
        emit(",\n".join(domain_lines))
        emit("|>;")
        emit(f"{stage_var}ReplaceAtPositions[profile_, positions_, values_] := ReplacePart[profile, Thread[positions -> values]];")
        emit(f"{stage_var}DeviationProfiles[player_, profile_] := Module[{{positions, domains, combos}},")
        emit(f"  positions = Lookup[{stage_var}PlayerPositions, player, {{}}];")
        emit(f"  domains = Lookup[{stage_var}PlayerDomains, player, {{}}];")
        emit("  combos = If[Length[domains] > 0, Tuples[domains], {{}}];")
        emit(f"  DeleteDuplicates[{stage_var}ReplaceAtPositions[profile, positions, #] & /@ combos]")
        emit("];")
        emit(f"{stage_var}StrategyProfiles = If[Length[{stage_var}DecisionDomains] > 0, Tuples[{stage_var}DecisionDomains], {{}}];")
        emit(f"{stage_var}ProfileRules = (Thread[{stage_var}DecisionSymbols -> #] &) /@ {stage_var}StrategyProfiles;")
        self._emit_discrete_contract_transfer(emit, stage, detail, stage_var)
        emit(f"{stage_var}PayoffValue[player_, profile_] := Module[{{rules = Thread[{stage_var}DecisionSymbols -> profile]}},")
        emit("  Switch[player,")
        payoff_cases = []
        for player in self.spec.basics.players:
            payoff = self._stage_payoff_expr(stage, player.id, detail)
            payoff_cases.append(
                f'    "{_wl_string(player.id)}", safeSimplify[expectedAll[((({payoff}) /. equilibriumRules) /. rules)] + {stage_var}ContractTransfer["{_wl_string(player.id)}", rules], "{stage.stage_id} payoff {player.id}"]'
            )
        emit(",\n".join(payoff_cases))
        emit("    , _, 0")
        emit("  ]")
        emit("];")
        emit(f"{stage_var}ProfilePayoffs = Table[")
        emit("  <|")
        emit(f'    "profile" -> AssociationThread[{stage_var}DecisionNames, profile],')
        emit('    "payoffs" -> <|')
        payoff_lines = []
        for player in self.spec.basics.players:
            payoff_lines.append(
                f'      "{_wl_string(player.id)}" -> ToString[{stage_var}PayoffValue["{_wl_string(player.id)}", profile], InputForm]'
            )
        emit(",\n".join(payoff_lines))
        emit("    |>")
        emit("  |>,")
        emit(f"  {{profile, {stage_var}StrategyProfiles}}")
        emit("];")
        emit(f"{stage_var}PureNashConditions = Table[")
        emit("  <|")
        emit(f'    "profile" -> AssociationThread[{stage_var}DecisionNames, profile],')
        emit('    "conditions" -> Flatten[Table[')
        emit("      Table[")
        emit(f'        ToString[safeSimplify[{stage_var}PayoffValue[player, profile] >= {stage_var}PayoffValue[player, deviation], "{stage.stage_id} IC"], InputForm],')
        emit(f"        {{deviation, {stage_var}DeviationProfiles[player, profile]}}")
        emit("      ],")
        emit(f"      {{player, {stage_var}DeciderIds}}")
        emit("    ]]")
        emit("  |>,")
        emit(f"  {{profile, {stage_var}StrategyProfiles}}")
        emit("];")
        self._emit_stage_contract_terms(emit, stage, detail, f"{stage_var}ContractTerms")
        emit(f'AssociateTo[stageResults, "{_wl_string(stage.stage_id)}" -> <|"solve_type" -> "{stage.solve_type.value}", "decision_variables" -> {stage_var}DecisionNames, "strategy_profiles" -> {stage_var}ProfilePayoffs, "pure_nash_conditions" -> {stage_var}PureNashConditions, "contract_terms" -> {stage_var}ContractTerms, "refinement" -> "{_wl_string(self.spec.procedure.refinement or "")}", "hint" -> "{_wl_string(stage.solver_hint or "")}"|>];')
        emit("")

    def _emit_optimization_summary_stage(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
    ) -> None:
        stage_var = self._stage_var(stage.stage_id)
        decision_vars = self._stage_decision_vars(stage)
        names = "{" + ", ".join(_wl_quoted(var) for var in decision_vars) + "}"
        deciders = "{" + ", ".join(_wl_quoted(decider.player_id) for decider in stage.deciders) + "}"

        emit(f"(* Optimization stage summary: {stage.stage_id} ({stage.solve_type.value}). *)")
        emit(f"(* {stage.description} *)")
        emit(f"{stage_var}DecisionNames = {names};")
        emit(f"{stage_var}Deciders = {deciders};")
        objective_names: dict[str, str] = {}
        for decider in stage.deciders:
            payoff = self._stage_payoff_expr(stage, decider.player_id, detail)
            objective_name = f"{stage_var}Objective{self._sym(decider.player_id)}"
            objective_names[decider.player_id] = objective_name
            contract_net = self._scenario_contract_net_expr(
                stage,
                detail,
                decider.player_id,
            )
            emit(f"{objective_name} = safeSimplify[expectedAll[({payoff}) /. equilibriumRules] + ({contract_net}), \"{stage.stage_id} objective {decider.player_id}\"];")
        emit(f"{stage_var}Objectives = <|")
        objective_lines = []
        for decider in stage.deciders:
            objective_lines.append(
                f'  "{_wl_string(decider.player_id)}" -> ToString[{objective_names[decider.player_id]}, InputForm]'
            )
        emit(",\n".join(objective_lines))
        emit("|>;")
        foc_lines = []
        rule_lines = []
        for decider in stage.deciders:
            player_vars = [
                var_name
                for var_name in decider.decision_vars
                if not self._is_discrete_indicator_var(var_name)
            ]
            wl_vars = "{" + ", ".join(self._sym(var_name) for var_name in player_vars) + "}"
            foc_name = f"{stage_var}FOCs{self._sym(decider.player_id)}"
            rules_name = f"{stage_var}CandidateRules{self._sym(decider.player_id)}"
            if player_vars:
                emit(f"{foc_name} = {{{', '.join(f'D[{objective_names[decider.player_id]}, {self._sym(var_name)}] == 0' for var_name in player_vars)}}};")
                emit(f"{rules_name} = solveRules[{foc_name}, {wl_vars}, \"{stage.stage_id} optimization {decider.player_id}\"];")
            else:
                emit(f"{foc_name} = {{}};")
                emit(f"{rules_name} = {{}};")
            foc_lines.append(f'  "{_wl_string(decider.player_id)}" -> ToString[{foc_name}, InputForm]')
            rule_lines.append(f'  "{_wl_string(decider.player_id)}" -> ToString[{rules_name}, InputForm]')
        emit(f"{stage_var}FOCs = <|")
        emit(",\n".join(foc_lines))
        emit("|>;")
        emit(f"{stage_var}CandidateRules = <|")
        emit(",\n".join(rule_lines))
        emit("|>;")
        self._emit_stage_contract_terms(emit, stage, detail, f"{stage_var}ContractTerms")
        emit(f'AssociateTo[stageResults, "{_wl_string(stage.stage_id)}" -> <|"solve_type" -> "{stage.solve_type.value}", "decision_variables" -> {stage_var}DecisionNames, "deciders" -> {stage_var}Deciders, "objectives" -> {stage_var}Objectives, "first_order_conditions" -> {stage_var}FOCs, "candidate_rules" -> {stage_var}CandidateRules, "contract_terms" -> {stage_var}ContractTerms, "uses_previous_stage_results" -> "{_wl_string("; ".join(stage.uses_previous_stage_results))}", "hint" -> "{_wl_string(stage.solver_hint or "")}"|>];')
        emit("")

    def _emit_unsupported_stage(self, emit, stage: SolvingStage) -> None:
        emit(f"(* Unsupported solving stage: {stage.stage_id} ({stage.solve_type.value}). *)")
        emit(f'markPartial["Unsupported solving stage {stage.stage_id}: {stage.solve_type.value}"];')
        emit(f'AssociateTo[stageResults, "{_wl_string(stage.stage_id)}" -> <|"solve_type" -> "{stage.solve_type.value}", "status" -> "unsupported"|>];')
        emit("")

    def _emit_discrete_contract_transfer(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
        stage_var: str,
    ) -> None:
        emit(f"{stage_var}ContractTransfer[player_, rules_] := safeSimplify[")
        transfer_cases = []
        for player in self.spec.basics.players:
            transfer_cases.append(
                f'If[player === "{_wl_string(player.id)}", {self._contract_transfer_expr(stage, detail, player.id, "rules")}, 0]'
            )
        transfer_expr = " + ".join(transfer_cases) if transfer_cases else "0"
        emit(f"  {transfer_expr},")
        emit(f'  "{stage_var} contract transfer"')
        emit("];")

    def _emit_stage_contract_terms(
        self,
        emit,
        stage: SolvingStage,
        detail: ScenarioDetail,
        target_name: str,
    ) -> None:
        terms = self._stage_contract_terms(stage, detail)
        emit(f"{target_name} = <|")
        lines = []
        for term in terms:
            amount = self._expr(term.formula)
            lines.append(
                f'  "{_wl_string(term.name)}" -> <|"payer" -> "{_wl_string(term.payer)}", "payee" -> "{_wl_string(term.payee)}", "amount" -> ToString[safeSimplify[{amount}, "contract term {term.name}"], InputForm], "triggered_when" -> "{_wl_string(term.triggered_when or "")}"|>'
            )
        emit(",\n".join(lines))
        emit("|>;")

    def _stage_contract_terms(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
    ):
        active_names = set(detail.active_contract_terms) or {
            term.name for term in self.spec.basics.contract_terms
        }
        if stage.uses_contract_terms:
            active_names &= set(stage.uses_contract_terms)
        return [
            term for term in self.spec.basics.contract_terms if term.name in active_names
        ]

    def _contract_transfer_expr(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
        player_id: str,
        rules_name: str,
    ) -> str:
        terms = []
        for term in self._stage_contract_terms(stage, detail):
            activation = self._contract_activation_expr(stage, term.payer, rules_name)
            amount = f"(({self._expr(term.formula)}) /. {rules_name})"
            if term.payer == player_id:
                terms.append(f"-(({amount}) * ({activation}))")
            if term.payee == player_id:
                terms.append(f"(({amount}) * ({activation}))")
        return " + ".join(terms).replace("+ -", "- ") if terms else "0"

    def _scenario_contract_net_expr(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
        player_id: str,
    ) -> str:
        terms = []
        for term in self._stage_contract_terms(stage, detail):
            amount = f"({self._expr(term.formula)})"
            if term.payer == player_id:
                terms.append(f"-({amount})")
            if term.payee == player_id:
                terms.append(f"({amount})")
        return " + ".join(terms).replace("+ -", "- ") if terms else "0"

    def _contract_activation_expr(
        self,
        stage: SolvingStage,
        payer_id: str,
        rules_name: str,
    ) -> str:
        payer_vars = [
            var_name
            for decider in stage.deciders
            if decider.player_id == payer_id
            for var_name in decider.decision_vars
            if self._is_discrete_indicator_var(var_name)
        ]
        if not payer_vars:
            return "1"
        factors = [f"({self._sym(var_name)} /. {rules_name})" for var_name in payer_vars]
        return " * ".join(factors)

    def _emit_compatibility_summary(self, emit, detail: ScenarioDetail) -> None:
        emit("(* Scenario-level compatibility summary for downstream readers. *)")
        informed_players = self._scenario_informed_players(detail)
        active_contract_terms = self._scenario_active_contract_term_names(detail)
        emit(f"scenarioInformedPlayers = {{{', '.join(_wl_quoted(player) for player in informed_players)}}};")
        emit(f"activeContractTermNames = {{{', '.join(_wl_quoted(term) for term in active_contract_terms)}}};")
        emit("scenarioMechanismProfile = <|")
        emit('  "informed_players" -> scenarioInformedPlayers,')
        emit('  "active_contract_terms" -> activeContractTermNames')
        emit("|>;")
        emit("expectedPricingProfits = <|")
        player_lines = []
        for player in self.spec.basics.players:
            payoff = self._payoff_name(player.id)
            player_lines.append(
                f'  "{_wl_string(player.id)}" -> ToString[expectedAll[safeSimplify[{payoff} /. equilibriumRules, "expected pricing profit {player.id}"]], InputForm]'
            )
        emit(",\n".join(player_lines))
        emit("|>;")

        contract_lines = []
        active_contract_set = set(active_contract_terms)
        for term in self.spec.basics.contract_terms:
            amount = self._expr(term.formula)
            active = term.name in active_contract_set
            contract_lines.append(
                f'  "{_wl_string(term.name)}" -> <|"payer" -> "{_wl_string(term.payer)}", "payee" -> "{_wl_string(term.payee)}", "amount" -> "{_wl_string(amount)}", "active_in_scenario" -> {_wl_bool(active)}|>'
            )
        emit("contractTerms = <|")
        emit(",\n".join(contract_lines))
        emit("|>;")
        emit('mechanismHints = <|"stage_driven_summary" -> "See stageResults for discrete, enumeration, optimization, contract, and transfer summaries generated from ModelSpec.procedure.solving_stages."|>;')
        emit("")

    def _emit_result_export(
        self,
        emit,
        detail: ScenarioDetail,
        active_components: list[PayoffComponent],
    ) -> None:
        active_vars = sorted(self._active_decision_vars(detail, active_components))
        equilibrium_entries = [
            f'      "{_wl_string(var)}" -> ToString[safeSimplify[{self._sym(var)} /. equilibriumRules, "equilibrium {var}"], InputForm]'
            for var in active_vars
        ]
        if not equilibrium_entries:
            equilibrium_entries = ['      "none" -> "no active continuous variables"']

        raw_payoff_entries = [
            f'      "{_wl_string(player.id)}" -> ToString[safeSimplify[{self._payoff_name(player.id)} /. equilibriumRules, "raw payoff equilibrium {player.id}"], InputForm]'
            for player in self.spec.basics.players
        ]
        expected_entries = [
            f'      "{_wl_string(player.id)}" -> expectedPricingProfits["{_wl_string(player.id)}"]'
            for player in self.spec.basics.players
        ]

        emit("result = <|")
        emit('  "scenario_id" -> scenarioId,')
        emit('  "scenario_description" -> scenarioDescription,')
        emit('  "status" -> status,')
        emit('  "failed_at" -> failedAt,')
        emit('  "warnings" -> warnings,')
        emit('  "solve_diagnostics" -> solveDiagnostics,')
        emit('  "stage_results" -> stageResults,')
        emit('  "phase1_options" -> phase1Options,')
        emit('  "equilibrium_rules" -> ToString[equilibriumRules, InputForm],')
        emit('  "equilibrium" -> <|')
        emit(",\n".join(equilibrium_entries))
        emit("  |>,")
        emit('  "pricing_payoffs_at_equilibrium" -> <|')
        emit(",\n".join(raw_payoff_entries))
        emit("  |>,")
        emit('  "expected_pricing_profits" -> <|')
        emit(",\n".join(expected_entries))
        emit("  |>,")
        emit('  "informed_players" -> scenarioInformedPlayers,')
        emit('  "active_contract_terms" -> activeContractTermNames,')
        emit('  "scenario_mechanism_profile" -> scenarioMechanismProfile,')
        emit('  "subscribed_players" -> scenarioInformedPlayers,')
        emit('  "contract_terms" -> contractTerms,')
        emit('  "mechanism_hints" -> mechanismHints')
        emit("|>;")
        emit("")
        emit(f'outputPath = FileNameJoin[{{DirectoryName[$InputFileName], "{_safe_filename(detail.scenario_id)}_result.json"}}];')
        emit('Export[outputPath, result, "JSON"];')
        emit('Print["Scenario ", scenarioId, " finished with status: ", status];')
        emit('Print["Result written to: ", outputPath];')

    def _build_symbol_map(self) -> dict[str, str]:
        names: list[str] = []
        names.extend(player.id for player in self.spec.basics.players)
        names.extend(var.name for var in self.spec.basics.decision_variables)
        names.extend(param.name for param in self.spec.basics.parameters)
        names.extend(rv.name for rv in self.spec.basics.information_structure.random_variables)
        names.extend(real.value for rv in self.spec.basics.information_structure.random_variables for real in rv.realizations)
        names.extend(demand.name for demand in self.spec.basics.demands)
        names.extend(component.id for component in self.spec.basics.payoff_components)
        names.extend(term.name for term in self.spec.basics.contract_terms)

        mapping: dict[str, str] = {}
        used: set[str] = set()
        for name in names:
            if name in mapping:
                continue
            base = _wolfram_identifier(name)
            candidate = base
            counter = 2
            while candidate in used:
                candidate = f"{base}{counter}"
                counter += 1
            mapping[name] = candidate
            used.add(candidate)
        return mapping

    def _scenario_overview(self, scenario_id: str):
        for scenario in self.spec.basics.scenario_overview:
            if scenario.id == scenario_id:
                return scenario
        raise ValueError(f"unknown scenario_id {scenario_id!r}")

    def _first_continuous_stage(self) -> SolvingStage | None:
        supported = {StageSolveType.SIMULTANEOUS_FOC, StageSolveType.SEQUENTIAL_FOC}
        for stage in self.spec.procedure.solving_stages:
            if stage.solve_type in supported:
                return stage
        return None

    def _active_demands(self, detail: ScenarioDetail):
        names = set(detail.active_demands)
        if not names:
            names = {demand.name for demand in self.spec.basics.demands}
        return [demand for demand in self.spec.basics.demands if demand.name in names]

    def _active_components(self, detail: ScenarioDetail) -> list[PayoffComponent]:
        names = {
            component_id
            for components in detail.active_payoff_components.values()
            for component_id in components
        }
        if not names:
            names = {
                component.id for component in self.spec.basics.payoff_components
            }
        return [
            component
            for component in self.spec.basics.payoff_components
            if component.id in names
        ]

    def _stage_payoff_expr(
        self,
        stage: SolvingStage,
        player_id: str,
        detail: ScenarioDetail,
    ) -> str:
        component_ids = stage.profit_function_assignments.get(player_id, [])
        if not component_ids:
            return self._payoff_name(player_id)

        active_ids = {component.id for component in self._active_components(detail)}
        component_ids = [
            component_id for component_id in component_ids if component_id in active_ids
        ]
        components = [
            component
            for component_id in component_ids
            if (component := self._component_by_id(component_id)) is not None
        ]
        if not components:
            return "0"

        terms = [self._signed_component_term(component) for component in components]
        return " + ".join(terms).replace("+ -", "- ")

    def _component_by_id(self, component_id: str) -> PayoffComponent | None:
        for component in self.spec.basics.payoff_components:
            if component.id == component_id:
                return component
        return None

    def _stage_information(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
    ) -> dict[str, set[str]]:
        info = {
            decider.player_id: set(decider.informed_about)
            for decider in stage.deciders
        }
        overrides = detail.informed_overrides.get(stage.stage_id, {})
        for player_id, randoms in overrides.items():
            info[player_id] = set(randoms)
        return info

    def _move_groups(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
        *,
        sequential: bool,
    ) -> list[tuple[int, list[str], list[str]]]:
        active_components = self._active_components(detail)
        active_vars = self._active_decision_vars(detail, active_components)
        continuous_vars = {
            var.name
            for var in self.spec.basics.decision_variables
            if var.domain not in {VariableDomain.BINARY, VariableDomain.DISCRETE}
        }
        active_vars &= continuous_vars
        timing_stage = next(
            (
                item
                for item in self.spec.basics.decision_timing.stages
                if item.stage_number == stage.corresponds_to_decision_stage
            ),
            None,
        )
        move_order: dict[str, int] = {}
        if timing_stage is not None:
            for decision in timing_stage.decisions:
                move_order[decision.decider] = decision.move_order or 1

        decider_ids = [decider.player_id for decider in stage.deciders]
        by_order: dict[int, list[str]] = {}
        for decider in stage.deciders:
            order = move_order.get(decider.player_id, 1) if sequential else 1
            vars_for_decider = [
                var for var in decider.decision_vars if var in active_vars
            ]
            if vars_for_decider:
                by_order.setdefault(order, []).extend(vars_for_decider)

        groups = []
        for order in sorted(by_order.keys(), reverse=True):
            vars_for_order = _dedupe(by_order[order])
            players = [
                player_id
                for player_id in decider_ids
                if any(
                    self._decision_owner(var) == player_id
                    for var in vars_for_order
                )
            ]
            groups.append((order, players, vars_for_order))
        return groups

    def _active_decision_vars(
        self,
        detail: ScenarioDetail,
        active_components: list[PayoffComponent],
    ) -> set[str]:
        texts = [demand.expression.formula for demand in self._active_demands(detail)]
        texts.extend(component.expression.formula for component in active_components)
        tokens = set()
        for text in texts:
            tokens.update(_tokens(text))
        decision_names = {var.name for var in self.spec.basics.decision_variables}
        return tokens & decision_names

    def _decision_owner(self, var_name: str) -> str | None:
        for var in self.spec.basics.decision_variables:
            if var.name == var_name:
                return var.owner
        return None

    def _scenario_informed_players(self, detail: ScenarioDetail) -> list[str]:
        pricing = self._first_continuous_stage()
        if pricing is None:
            return []
        random_names = set(self._random_names())
        players = []
        for player_id, known in detail.informed_overrides.get(pricing.stage_id, {}).items():
            if set(known) & random_names:
                players.append(player_id)
        return sorted(players)

    def _scenario_active_contract_term_names(self, detail: ScenarioDetail) -> list[str]:
        if detail.active_contract_terms:
            return list(detail.active_contract_terms)
        return [term.name for term in self.spec.basics.contract_terms]

    def _stage_has_active_continuous_formula_vars(
        self,
        stage: SolvingStage,
        detail: ScenarioDetail,
        active_components: list[PayoffComponent],
    ) -> bool:
        active_formula_vars = self._active_decision_vars(detail, active_components)
        continuous_decision_vars = {
            var.name
            for var in self.spec.basics.decision_variables
            if var.domain not in {VariableDomain.BINARY, VariableDomain.DISCRETE}
        }
        stage_vars = set(self._stage_decision_vars(stage))
        return bool(active_formula_vars & continuous_decision_vars & stage_vars)

    def _stage_decision_vars(self, stage: SolvingStage) -> list[str]:
        return _dedupe(
            var_name
            for decider in stage.deciders
            for var_name in decider.decision_vars
        )

    def _wl_domain_values(self, var_name: str) -> str:
        variable = next(
            var for var in self.spec.basics.decision_variables if var.name == var_name
        )
        if variable.domain == VariableDomain.BINARY:
            return "{0, 1}"
        if variable.domain == VariableDomain.UNIT_INTERVAL:
            return "{0, 1}"
        if variable.domain == VariableDomain.DISCRETE and variable.custom_domain:
            return "{" + self._expr(variable.custom_domain).strip("{}") + "}"
        return "{}"

    def _is_discrete_indicator_var(self, var_name: str) -> bool:
        variable = next(
            (
                item
                for item in self.spec.basics.decision_variables
                if item.name == var_name
            ),
            None,
        )
        return variable is not None and variable.domain in {
            VariableDomain.BINARY,
            VariableDomain.UNIT_INTERVAL,
        }

    def _domain_assumptions(self, name: str, domain: VariableDomain) -> list[str]:
        sym = self._sym(name)
        if domain == VariableDomain.POSITIVE:
            return [f"{sym} > 0"]
        if domain == VariableDomain.NON_NEGATIVE:
            return [f"{sym} >= 0"]
        if domain == VariableDomain.UNIT_INTERVAL:
            return [f"0 <= {sym} <= 1"]
        if domain == VariableDomain.REALS:
            return [f"Element[{sym}, Reals]"]
        return []

    def _expectation_expr(self, expr: str, random_names: Iterable[str]) -> str:
        output = expr
        for random_name in random_names:
            random_variable = next(
                rv
                for rv in self.spec.basics.information_structure.random_variables
                if rv.name == random_name
            )
            random_sym = self._sym(random_name)
            terms = []
            for realization in random_variable.realizations:
                value = self._expr(realization.value)
                probability = self._expr(realization.probability)
                terms.append(f"({probability}) * (({output}) /. {random_sym} -> {value})")
            output = "(" + " + ".join(terms) + ")"
        return output

    def _random_names(self) -> list[str]:
        return [rv.name for rv in self.spec.basics.information_structure.random_variables]

    def _constraint(self, text: str) -> str:
        expr = self._expr(text)
        if "==" not in expr and re.search(r"(?<![<>=!])=(?![=])", expr):
            expr = re.sub(r"(?<![<>=!])=(?![=])", "==", expr)
        return expr

    def _signed_component_term(self, component: PayoffComponent) -> str:
        term = self._component_expr_name(component.id)
        if component.component_type == PayoffComponentType.COST:
            return f"-({term})"
        return f"({term})"

    def _join_rules(self, rule_names: list[str]) -> str:
        if not rule_names:
            return "{}"
        return f"Join[{', '.join(rule_names)}]"

    def _sym(self, name: str) -> str:
        return self._symbol_map.get(name, _wolfram_identifier(name))

    def _expr(self, formula: str) -> str:
        return _replace_tokens(formula, self._symbol_map)

    def _wl_value(self, value: str | int | float) -> str:
        if isinstance(value, (int, float)):
            return repr(value)
        return self._expr(str(value))

    def _component_expr_name(self, component_id: str) -> str:
        return f"{self._sym(component_id)}Expr"

    def _payoff_name(self, player_id: str) -> str:
        return f"payoff{self._sym(player_id)}"

    def _stage_var(self, stage_id: str) -> str:
        return f"stage{_wolfram_identifier(stage_id)[:1].upper()}{_wolfram_identifier(stage_id)[1:]}"


def _tokens(text: str) -> list[str]:
    return re.findall(r"\b[A-Za-z][A-Za-z0-9_]*\b", text or "")


def _replace_tokens(text: str, mapping: dict[str, str]) -> str:
    def repl(match: re.Match[str]) -> str:
        token = match.group(0)
        return mapping.get(token, token)

    return re.sub(r"\b[A-Za-z][A-Za-z0-9_]*\b", repl, text or "")


def _wolfram_identifier(name: str) -> str:
    parts = re.split(r"[^A-Za-z0-9]+", name)
    parts = [part for part in parts if part]
    if not parts:
        parts = ["x"]
    first = parts[0]
    rest = [part[:1].upper() + part[1:] for part in parts[1:]]
    candidate = first + "".join(rest)
    if candidate[0].isdigit():
        candidate = "x" + candidate
    candidate = re.sub(r"[^A-Za-z0-9]", "", candidate)
    reserved = {
        "C",
        "D",
        "E",
        "I",
        "N",
        "O",
        "Pi",
        "Power",
        "Plus",
        "Times",
        "Solve",
        "FullSimplify",
    }
    if candidate in reserved:
        candidate += "Sym"
    return candidate


def _safe_filename(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)


def _wl_string(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def _wl_quoted(text: str) -> str:
    return f'"{_wl_string(text)}"'


def _wl_bool(value: bool) -> str:
    return "True" if value else "False"


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item not in seen:
            result.append(item)
            seen.add(item)
    return result
