"""Phase 1 workflow: finalized ModelSpec -> Wolfram scripts.

This file uses VS Code/Jupyter ``# %%`` cells. Run cells one by one.
"""

# %%
from pathlib import Path

from agent.phase1 import (
    WolframGenerationOptions,
    generate_wolfram_scripts,
    load_modelspec,
    run_wolfram_scripts,
    write_phase1_diagnostics,
)


# %% [markdown]
# ## 1. Configure paths

# %%
MODELSPEC_PATH = Path("output/qwen_phase0_finalize_acceptance/modelspec_final.yaml")
OUTPUT_DIR = Path("output/phase1_wolfram")


# %% [markdown]
# ## 2. Load and validate ModelSpec

# %%
spec = load_modelspec(MODELSPEC_PATH)
print(spec.basics.title)
print(f"scenarios: {len(spec.procedure.scenario_details)}")
print(f"method: {spec.procedure.method.value}")


# %% [markdown]
# ## 3. Choose solver options

# %%
options = WolframGenerationOptions(
    solve_timeout_seconds=120,
    simplify_timeout_seconds=30,
    solve_mode="symbolic",
    parameter_values={},
)

# For difficult SB scenarios, switch to semi-numeric or numeric mode:
# options = WolframGenerationOptions(
#     solve_timeout_seconds=60,
#     simplify_timeout_seconds=15,
#     solve_mode="semi_numeric",
#     parameter_values={
#         "a_H": 10,
#         "a_L": 5,
#         "beta": "1/2",
#         "alpha": "1/5",
#         "theta": "3/5",
#         "r": 1,
#         "phi": 2,
#     },
# )


# %% [markdown]
# ## 4. Generate Wolfram scripts

# %%
result = generate_wolfram_scripts(spec, OUTPUT_DIR, options=options)

print(f"Output directory: {result.output_dir}")
print(f"Runner: {result.run_all_path}")
print(f"Manifest: {result.manifest_path}")
print(f"Scenario scripts: {len(result.scenario_scripts)}")
for scenario_id, path in result.scenario_scripts.items():
    print(f"  {scenario_id}: {path}")


# %% [markdown]
# ## 5. Run with Python Phase 1.5 runner

# %%
# This runs each scenario with wolframscript, writes stdout/stderr logs,
# aggregates result JSON files, and creates phase1_report.md.
run_result = run_wolfram_scripts(
    OUTPUT_DIR,
    timeout_seconds=180,
)

print(f"Run summary: {run_result.run_summary_path}")
print(f"Diagnostics: {run_result.diagnostics_path}")
print(f"Report: {run_result.report_path}")
print(run_result.diagnostics.counts)


# %% [markdown]
# ## 6. Diagnose existing results without rerunning

# %%
diagnostics = write_phase1_diagnostics(OUTPUT_DIR)
print(diagnostics.counts)


# %% [markdown]
# ## 7. Or run in Wolfram/Mathematica manually
#
# Open Mathematica or wolframscript and run:
#
# ```wolfram
# Get["output/phase1_wolfram/run_all.wl"]
# ```
#
# Each scenario writes ``scenarios/<scenario_id>_result.json`` and the runner
# writes ``all_results.json``.
