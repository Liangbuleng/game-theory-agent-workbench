"""Stage 1 + Stage 1.5 review workflow template.

This file uses VS Code/Jupyter ``# %%`` cells. Run cells one by one:

1. parse_stage1
2. export review JSONC
3. revise from feedback or from edited JSONC
4. inspect diff
5. confirm Stage 1
"""

# %%
from pathlib import Path

from agent.llm import LLMClient
from agent.parser import Parser, Stage1Output


# %% [markdown]
# ## 1. Configure paths
#
# Edit these paths for your paper/model. ``PAPER_PATH`` should point to a text
# or markdown file. PDF/docx should be preprocessed to markdown before Stage 1.

# %%
PAPER_PATH = Path("output/model_pandoc.md")
OUTPUT_DIR = Path("output/stage1_review_workflow")

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
# ## 2. Stage 1 parse
#
# This calls the LLM and saves ``stage1_output_v1.json``.

# %%
stage1_v1 = parser.parse_stage1(
    PAPER_PATH,
    output_dir=OUTPUT_DIR,
    save=True,
)

print(stage1_v1.summary_markdown())


# %% [markdown]
# ## 3. Export review JSONC
#
# This file is for human review/editing. It contains comments, so it is not the
# canonical machine artifact. The canonical artifact is still strict JSON.

# %%
review_jsonc_path = OUTPUT_DIR / "stage1_output_v1.review.jsonc"
parser.export_stage1_review_jsonc(stage1_v1, review_jsonc_path)
print(f"Review JSONC saved to: {review_jsonc_path}")


# %% [markdown]
# ## 4A. Small revision: edit JSONC directly
#
# Use this when the change is local and precise. Edit
# ``stage1_output_v1.review.jsonc`` by hand, then run this cell. This path does
# not call the LLM; it only parses and validates the edited JSONC.

# %%
RUN_JSONC_REVISION = False

if RUN_JSONC_REVISION:
    stage1_v2 = parser.stage1_revise_from_json(
        review_jsonc_path,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage1_diff_markdown(stage1_v1, stage1_v2))
else:
    stage1_v2 = stage1_v1
    print("Skipped JSONC revision.")


# %% [markdown]
# ## 4B. Large revision: natural-language feedback
#
# Use this when the change is structural or easier to state in natural language.
# ``answers`` should answer clarification question ids such as ``q1`` or ``CQ1``.
# The LLM returns a complete new ``Stage1Output``; it is then validated and
# repaired if needed.

# %%
RUN_FEEDBACK_REVISION = False

answers = {
    # "q1": "The store brand marginal cost is normalized to zero.",
    # "q2": "The information fee is a uniform fee T paid separately by each subscribing manufacturer.",
}

free_feedback = """
Revise only Stage 1 facts.
Keep correct existing fields unchanged.
"""

if RUN_FEEDBACK_REVISION:
    stage1_v2 = parser.stage1_revise_from_feedback(
        previous=stage1_v1,
        answers=answers,
        free_feedback=free_feedback,
        paper_content=PAPER_PATH.read_text(encoding="utf-8"),
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage1_diff_markdown(stage1_v1, stage1_v2))
else:
    print("Skipped feedback revision.")


# %% [markdown]
# ## 5. Inspect revised output

# %%
print(stage1_v2.summary_markdown())

review_v2_path = OUTPUT_DIR / "stage1_output_v2.review.jsonc"
parser.export_stage1_review_jsonc(stage1_v2, review_v2_path)
print(f"Revised review JSONC saved to: {review_v2_path}")


# %% [markdown]
# ## 6. Confirm Stage 1
#
# Run this only after the Stage 1 output is accepted. This writes
# ``stage1_final.json``. Stage 2 should consume this confirmed file.

# %%
RUN_CONFIRM = False

if RUN_CONFIRM:
    final_path = parser.confirm_stage1(stage1_v2, output_dir=OUTPUT_DIR)
    print(f"Confirmed Stage 1 saved to: {final_path}")
else:
    print("Skipped confirm_stage1.")


# %% [markdown]
# ## 7. Resume from an existing Stage 1 file
#
# If you already have a previous run, load it here and continue from step 3/4.

# %%
RUN_RESUME = False

if RUN_RESUME:
    existing_path = OUTPUT_DIR / "stage1_final.json"
    resumed = Stage1Output.model_validate_json(
        existing_path.read_text(encoding="utf-8")
    )
    resumed.assert_valid()
    parser.export_stage1_review_jsonc(
        resumed,
        OUTPUT_DIR / "stage1_resumed.review.jsonc",
    )
    print(resumed.summary_markdown())
else:
    print("Skipped resume.")
