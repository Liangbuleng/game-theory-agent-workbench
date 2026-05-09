"""Information-fee mechanism handler for Phase 1.5.

This module is intentionally optional. It only applies to result sets that look
like cross-scenario information sharing / participation-fee mechanisms: scenario
results must contain expected profits, contract terms, and subscriber profiles.
"""

from __future__ import annotations

import ast
from datetime import datetime, timezone
from fractions import Fraction
from typing import Iterable


MECHANISM_ID = "information_fee"
MECHANISM_TITLE = "Information Fee"


def can_handle_information_fee(all_results: dict[str, object]) -> bool:
    usable = _usable_fee_results(all_results)
    if len(usable) < 2:
        return False
    has_fee_terms = any(_contract_payers(result) for result in usable.values())
    has_profile_variation = len(
        {tuple(_subscribers(result)) for result in usable.values()}
    ) > 1
    has_baseline = any(not _subscribers(result) for result in usable.values())
    return has_fee_terms and has_profile_variation and has_baseline


def build_information_fee_summary(
    all_results: dict[str, object],
) -> dict[str, object]:
    """Build cross-scenario fee boundary candidates from expected profits."""

    usable = _usable_fee_results(all_results)
    groups = _group_fee_scenarios(usable)
    output_groups: dict[str, object] = {}
    for group_id, scenario_ids in groups.items():
        baseline_id = _select_fee_baseline(scenario_ids, usable)
        if baseline_id is None:
            continue
        baseline = usable[baseline_id]
        baseline_profits = _expected_profits(baseline)
        profiles = {}
        for scenario_id in scenario_ids:
            result = usable[scenario_id]
            subscribers = _subscribers(result)
            expected_profits = _expected_profits(result)
            information_values = {
                player_id: _difference_expr(
                    expected_profits.get(player_id, "0"),
                    baseline_profits.get(player_id, "0"),
                )
                for player_id in sorted(_contract_payers(result))
            }
            feasible_conditions = _fee_feasible_conditions(
                result=result,
                subscribers=subscribers,
                information_values=information_values,
            )
            candidate_t = _fee_candidate_t(subscribers, information_values)
            candidate_t_value = _try_eval_expr(candidate_t)
            feasibility = _fee_profile_feasibility(
                result=result,
                subscribers=subscribers,
                information_values=information_values,
                candidate_t_value=candidate_t_value,
            )
            platform_objective = _platform_objective_expr(
                result=result,
                subscribers=subscribers,
                candidate_t=candidate_t,
            )
            platform_objective_value = _platform_objective_value(
                result=result,
                subscribers=subscribers,
                candidate_t_value=candidate_t_value,
            )
            profiles[scenario_id] = {
                "subscribers": subscribers,
                "expected_pricing_profits": expected_profits,
                "manufacturer_information_values": information_values,
                "feasible_T_conditions": feasible_conditions,
                "candidate_T": candidate_t,
                "candidate_T_value": _format_fraction(candidate_t_value),
                "feasibility": feasibility,
                "platform_objective": platform_objective,
                "platform_objective_value": _format_fraction(
                    platform_objective_value
                ),
                "source_status": result.get("status", ""),
                "source_warnings": result.get("warnings", []),
            }

        comparison = _compare_fee_profiles(profiles)
        output_groups[group_id] = {
            "baseline": baseline_id,
            "profiles": profiles,
            "comparison": comparison,
            "comparison_candidates": [
                {
                    "scenario_id": scenario_id,
                    "objective": profile["platform_objective"],
                    "objective_value": profile["platform_objective_value"],
                    "candidate_T": profile["candidate_T"],
                    "candidate_T_value": profile["candidate_T_value"],
                    "feasibility": profile["feasibility"],
                    "conditions": profile["feasible_T_conditions"],
                }
                for scenario_id, profile in profiles.items()
            ],
            "note": (
                "Candidate T values are boundary candidates from participation "
                "constraints. Compare platform_objective expressions under the "
                "listed feasible_T_conditions."
            ),
        }

    return {
        "mechanism_id": MECHANISM_ID,
        "title": MECHANISM_TITLE,
        "generated_at": _now_iso(),
        "status": "available" if output_groups else "not_applicable",
        "detector": {
            "matched": bool(output_groups),
            "reason": (
                "expected profits, contract terms, subscriber variation, and "
                "baseline profiles were detected"
                if output_groups
                else "required information-fee result structure was not detected"
            ),
        },
        "groups": output_groups,
    }


def render_information_fee_report(summary: dict[str, object]) -> list[str]:
    """Render the optional information-fee report section."""

    lines: list[str] = []
    emit = lines.append
    if not summary.get("groups"):
        return lines

    emit("## Mechanism: Information Fee")
    emit("")
    emit(
        "This optional mechanism handler treats fee design as a cross-scenario "
        "boundary problem using expected profits from finished scenario runs."
    )
    emit("")
    groups = summary.get("groups", {})
    if isinstance(groups, dict):
        for group_id, group_data in groups.items():
            if not isinstance(group_data, dict):
                continue
            emit(f"### {group_id}")
            emit("")
            emit(f"- Baseline: `{group_data.get('baseline', '')}`")
            comparison = group_data.get("comparison", {})
            if isinstance(comparison, dict):
                emit(f"- Comparison status: `{comparison.get('status', '')}`")
                if comparison.get("best_profile"):
                    emit(
                        f"- Best profile: `{comparison.get('best_profile')}` "
                        f"with objective `{comparison.get('best_objective_value', '')}` "
                        f"and candidate T `{comparison.get('best_candidate_T', '')}`"
                    )
            emit("")
            emit("| Scenario | Feasible | Subscribers | Feasible T | Candidate T | Objective Value | Platform Objective |")
            emit("|---|---:|---|---|---|---:|---|")
            profiles = group_data.get("profiles", {})
            if isinstance(profiles, dict):
                for scenario_id, profile in profiles.items():
                    if not isinstance(profile, dict):
                        continue
                    subscribers = ", ".join(profile.get("subscribers", []))
                    conditions = "; ".join(profile.get("feasible_T_conditions", []))
                    candidate = profile.get("candidate_T", "")
                    feasibility = profile.get("feasibility", {})
                    feasible_status = (
                        feasibility.get("status", "")
                        if isinstance(feasibility, dict)
                        else ""
                    )
                    objective_value = profile.get("platform_objective_value", "")
                    objective = profile.get("platform_objective", "")
                    emit(
                        f"| {scenario_id} | {feasible_status} | "
                        f"{subscribers or 'none'} | "
                        f"{conditions or 'none'} | {candidate or 'none'} | "
                        f"{objective_value or 'unknown'} | {objective} |"
                    )
            emit("")
    return lines


def _usable_fee_results(
    all_results: dict[str, object],
) -> dict[str, dict[str, object]]:
    return {
        scenario_id: result
        for scenario_id, result in all_results.items()
        if isinstance(result, dict)
        and result.get("expected_pricing_profits")
        and result.get("contract_terms") is not None
    }


def _group_fee_scenarios(
    results: dict[str, dict[str, object]],
) -> dict[str, list[str]]:
    groups: dict[str, list[str]] = {}
    for scenario_id in results:
        group_id = _fee_group_id(scenario_id)
        groups.setdefault(group_id, []).append(scenario_id)
    return {
        group_id: sorted(
            scenario_ids,
            key=lambda item: (len(_subscribers(results[item])), item),
        )
        for group_id, scenario_ids in groups.items()
    }


def _fee_group_id(scenario_id: str) -> str:
    lowered = scenario_id.lower()
    if lowered.endswith("_no_sb"):
        return "no_sb"
    if lowered.endswith("_sb"):
        return "sb"
    parts = scenario_id.rsplit("_", 1)
    if len(parts) == 2:
        return parts[1]
    return "all"


def _select_fee_baseline(
    scenario_ids: list[str],
    results: dict[str, dict[str, object]],
) -> str | None:
    no_subscriber = [
        scenario_id
        for scenario_id in scenario_ids
        if not _subscribers(results[scenario_id])
    ]
    if no_subscriber:
        return sorted(no_subscriber)[0]
    return scenario_ids[0] if scenario_ids else None


def _subscribers(result: dict[str, object]) -> list[str]:
    subscribers = result.get("subscribed_players", [])
    if isinstance(subscribers, list):
        return sorted(str(item) for item in subscribers)

    informed_players = result.get("informed_players", [])
    if isinstance(informed_players, list):
        return sorted(str(item) for item in informed_players)

    mechanism_profile = result.get("scenario_mechanism_profile", {})
    if isinstance(mechanism_profile, dict):
        profile_informed = mechanism_profile.get("informed_players", [])
        if isinstance(profile_informed, list):
            return sorted(str(item) for item in profile_informed)

    inferred = []
    contract_terms = result.get("contract_terms", {})
    if isinstance(contract_terms, dict):
        for term in contract_terms.values():
            if isinstance(term, dict) and term.get("active_in_scenario"):
                payer = term.get("payer")
                if payer:
                    inferred.append(str(payer))
    return sorted(set(inferred))


def _expected_profits(result: dict[str, object]) -> dict[str, str]:
    profits = result.get("expected_pricing_profits", {})
    if not isinstance(profits, dict):
        return {}
    return {str(player): str(value) for player, value in profits.items()}


def _contract_payers(result: dict[str, object]) -> set[str]:
    payers = set()
    contract_terms = result.get("contract_terms", {})
    if isinstance(contract_terms, dict):
        for term in contract_terms.values():
            if isinstance(term, dict) and term.get("payer"):
                payers.add(str(term["payer"]))
    return payers


def _active_fee_terms(
    result: dict[str, object],
    payer_id: str,
) -> list[dict[str, object]]:
    contract_terms = result.get("contract_terms", {})
    if not isinstance(contract_terms, dict):
        return []
    terms = []
    for term in contract_terms.values():
        if not isinstance(term, dict):
            continue
        if str(term.get("payer", "")) == payer_id and term.get("active_in_scenario"):
            terms.append(term)
    return terms


def _fee_variable_expr(
    result: dict[str, object],
    payer_id: str,
) -> str:
    terms = _active_fee_terms(result, payer_id)
    if not terms:
        return "T"
    amounts = [str(term.get("amount", "T")) for term in terms]
    return " + ".join(amounts) if len(amounts) > 1 else amounts[0]


def _fee_feasible_conditions(
    *,
    result: dict[str, object],
    subscribers: list[str],
    information_values: dict[str, str],
) -> list[str]:
    conditions = ["T >= 0"]
    payer_ids = sorted(_contract_payers(result))
    for payer_id in payer_ids:
        delta = information_values.get(payer_id, "0")
        fee_expr = _fee_variable_expr(result, payer_id)
        if payer_id in subscribers:
            conditions.append(f"{fee_expr} <= {delta}")
        else:
            conditions.append(f"{fee_expr} >= {delta}")
    return _dedupe(conditions)


def _fee_profile_feasibility(
    *,
    result: dict[str, object],
    subscribers: list[str],
    information_values: dict[str, str],
    candidate_t_value: Fraction | None,
) -> dict[str, object]:
    notes: list[str] = []
    unknowns: list[str] = []
    failures: list[str] = []
    subscriber_set = set(subscribers)
    payer_ids = sorted(_contract_payers(result))

    if candidate_t_value is None:
        unknowns.append("candidate_T could not be evaluated")
    elif candidate_t_value < 0:
        failures.append("candidate_T is negative")

    for payer_id in payer_ids:
        delta_expr = information_values.get(payer_id, "0")
        delta_value = _try_eval_expr(delta_expr)
        if delta_value is None:
            unknowns.append(f"information value for {payer_id} is symbolic")
            continue

        if payer_id in subscriber_set:
            if delta_value < 0:
                failures.append(
                    f"{payer_id} has negative information value {delta_expr}"
                )
            if candidate_t_value is not None and candidate_t_value > delta_value:
                failures.append(
                    f"candidate_T exceeds {payer_id}'s willingness to pay"
                )
        elif candidate_t_value is not None and candidate_t_value < delta_value:
            failures.append(
                f"candidate_T would not deter non-subscriber {payer_id}"
            )

    if failures:
        status = "infeasible"
    elif unknowns:
        status = "unknown"
    else:
        status = "feasible"

    if not subscribers:
        notes.append(
            "no-fee profile: platform objective is independent of T; choose any T satisfying deterrence conditions"
        )

    return {
        "status": status,
        "failures": failures,
        "unknowns": unknowns,
        "notes": notes,
    }


def _fee_candidate_t(
    subscribers: list[str],
    information_values: dict[str, str],
) -> str:
    if not subscribers:
        bounds = list(information_values.values())
        if not bounds:
            return "0"
        return "Max[0, " + ", ".join(bounds) + "]"
    bounds = [
        information_values.get(player_id, "0")
        for player_id in subscribers
    ]
    if len(bounds) == 1:
        return bounds[0]
    return "Min[" + ", ".join(bounds) + "]"


def _compare_fee_profiles(
    profiles: dict[str, dict[str, object]],
) -> dict[str, object]:
    ranking = []
    unknown_profiles = []
    infeasible_profiles = []
    for scenario_id, profile in profiles.items():
        feasibility = profile.get("feasibility", {})
        feasible_status = (
            feasibility.get("status", "unknown")
            if isinstance(feasibility, dict)
            else "unknown"
        )
        objective_value = _try_eval_expr(str(profile.get("platform_objective_value", "")))
        if objective_value is None:
            objective_value = _try_eval_expr(str(profile.get("platform_objective", "")))

        entry = {
            "scenario_id": scenario_id,
            "feasibility": feasible_status,
            "objective_value": _format_fraction(objective_value),
            "candidate_T": profile.get("candidate_T", ""),
            "candidate_T_value": profile.get("candidate_T_value", ""),
        }
        if feasible_status == "infeasible":
            infeasible_profiles.append(entry)
            continue
        if feasible_status == "unknown" or objective_value is None:
            unknown_profiles.append(entry)
            continue
        ranking.append((scenario_id, objective_value, entry))

    ranking.sort(key=lambda item: item[1], reverse=True)
    ranked_entries = [entry for _, _, entry in ranking]
    if ranking:
        best_scenario, best_value, best_entry = ranking[0]
        return {
            "status": "ranked",
            "best_profile": best_scenario,
            "best_objective_value": _format_fraction(best_value),
            "best_candidate_T": best_entry.get("candidate_T", ""),
            "ranking": ranked_entries,
            "unknown_profiles": unknown_profiles,
            "infeasible_profiles": infeasible_profiles,
        }
    if unknown_profiles:
        return {
            "status": "unknown",
            "best_profile": None,
            "ranking": [],
            "unknown_profiles": unknown_profiles,
            "infeasible_profiles": infeasible_profiles,
        }
    return {
        "status": "no_feasible_profile",
        "best_profile": None,
        "ranking": [],
        "unknown_profiles": unknown_profiles,
        "infeasible_profiles": infeasible_profiles,
    }


def _platform_objective_expr(
    *,
    result: dict[str, object],
    subscribers: list[str],
    candidate_t: str,
) -> str:
    profits = _expected_profits(result)
    platform_id = _infer_platform_id(result)
    base_profit = profits.get(platform_id, "0")
    if not subscribers:
        return base_profit
    fee_terms = []
    for subscriber in subscribers:
        for term in _active_fee_terms(result, subscriber):
            if str(term.get("payee", "")) == platform_id:
                fee_terms.append(str(term.get("amount", "T")))
    fee_expr = " + ".join(fee_terms) if fee_terms else f"{len(subscribers)} * T"
    return f"({base_profit}) + ({fee_expr}) /. T -> ({candidate_t})"


def _platform_objective_value(
    *,
    result: dict[str, object],
    subscribers: list[str],
    candidate_t_value: Fraction | None,
) -> Fraction | None:
    profits = _expected_profits(result)
    platform_id = _infer_platform_id(result)
    base_value = _try_eval_expr(profits.get(platform_id, "0"))
    if base_value is None:
        return None
    if not subscribers:
        return base_value
    if candidate_t_value is None:
        return None

    total_fee = Fraction(0)
    for subscriber in subscribers:
        for term in _active_fee_terms(result, subscriber):
            if str(term.get("payee", "")) != platform_id:
                continue
            amount = str(term.get("amount", "T")).strip()
            if amount == "T":
                total_fee += candidate_t_value
                continue
            amount_value = _try_eval_expr(amount)
            if amount_value is None:
                return None
            total_fee += amount_value
    if total_fee == 0:
        total_fee = len(subscribers) * candidate_t_value
    return base_value + total_fee


def _infer_platform_id(result: dict[str, object]) -> str:
    payee_counts: dict[str, int] = {}
    contract_terms = result.get("contract_terms", {})
    if isinstance(contract_terms, dict):
        for term in contract_terms.values():
            if isinstance(term, dict) and term.get("payee"):
                payee = str(term["payee"])
                payee_counts[payee] = payee_counts.get(payee, 0) + 1
    if payee_counts:
        return max(payee_counts.items(), key=lambda item: item[1])[0]
    profits = _expected_profits(result)
    if "R" in profits:
        return "R"
    return next(iter(profits), "R")


def _difference_expr(left: str, right: str) -> str:
    if left == right:
        return "0"
    return f"({left}) - ({right})"


def _try_eval_expr(expr: object) -> Fraction | None:
    text = str(expr).strip()
    if not text:
        return None
    if text.lower() in {"none", "unknown"}:
        return None
    try:
        translated = (
            text.replace("[", "(")
            .replace("]", ")")
            .replace("Min", "min")
            .replace("Max", "max")
        )
        tree = ast.parse(translated, mode="eval")
        return _eval_fraction_ast(tree.body)
    except (SyntaxError, ValueError, TypeError, ZeroDivisionError):
        return None


def _eval_fraction_ast(node: ast.AST) -> Fraction:
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool):
            raise ValueError("boolean constants are not numeric expressions")
        if isinstance(value, int):
            return Fraction(value)
        if isinstance(value, float):
            return Fraction(str(value))
        raise ValueError("unsupported constant")
    if isinstance(node, ast.UnaryOp):
        operand = _eval_fraction_ast(node.operand)
        if isinstance(node.op, ast.USub):
            return -operand
        if isinstance(node.op, ast.UAdd):
            return operand
        raise ValueError("unsupported unary operator")
    if isinstance(node, ast.BinOp):
        left = _eval_fraction_ast(node.left)
        right = _eval_fraction_ast(node.right)
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.Div):
            return left / right
        raise ValueError("unsupported binary operator")
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
        values = [_eval_fraction_ast(arg) for arg in node.args]
        if not values:
            raise ValueError("empty call")
        if node.func.id == "min":
            return min(values)
        if node.func.id == "max":
            return max(values)
    raise ValueError("unsupported expression")


def _format_fraction(value: Fraction | None) -> str | None:
    if value is None:
        return None
    if value.denominator == 1:
        return str(value.numerator)
    return f"{value.numerator}/{value.denominator}"


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
