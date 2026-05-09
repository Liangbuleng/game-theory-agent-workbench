"""Complete Phase 0 workflow template.

This file uses VS Code/Jupyter ``# %%`` cells. Run cells one by one:

1. parse and review Stage 1
2. optionally revise Stage 1
3. confirm Stage 1
4. parse and review Stage 2
5. optionally revise Stage 2
6. confirm Stage 2
7. finalize ModelSpec
"""

# %%
from pathlib import Path

from agent.llm import LLMClient
from agent.parser import Parser


# %% [markdown]
# ## 1. Configure paths

# %%
PAPER_PATH = Path("output/model_pandoc.md")
OUTPUT_DIR = Path("output/phase0_workflow")

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
# ## 2. Stage 1: parse GameBasics

# %%
stage1_v1 = parser.parse_stage1(
    PAPER_PATH,
    output_dir=OUTPUT_DIR,
    save=True,
)
print(stage1_v1.summary_markdown())

stage1_review_path = OUTPUT_DIR / "stage1_output_v1.review.jsonc"
parser.export_stage1_review_jsonc(stage1_v1, stage1_review_path)
print(f"Stage 1 review JSONC saved to: {stage1_review_path}")


# %% [markdown]
# ## 3A. Optional Stage 1.5: direct JSONC edit

# %%
RUN_STAGE1_JSONC_REVISION = False

if RUN_STAGE1_JSONC_REVISION:
    stage1_v2 = parser.stage1_revise_from_json(
        stage1_review_path,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage1_diff_markdown(stage1_v1, stage1_v2))
else:
    stage1_v2 = stage1_v1
    print("Skipped Stage 1 JSONC revision.")


# %% [markdown]
# ## 3B. Optional Stage 1.5: natural-language revision

# %%
RUN_STAGE1_FEEDBACK_REVISION = False

stage1_answers = {
    # "q1": "...",
}

stage1_free_feedback = """
Revise only Stage 1 GameBasics facts. Keep correct existing fields unchanged.
"""

if RUN_STAGE1_FEEDBACK_REVISION:
    stage1_v2 = parser.stage1_revise_from_feedback(
        previous=stage1_v1,
        answers=stage1_answers,
        free_feedback=stage1_free_feedback,
        paper_content=PAPER_PATH.read_text(encoding="utf-8"),
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage1_diff_markdown(stage1_v1, stage1_v2))
else:
    print("Skipped Stage 1 feedback revision.")


# %% [markdown]
# ## 4. Confirm Stage 1

# %%
RUN_CONFIRM_STAGE1 = False

if RUN_CONFIRM_STAGE1:
    stage1_final_path = parser.confirm_stage1(stage1_v2, output_dir=OUTPUT_DIR)
    print(f"Confirmed Stage 1 saved to: {stage1_final_path}")
else:
    print("Skipped confirm_stage1.")


# %% [markdown]
# ## 5. Stage 2: parse SolvingProcedure

# %%
stage2_v1 = parser.parse_stage2(
    stage1_v2,
    paper_path=PAPER_PATH,
    output_dir=OUTPUT_DIR,
    save=True,
)
print(stage2_v1.summary_markdown())

stage2_review_path = OUTPUT_DIR / "stage2_output_v1.review.jsonc"
parser.export_stage2_review_jsonc(stage2_v1, stage2_review_path)
print(f"Stage 2 review JSONC saved to: {stage2_review_path}")


# %% [markdown]
# ## 6A. Optional Stage 2.5: direct JSONC edit

# %%
RUN_STAGE2_JSONC_REVISION = False

if RUN_STAGE2_JSONC_REVISION:
    stage2_v2 = parser.stage2_revise_from_json(
        stage2_review_path,
        stage1_v2,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage2_diff_markdown(stage2_v1, stage2_v2))
else:
    stage2_v2 = stage2_v1
    print("Skipped Stage 2 JSONC revision.")


# %% [markdown]
# ## 6B. Optional Stage 2.5: natural-language revision

# %%
RUN_STAGE2_FEEDBACK_REVISION = False

stage2_answers = {
    # "cq1": "...",
}

stage2_free_feedback = """
Revise only Stage 2 solving procedure and research-question fields.
Keep confirmed GameBasics unchanged.
"""

if RUN_STAGE2_FEEDBACK_REVISION:
    stage2_v2 = parser.stage2_revise_from_feedback(
        previous=stage2_v1,
        stage1=stage1_v2,
        answers=stage2_answers,
        free_feedback=stage2_free_feedback,
        paper_path=PAPER_PATH,
        output_dir=OUTPUT_DIR,
        save=True,
    )
    print(parser.format_stage2_diff_markdown(stage2_v1, stage2_v2))
else:
    print("Skipped Stage 2 feedback revision.")


# %% [markdown]
# ## 7. Confirm Stage 2

# %%
RUN_CONFIRM_STAGE2 = False

if RUN_CONFIRM_STAGE2:
    stage2_final_path = parser.confirm_stage2(
        stage2_v2,
        basics=stage1_v2.basics,
        output_dir=OUTPUT_DIR,
    )
    print(f"Confirmed Stage 2 saved to: {stage2_final_path}")
else:
    print("Skipped confirm_stage2.")


# %% [markdown]
# ## 8. Finalize ModelSpec
#
# If Stage 2 has material/blocking ``basics_revision_suggestions``, this cell
# will fail and you should return to Stage 1 before finalizing.

# %%
RUN_FINALIZE = False

if RUN_FINALIZE:
    spec = parser.finalize(
        stage1_v2,
        stage2_v2,
        output_dir=OUTPUT_DIR,
        save=True,
        save_json=True,
    )
    print(f"ModelSpec finalized: {spec.basics.title}")
    print(f"YAML: {OUTPUT_DIR / 'modelspec_final.yaml'}")
    print(f"JSON: {OUTPUT_DIR / 'modelspec_final.json'}")
else:
    print("Skipped finalize.")
