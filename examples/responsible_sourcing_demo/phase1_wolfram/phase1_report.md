# Phase 1.5 Wolfram Run Report

- Title: Synthetic Responsible Sourcing Game
- Method: stackelberg_backward_induction
- Output dir: `C:\Users\Lenovo\Desktop\game theory agent\game_theory_agent\examples\responsible_sourcing_demo\phase1_wolfram`
- Solve mode: `precomputed`
- Solve timeout: `0` seconds
- Simplify timeout: `0` seconds

## Summary

- total: 6
- ok: 6

## Executive Summary

6 of 6 scenarios produced usable result structures. The first usable scenario is `base_case` with equilibrium decisions strategy=dual_sourcing, p=1.32, xR=0.55, xK=0.45 and expected payoffs B=0.184, RS=0.071, KS=0.052. Scenarios requiring attention: 0.

## Scenario Outcome Table

| Scenario | Outcome | Meaning | Equilibrium | Payoffs | Subscriptions | Stages |
|---|---|---|---|---|---|---|
| base_case | ok | usable result | strategy=dual_sourcing, p=1.32, xR=0.55, xK=0.45 | B=0.184, RS=0.071, KS=0.052 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |
| high_transparency | ok | usable result | strategy=responsible_mass_market, p=1.44, xR=1.00, xK=0.00 | B=0.201, RS=0.118, KS=0 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |
| high_consumer_premium | ok | usable result | strategy=responsible_niche, p=1.58, xR=0.62, xK=0.00 | B=0.176, RS=0.096, KS=0 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |
| large_conscious_segment | ok | usable result | strategy=responsible_mass_market, p=1.39, xR=1.00, xK=0.00 | B=0.214, RS=0.122, KS=0 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |
| strong_penalty | ok | usable result | strategy=responsible_mass_market, p=1.37, xR=1.00, xK=0.00 | B=0.192, RS=0.111, KS=0 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |
| high_responsible_cost | ok | usable result | strategy=low_cost_sourcing, p=1.08, xR=0.00, xK=1.00 | B=0.167, RS=0, KS=0.083 | none | strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison |

## Equilibrium Decisions

| Scenario | strategy | p | xR | xK |
|---|---|---|---|---|
| base_case | dual_sourcing | 1.32 | 0.55 | 0.45 |
| high_transparency | responsible_mass_market | 1.44 | 1.00 | 0.00 |
| high_consumer_premium | responsible_niche | 1.58 | 0.62 | 0.00 |
| large_conscious_segment | responsible_mass_market | 1.39 | 1.00 | 0.00 |
| strong_penalty | responsible_mass_market | 1.37 | 1.00 | 0.00 |
| high_responsible_cost | low_cost_sourcing | 1.08 | 0.00 | 1.00 |

## Expected Payoffs

| Scenario | B | RS | KS |
|---|---|---|---|
| base_case | 0.184 | 0.071 | 0.052 |
| high_transparency | 0.201 | 0.118 | 0 |
| high_consumer_premium | 0.176 | 0.096 | 0 |
| large_conscious_segment | 0.214 | 0.122 | 0 |
| strong_penalty | 0.192 | 0.111 | 0 |
| high_responsible_cost | 0.167 | 0 | 0.083 |

## Scenario Result Cards

### base_case

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=dual_sourcing, p=1.32, xR=0.55, xK=0.45
- Expected payoffs: B=0.184, RS=0.071, KS=0.052
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_transparency

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=responsible_mass_market, p=1.44, xR=1.00, xK=0.00
- Expected payoffs: B=0.201, RS=0.118, KS=0
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_consumer_premium

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=responsible_niche, p=1.58, xR=0.62, xK=0.00
- Expected payoffs: B=0.176, RS=0.096, KS=0
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### large_conscious_segment

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=responsible_mass_market, p=1.39, xR=1.00, xK=0.00
- Expected payoffs: B=0.214, RS=0.122, KS=0
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### strong_penalty

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=responsible_mass_market, p=1.37, xR=1.00, xK=0.00
- Expected payoffs: B=0.192, RS=0.111, KS=0
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_responsible_cost

- Status: `ok`
- Meaning: usable result
- Equilibrium decisions: strategy=low_cost_sourcing, p=1.08, xR=0.00, xK=1.00
- Expected payoffs: B=0.167, RS=0, KS=0.083
- Subscribed players: none
- Solving stages: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison


## Raw Artifact Index

### base_case

- Result file: `scenarios\base_case_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_transparency

- Result file: `scenarios\high_transparency_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_consumer_premium

- Result file: `scenarios\high_consumer_premium_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### large_conscious_segment

- Result file: `scenarios\large_conscious_segment_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### strong_penalty

- Result file: `scenarios\strong_penalty_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison

### high_responsible_cost

- Result file: `scenarios\high_responsible_cost_result.json`
- Process status: ``
- Return code: `None`
- Timed out: `False`
- Result status: `success`
- Stage result keys: strategy_enumeration, allocation_optimization, pricing_optimization, policy_comparison
