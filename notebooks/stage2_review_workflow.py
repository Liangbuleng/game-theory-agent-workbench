"""Stage 2 + Stage 2.5 review workflow template.

This file uses VS Code/Jupyter ``# %%`` cells. Run cells one by one:

1. load confirmed Stage 1
2. parse_stage2
3. export review JSONC
4. revise from feedback or from edited JSONC
5. inspect diff
6. confirm Stage 2
"""

# %%
from pathlib import Path

from agent.llm import LLMClient
from agent.parser import Parser, Stage1Output, Stage2Output


# %% [markdown]
# ## 1. Configure paths
#
# ``STAGE1_FINAL_PATH`` should point to a confirmed Stage 1 JSON file.
# ``PAPER_PATH`` is optional but recommended; Stage 2 uses it only as auxiliary
# evidence for solving details and research questions.

# %%
STAGE1_FINAL_PATH = Path("output/qwen_sequence_upgrade_acceptance/stage1_final.json")
PAPER_PATH = Path("output/model_pandoc.md")
OUTPUT_DIR = Path("output/stage2_review_workflow")

# Set PROVIDER to None to use agent_config.yaml default_provider.
PROVIDER = "qwen"

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

llm_client = LLMClient(provider=PROVIDER) if PROVIDER else None
parser = Parser(
    llm_client=llm_client,
    auto_save=False,
    llm_stream=True,
    llm_log=True,
)


# %% [markdown]
# ## 2. Load confirmed Stage 1

# %%
stage1 = Stage1Output.model_validate_json(
    STAGE1_FINAL_PATH.read_text(encoding="utf-8")
)
stage1.assert_valid()

print(stage1.summary_markdown())


# %% [markdown]
# ## 3. Stage 2 parse
#
# This calls the LLM and saves ``stage2_output_v1.json``.

# %%
RUN_PARSE_STAGE2 = True

if RUN_PARSE_STAGE2:
    stage2_v1 = parser.parse_stage2(
        stage1,
        paper_path=PAPER_PATH,
        output_dir=OUTPUT_DIR,
        save=True,
    )
else:
    existing_stage2_path = OUTPUT_DIR / "stage2_output_v1.json"
    stage2_v1 = Stage2Output.model_validate_json(
        existing_stage2_path.read_text(encoding="utf-8")
    )
    stage2_v1.assert_valid(stage1.basics)

print(stage2_v1.summary_markdown())


# %% [markdown]
# ## 4. Export review JSONC
#
# This file is for human review/editing. It contains comments, so it is not the
# canonical machine artifact. The canonical artifact is still strict JSON.

# %%
review_jsonc_path = OUTPUT_DIR / "stage2_output_v1.review.jsonc"
parser.export_stage2_review_jsonc(stage2_v1, review_jsonc_path)
print(f"Review JSONC saved to: {review_jsonc_path}")


# %% [markdown]
# ## 5A. Small revision: edit JSONC directly
#
# Use this when the change is local and precise. Edit
# ``stage2_output_v1.review.jsonc`` by hand, then run this cell. This path does
# not call the LLM; it only parses and validates the edited JSONC against the
# confirmed GameBasics.

# %%
RUN_JSONC_REVISION = False

if RUN_JSONC_REVISION:
    stage2_v2 = parser.stage2_revise_from_json(
        review_jsonc_path,
        stage1,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage2_diff_markdown(stage2_v1, stage2_v2))
else:
    stage2_v2 = stage2_v1
    print("Skipped JSONC revision.")


# %% [markdown]
# ## 5B. Large revision: natural-language feedback
#
# Use this when the change is structural or easier to state in natural language.
# ``answers`` should answer Stage 2 clarification question ids such as ``cq1``.
# The LLM returns a complete new ``Stage2Output``; it is then validated and
# repaired if needed.

# %%
RUN_FEEDBACK_REVISION = False

answers = {
    # "cq1": "Use mixed_by_scenario for pricing stages whose information differs by scenario.",
}

free_feedback = """
Revise only Stage 2 solving procedure and research-question fields.
Keep confirmed GameBasics unchanged.
"""

if RUN_FEEDBACK_REVISION:
    stage2_v2 = parser.stage2_revise_from_feedback(
        previous=stage2_v1,
        stage1=stage1,
        answers=answers,
        free_feedback=free_feedback,
        paper_path=PAPER_PATH,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage2_diff_markdown(stage2_v1, stage2_v2))
else:
    print("Skipped feedback revision.")


# %% [markdown]
# ## 6. Inspect revised output

# %%
print(stage2_v2.summary_markdown())

review_v2_path = OUTPUT_DIR / "stage2_output_v2.review.jsonc"
parser.export_stage2_review_jsonc(stage2_v2, review_v2_path)
print(f"Revised review JSONC saved to: {review_v2_path}")


# %% [markdown]
# ## 7. Confirm Stage 2
#
# Run this only after the Stage 2 output is accepted. This writes
# ``stage2_final.json``. The final ModelSpec builder should consume this file
# together with ``stage1_final.json``.

# %%
RUN_CONFIRM = False

if RUN_CONFIRM:
    final_path = parser.confirm_stage2(
        stage2_v2,
        basics=stage1.basics,
        output_dir=OUTPUT_DIR,
    )
    print(f"Confirmed Stage 2 saved to: {final_path}")
else:
    print("Skipped confirm_stage2.")


# %% [markdown]
# ## 8. Resume from an existing Stage 2 file
#
# If you already have a previous run, load it here and continue from step 4/5.

# %%
RUN_RESUME = False

if RUN_RESUME:
    existing_path = OUTPUT_DIR / "stage2_final.json"
    resumed = Stage2Output.model_validate_json(
        existing_path.read_text(encoding="utf-8")
    )
    resumed.assert_valid(stage1.basics)
    parser.export_stage2_review_jsonc(
        resumed,
        OUTPUT_DIR / "stage2_resumed.review.jsonc",
    )
    print(resumed.summary_markdown())
else:
    print("Skipped resume.")
