from __future__ import annotations

import json
import shutil
from pathlib import Path

import yaml

from agent.parser.output_format import Stage1Output, Stage2Output
from agent.phase1.runner import diagnose_wolfram_results, render_phase1_report
from agent.schemas import ModelSpec


ROOT = Path(__file__).resolve().parents[1]
DEMO_DIR = ROOT / "examples" / "responsible_sourcing_demo"
PHASE1_DIR = DEMO_DIR / "phase1_wolfram"
SCENARIO_DIR = PHASE1_DIR / "scenarios"
LOG_DIR = PHASE1_DIR / "run_logs"


SCENARIOS = [
    (
        "base_case",
        "moderate transparency, moderate responsible cost, and moderate buyer penalty",
        {"transparency": "moderate", "consumer_pressure": "moderate", "enforcement": "moderate"},
        "dual_sourcing",
        {"p": "1.32", "xR": "0.55", "xK": "0.45"},
        {"B": "0.184", "RS": "0.071", "KS": "0.052"},
        ["balanced profit and responsibility exposure"],
    ),
    (
        "high_transparency",
        "high transparency makes responsibility violations visible to consumers",
        {"transparency": "high", "consumer_pressure": "moderate", "enforcement": "moderate"},
        "responsible_mass_market",
        {"p": "1.44", "xR": "1.00", "xK": "0.00"},
        {"B": "0.201", "RS": "0.118", "KS": "0"},
        ["risk-sensitive consumers discipline risky sourcing"],
    ),
    (
        "high_consumer_premium",
        "socially conscious consumers have a high willingness to pay for responsibility",
        {"transparency": "moderate", "consumer_pressure": "high", "enforcement": "moderate"},
        "responsible_niche",
        {"p": "1.58", "xR": "0.62", "xK": "0.00"},
        {"B": "0.176", "RS": "0.096", "KS": "0"},
        ["responsible sourcing is profitable for the premium segment"],
    ),
    (
        "large_conscious_segment",
        "the socially conscious segment is large enough to affect mass-market design",
        {"transparency": "moderate", "consumer_pressure": "large_segment", "enforcement": "moderate"},
        "responsible_mass_market",
        {"p": "1.39", "xR": "1.00", "xK": "0.00"},
        {"B": "0.214", "RS": "0.122", "KS": "0"},
        ["consumer composition shifts the buyer toward responsible sourcing"],
    ),
    (
        "strong_penalty",
        "a regulator imposes a strong penalty on buyer responsibility violations",
        {"transparency": "moderate", "consumer_pressure": "moderate", "enforcement": "strong"},
        "responsible_mass_market",
        {"p": "1.37", "xR": "1.00", "xK": "0.00"},
        {"B": "0.192", "RS": "0.111", "KS": "0"},
        ["enforcement directly reduces risky sourcing incentives"],
    ),
    (
        "high_responsible_cost",
        "responsible supplier cost is high and enforcement is weak",
        {"transparency": "low", "consumer_pressure": "moderate", "enforcement": "weak"},
        "low_cost_sourcing",
        {"p": "1.08", "xR": "0.00", "xK": "1.00"},
        {"B": "0.167", "RS": "0", "KS": "0.083"},
        ["low-cost risky supply dominates when responsibility is expensive"],
    ),
]


def main() -> None:
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    (DEMO_DIR / "paper").mkdir(parents=True)
    SCENARIO_DIR.mkdir(parents=True)
    LOG_DIR.mkdir(parents=True)

    _write_demo_paper()
    stage1 = Stage1Output.model_validate(_stage1_data())
    stage1.assert_valid()
    stage2 = Stage2Output.model_validate(_stage2_data())
    stage2.assert_valid(stage1.basics)
    spec = ModelSpec(
        basics=stage1.basics,
        procedure=stage2.procedure,
        research_questions=stage2.research_questions,
        meta={
            "implicit_assumptions": stage1.implicit_assumptions,
            "field_confidence": stage1.field_confidence + stage2.field_confidence,
        },
    )
    spec.assert_valid()

    _write_json(DEMO_DIR / "stage1_output_v1.json", stage1.model_dump(mode="json"))
    _write_json(DEMO_DIR / "stage1_final.json", stage1.model_dump(mode="json"))
    _write_json(DEMO_DIR / "stage2_output_v1.json", stage2.model_dump(mode="json"))
    _write_json(DEMO_DIR / "stage2_final.json", stage2.model_dump(mode="json"))
    _write_json(DEMO_DIR / "modelspec_final.json", spec.model_dump(mode="json"))
    (DEMO_DIR / "modelspec_final.yaml").write_text(
        yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False, allow_unicode=True),
        encoding="utf-8",
    )

    manifest = _phase1_manifest()
    _write_json(PHASE1_DIR / "manifest.json", manifest)
    _write_phase1_scripts()
    all_results = _phase1_results()
    _write_json(PHASE1_DIR / "all_results.json", all_results)
    _write_json(PHASE1_DIR / "mechanism_summaries.json", _mechanism_summaries(all_results))
    diagnostics = diagnose_wolfram_results(PHASE1_DIR)
    _write_json(PHASE1_DIR / "phase1_diagnostics.json", diagnostics.to_dict())
    run_summary = {
        "generated_at": diagnostics.generated_at,
        "output_dir": str(PHASE1_DIR),
        "records": [],
        "counts": diagnostics.counts,
    }
    _write_json(PHASE1_DIR / "run_summary.json", run_summary)
    (PHASE1_DIR / "phase1_report.md").write_text(
        render_phase1_report(
            diagnostics,
            all_results=all_results,
            mechanism_summaries=_mechanism_summaries(all_results),
        ),
        encoding="utf-8",
    )
    (PHASE1_DIR / "README.md").write_text(
        "# Demo Wolfram Artifacts\n\n"
        "These scripts and JSON files are precomputed for the online demo. "
        "They are not generated from a copyrighted source document.\n",
        encoding="utf-8",
    )


def _write_demo_paper() -> None:
    text = """# Synthetic Responsible Sourcing Game

This synthetic teaching example studies a buyer choosing how to source a
consumer product. The buyer can purchase from a responsible supplier that uses
audited social and environmental practices, or from a risky low-cost supplier
that may suffer a responsibility violation.

The market has regular consumers and socially conscious consumers. Socially
conscious consumers value responsible sourcing and may abandon the product if a
violation becomes visible. The buyer chooses a sourcing strategy and retail
price, while supplier allocation determines how much demand is served by each
supplier type.

The example compares low-cost sourcing, dual sourcing, responsible niche
sourcing, and responsible mass-market sourcing under different transparency,
consumer-pressure, and enforcement conditions. The central question is when
consumer pressure, transparency, or penalties move the buyer toward responsible
sourcing.
"""
    (DEMO_DIR / "paper" / "demo_model.md").write_text(text, encoding="utf-8")


def _stage1_data() -> dict[str, object]:
    scenarios = [
        {"id": sid, "description": desc, "axis_values": axis}
        for sid, desc, axis, *_rest in SCENARIOS
    ]
    return {
        "basics": {
            "title": "Synthetic Responsible Sourcing Game",
            "source": "examples/responsible_sourcing_demo/paper/demo_model.md",
            "game_type": "stackelberg",
            "players": [
                {"id": "B", "name": "Buyer", "role": "leader", "description": "Chooses sourcing strategy and price."},
                {"id": "RS", "name": "Responsible Supplier", "role": "follower", "description": "Higher-cost supplier with audited responsible practices."},
                {"id": "KS", "name": "Risky Supplier", "role": "follower", "description": "Lower-cost supplier exposed to responsibility violations."},
                {"id": "C", "name": "Consumers", "role": "unspecified", "description": "Regular and socially conscious demand segments."},
            ],
            "decision_variables": [
                {"name": "s", "owner": "B", "domain": "Discrete", "custom_domain": "{LC, DS, RN, RM}", "description": "Buyer sourcing strategy."},
                {"name": "p", "owner": "B", "domain": "Positive", "description": "Retail price."},
                {"name": "xR", "owner": "B", "domain": "UnitInterval", "description": "Demand share sourced responsibly."},
                {"name": "xK", "owner": "B", "domain": "UnitInterval", "description": "Demand share sourced from the risky supplier."},
            ],
            "parameters": [
                {"name": "a", "domain": "Positive", "description": "Base market size."},
                {"name": "b", "domain": "Positive", "description": "Price sensitivity."},
                {"name": "lambda", "domain": "UnitInterval", "description": "Share of socially conscious consumers."},
                {"name": "v", "domain": "Positive", "description": "Responsibility premium among conscious consumers."},
                {"name": "cR", "domain": "Positive", "description": "Responsible supplier unit cost."},
                {"name": "cK", "domain": "Positive", "description": "Risky supplier unit cost."},
                {"name": "rho", "domain": "UnitInterval", "description": "Violation probability for risky sourcing."},
                {"name": "tau", "domain": "UnitInterval", "description": "Transparency level."},
                {"name": "F", "domain": "NonNegative", "description": "Buyer penalty if a violation is detected."},
            ],
            "parameter_constraints": [
                {"expression": "a > 0 && b > 0 && cR > cK > 0", "description": "Responsible supply is more costly."},
                {"expression": "0 <= lambda <= 1 && 0 <= rho <= 1 && 0 <= tau <= 1", "description": "Probabilities and shares are bounded."},
            ],
            "information_structure": {
                "random_variables": [
                    {"name": "violation", "realizations": [{"value": "0", "probability": "1 - rho"}, {"value": "1", "probability": "rho"}], "description": "Whether risky sourcing suffers a responsibility violation."}
                ],
                "access": [
                    {"player_id": "B", "knows": ["violation"], "when": "in expectation before sourcing", "description": "The buyer knows the violation distribution, not the realization."}
                ],
                "action_observability": [
                    {"observer": "C", "observed_player": "B", "observed_decision_vars": ["s", "p"], "when": "before purchase"}
                ],
            },
            "decision_timing": {
                "stages": [
                    {"stage_number": 1, "description": "Buyer selects sourcing strategy and supplier allocation.", "decisions": [{"decider": "B", "decision_vars": ["s", "xR", "xK"], "move_order": 1, "decision_role": "mechanism_design"}]},
                    {"stage_number": 2, "description": "Buyer sets retail price after choosing the sourcing posture.", "decisions": [{"decider": "B", "decision_vars": ["p"], "move_order": 1, "observes_before_deciding": ["s", "xR", "xK"], "decision_role": "pricing"}]},
                ]
            },
            "demands": [
                {"name": "Dregular", "expression": {"formula": "(1 - lambda) * Max[a - b*p, 0]"}, "description": "Regular consumer demand."},
                {"name": "Dconscious", "expression": {"formula": "lambda * Max[a + v*xR - tau*rho*xK - b*p, 0]"}, "description": "Socially conscious demand adjusted for responsibility and visible risk."},
                {"name": "Dtotal", "expression": {"formula": "Dregular + Dconscious"}, "description": "Total demand."},
            ],
            "payoff_components": [
                {"id": "buyer_margin", "player_id": "B", "expression": {"formula": "(p - cR*xR - cK*xK) * Dtotal"}, "component_type": "profit", "applies_to_decision_stage": 2},
                {"id": "expected_penalty", "player_id": "B", "expression": {"formula": "-F * tau * rho * xK"}, "component_type": "cost", "applies_to_decision_stage": 1},
                {"id": "responsible_supplier_profit", "player_id": "RS", "expression": {"formula": "cR * xR * Dtotal"}, "component_type": "revenue"},
                {"id": "risky_supplier_profit", "player_id": "KS", "expression": {"formula": "cK * xK * Dtotal"}, "component_type": "revenue"},
            ],
            "contract_terms": [],
            "scenario_axes": [
                {"id": "transparency", "values": [{"id": "low"}, {"id": "moderate"}, {"id": "high"}]},
                {"id": "consumer_pressure", "values": [{"id": "moderate"}, {"id": "high"}, {"id": "large_segment"}]},
                {"id": "enforcement", "values": [{"id": "weak"}, {"id": "moderate"}, {"id": "strong"}]},
            ],
            "scenario_overview": scenarios,
        },
        "clarification_questions": [],
        "field_confidence": [
            {"field_path": "basics.game_type", "confidence": "inferred", "note": "The demo abstracts the sourcing decision as a Stackelberg-style buyer optimization."}
        ],
        "implicit_assumptions": [
            "This is a synthetic demo inspired by responsible-sourcing problems, not a reproduction of a copyrighted paper.",
            "Suppliers are represented through sourcing costs and payoff accounting rather than separate strategic decisions.",
        ],
    }


def _stage2_data() -> dict[str, object]:
    details = []
    for sid, _desc, _axis, *_rest in SCENARIOS:
        details.append(
            {
                "scenario_id": sid,
                "active_demands": ["Dregular", "Dconscious", "Dtotal"],
                "active_payoff_components": {
                    "B": ["buyer_margin", "expected_penalty"],
                    "RS": ["responsible_supplier_profit"],
                    "KS": ["risky_supplier_profit"],
                },
                "active_contract_terms": [],
                "notes": "Precomputed demo scenario.",
            }
        )
    scenario_ids = [sid for sid, *_rest in SCENARIOS]
    return {
        "procedure": {
            "method": "stackelberg_backward_induction",
            "description": "Enumerate sourcing strategies, optimize price/allocation, then compare buyer payoffs across scenarios.",
            "refinement": "Buyer selects the profit-maximizing feasible sourcing strategy.",
            "solving_stages": [
                {
                    "stage_id": "strategy_enumeration",
                    "description": "Enumerate low-cost, dual, responsible-niche, and responsible-mass-market sourcing strategies.",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "enumeration",
                    "deciders": [{"player_id": "B", "decision_vars": ["s"]}],
                    "profit_function_assignments": {"B": ["buyer_margin", "expected_penalty"]},
                    "uses_demands": ["Dregular", "Dconscious", "Dtotal"],
                    "expectation_handling": "before_foc",
                    "solver_hint": "Evaluate buyer payoff under each candidate sourcing strategy.",
                },
                {
                    "stage_id": "allocation_optimization",
                    "description": "For each sourcing strategy, choose responsible and risky sourcing shares.",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "optimization",
                    "deciders": [{"player_id": "B", "decision_vars": ["xR", "xK"]}],
                    "profit_function_assignments": {"B": ["buyer_margin", "expected_penalty"]},
                    "uses_demands": ["Dregular", "Dconscious", "Dtotal"],
                    "expectation_handling": "before_foc",
                    "uses_previous_stage_results": ["strategy_enumeration"],
                    "solver_hint": "Optimize allocation subject to xR + xK <= 1 and strategy-specific restrictions.",
                },
                {
                    "stage_id": "pricing_optimization",
                    "description": "For each candidate strategy, optimize the buyer's retail price.",
                    "corresponds_to_decision_stage": 2,
                    "solve_type": "optimization",
                    "deciders": [{"player_id": "B", "decision_vars": ["p"]}],
                    "profit_function_assignments": {"B": ["buyer_margin", "expected_penalty"]},
                    "uses_demands": ["Dregular", "Dconscious", "Dtotal"],
                    "expectation_handling": "before_foc",
                    "uses_previous_stage_results": ["strategy_enumeration", "allocation_optimization"],
                    "solver_hint": "Maximize buyer expected payoff subject to nonnegative demand.",
                },
                {
                    "stage_id": "policy_comparison",
                    "description": "Compare optimal sourcing strategies and payoffs across policy scenarios.",
                    "corresponds_to_decision_stage": 1,
                    "solve_type": "enumeration",
                    "deciders": [{"player_id": "B", "decision_vars": ["s"]}],
                    "profit_function_assignments": {"B": ["buyer_margin", "expected_penalty"], "RS": ["responsible_supplier_profit"], "KS": ["risky_supplier_profit"]},
                    "uses_demands": ["Dtotal"],
                    "expectation_handling": "not_needed",
                    "uses_previous_stage_results": ["strategy_enumeration", "allocation_optimization", "pricing_optimization"],
                    "solver_hint": "Rank scenarios by buyer profit, responsible sourcing share, and risky exposure.",
                },
            ],
            "scenario_details": details,
        },
        "research_questions": [
            {"id": "rq_strategy", "question": "When does the buyer choose responsible sourcing rather than risky low-cost sourcing?", "question_type": "optimal_choice", "target_scenarios": scenario_ids, "target_players": ["B"], "target_metrics": ["chosen_strategy"]},
            {"id": "rq_policy", "question": "Do transparency, consumer pressure, or penalties most reliably increase responsible sourcing?", "question_type": "comparative_statics", "target_scenarios": scenario_ids, "target_players": ["B"], "target_metrics": ["xR", "xK", "expected_pricing_profits"]},
        ],
        "basics_revision_suggestions": [],
        "clarification_questions": [],
        "field_confidence": [
            {"field_path": "procedure.solving_stages", "confidence": "inferred", "note": "The demo uses a simplified enumeration and optimization workflow."}
        ],
    }


def _phase1_manifest() -> dict[str, object]:
    return {
        "generator": "precomputed-demo-v1",
        "title": "Synthetic Responsible Sourcing Game",
        "method": "stackelberg_backward_induction",
        "options": {"solve_mode": "precomputed", "solve_timeout_seconds": 0, "simplify_timeout_seconds": 0},
        "scenario_count": len(SCENARIOS),
        "scenarios": [
            {"scenario_id": sid, "script": f"scenarios/{sid}.wl", "result": f"scenarios/{sid}_result.json"}
            for sid, *_rest in SCENARIOS
        ],
        "run_all": "run_all.wl",
    }


def _write_phase1_scripts() -> None:
    run_lines = ["(* Precomputed demo script index. *)"]
    for sid, desc, _axis, *_rest in SCENARIOS:
        script = (
            "(* Synthetic Responsible Sourcing Game: precomputed demo script. *)\n"
            f"(* Scenario: {sid} - {desc} *)\n"
            "(* Online demo mode does not run WolframScript. The matching result JSON is precomputed. *)\n"
        )
        (SCENARIO_DIR / f"{sid}.wl").write_text(script, encoding="utf-8")
        run_lines.append(f'Print["Demo scenario {sid} is precomputed."];')
        (LOG_DIR / f"{sid}.stdout.txt").write_text(
            f"Demo mode loaded precomputed result for {sid}.\n",
            encoding="utf-8",
        )
        (LOG_DIR / f"{sid}.stderr.txt").write_text("", encoding="utf-8")
    (PHASE1_DIR / "run_all.wl").write_text("\n".join(run_lines) + "\n", encoding="utf-8")


def _phase1_results() -> dict[str, object]:
    results: dict[str, object] = {}
    for sid, _desc, axis, strategy, equilibrium, payoffs, insights in SCENARIOS:
        result = {
            "scenario_id": sid,
            "status": "success",
            "failed_at": "",
            "warnings": [],
            "managerial_insights": insights,
            "stage_results": {
                "strategy_enumeration": {
                    "solve_type": "enumeration",
                    "chosen_strategy": strategy,
                    "candidate_strategies": ["low_cost_sourcing", "dual_sourcing", "responsible_niche", "responsible_mass_market"],
                    "strategy_profiles": [
                        {"strategy": strategy, "selected": True, "reason": "highest buyer payoff in this precomputed scenario"}
                    ],
                    "pure_nash_conditions": [],
                },
                "allocation_optimization": {
                    "solve_type": "optimization",
                    "decision_variables": ["xR", "xK"],
                    "objectives": {"B": "maximize expected buyer payoff over sourcing shares"},
                    "candidate_rules": {"xR": equilibrium["xR"], "xK": equilibrium["xK"]},
                },
                "pricing_optimization": {
                    "solve_type": "optimization",
                    "decision_variables": ["p"],
                    "objectives": {"B": "maximize expected buyer payoff over retail price"},
                    "candidate_rules": {"p": equilibrium["p"]},
                },
                "policy_comparison": {
                    "solve_type": "enumeration",
                    "scenario_axes": axis,
                    "responsible_share": equilibrium["xR"],
                    "risky_share": equilibrium["xK"],
                    "managerial_insights": insights,
                    "strategy_profiles": [
                        {"scenario": sid, "strategy": strategy, "responsible_share": equilibrium["xR"], "risky_share": equilibrium["xK"]}
                    ],
                    "pure_nash_conditions": [],
                },
            },
            "equilibrium": {"strategy": strategy, **equilibrium},
            "subscribed_players": [],
            "expected_pricing_profits": payoffs,
            "contract_terms": {},
            "phase1_options": {"solve_mode": "precomputed-demo"},
        }
        result_path = SCENARIO_DIR / f"{sid}_result.json"
        _write_json(result_path, result)
        results[sid] = result
    return results


def _mechanism_summaries(all_results: dict[str, object]) -> dict[str, object]:
    responsible_best = [
        sid
        for sid, result in all_results.items()
        if isinstance(result, dict)
        and result.get("equilibrium", {}).get("strategy") == "responsible_mass_market"
    ]
    return {
        "status": "ok",
        "handlers": {
            "responsible_sourcing": {
                "title": "Responsible Sourcing Comparison",
                "responsible_mass_market_scenarios": responsible_best,
                "summary": "Transparency, large socially conscious demand, and strong penalties all support responsible mass-market sourcing in this demo.",
            }
        },
        "manifest_title": "Synthetic Responsible Sourcing Game",
    }


def _write_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
