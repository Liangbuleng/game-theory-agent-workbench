from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path
from typing import Any

import streamlit as st

from agent.llm import LLMClient, load_llm_config
from agent.parser import Parser, Stage1Output, Stage2Output
from agent.parser._doc_utils import load_docx_as_text, load_pdf_as_text, load_plain_text
from agent.phase1 import (
    WolframGenerationOptions,
    generate_wolfram_scripts,
    load_modelspec,
    run_wolfram_scripts,
    write_phase1_diagnostics,
)
from agent.schemas import ModelSpec


PROJECTS_ROOT = Path("output/streamlit_projects")
DEMO_PROJECT_NAME = "responsible_sourcing_demo"
DEMO_SOURCE_ROOT = Path("examples") / DEMO_PROJECT_NAME

DEMO_STEPS: dict[str, list[tuple[str, str]]] = {
    "seed": [("paper", "paper")],
    "stage1_parse": [("stage1_output_v1.json", "stage1_output_v1.json")],
    "stage1_confirm": [("stage1_final.json", "stage1_final.json")],
    "stage2_parse": [("stage2_output_v1.json", "stage2_output_v1.json")],
    "stage2_confirm": [("stage2_final.json", "stage2_final.json")],
    "finalize": [
        ("modelspec_final.yaml", "modelspec_final.yaml"),
        ("modelspec_final.json", "modelspec_final.json"),
    ],
    "phase1_generate": [
        ("phase1_wolfram/manifest.json", "phase1_wolfram/manifest.json"),
        ("phase1_wolfram/README.md", "phase1_wolfram/README.md"),
        ("phase1_wolfram/run_all.wl", "phase1_wolfram/run_all.wl"),
        ("phase1_wolfram/scenarios", "phase1_wolfram/scenarios"),
    ],
    "phase15_run": [
        ("phase1_wolfram/all_results.json", "phase1_wolfram/all_results.json"),
        ("phase1_wolfram/mechanism_summaries.json", "phase1_wolfram/mechanism_summaries.json"),
        ("phase1_wolfram/phase1_diagnostics.json", "phase1_wolfram/phase1_diagnostics.json"),
        ("phase1_wolfram/phase1_report.md", "phase1_wolfram/phase1_report.md"),
        ("phase1_wolfram/run_logs", "phase1_wolfram/run_logs"),
        ("phase1_wolfram/run_summary.json", "phase1_wolfram/run_summary.json"),
    ],
}


def main() -> None:
    st.set_page_config(
        page_title="Game Theory Agent Workbench",
        layout="wide",
    )
    PROJECTS_ROOT.mkdir(parents=True, exist_ok=True)

    _init_state()
    st.title("Game Theory Agent Workbench")
    st.caption("Phase 0 parsing, review, finalize, and Phase 1 Wolfram execution.")

    if _demo_mode():
        _ensure_demo_project_seed()

    project_dir = _sidebar()
    if project_dir is None:
        st.info("Create or select a project in the sidebar to begin.")
        return

    _hydrate_project_state(project_dir)
    paper_path = _project_paper_path(project_dir)

    st.write(f"**Project**: `{project_dir.name}`")
    st.write(f"**Workspace**: `{project_dir.resolve()}`")
    if paper_path.exists():
        st.write(f"**Paper**: `{paper_path}`")

    tabs = st.tabs(["Guide", "Project", "Stage 1", "Stage 2", "Finalize", "Phase 1"])
    with tabs[0]:
        _render_guide_tab()
    with tabs[1]:
        _render_project_tab(project_dir, paper_path)
    with tabs[2]:
        _render_stage1_tab(project_dir, paper_path)
    with tabs[3]:
        _render_stage2_tab(project_dir, paper_path)
    with tabs[4]:
        _render_finalize_tab(project_dir)
    with tabs[5]:
        _render_phase1_tab(project_dir)


def _init_state() -> None:
    defaults = {
        "current_project": "",
        "stage1_review_jsonc": "",
        "stage2_review_jsonc": "",
        "stage1_feedback_answers": "{}",
        "stage2_feedback_answers": "{}",
        "stage1_feedback_text": "",
        "stage2_feedback_text": "",
        "stage1_diff_markdown": "",
        "stage2_diff_markdown": "",
        "phase1_parameter_values": "{}",
        "phase1_wolframscript_path": "",
        "phase1_generate_timeout": 120,
        "phase1_simplify_timeout": 30,
        "phase1_run_timeout": 180,
        "phase1_solve_mode": "symbolic",
        "provider_name": "",
        "llm_stream": True,
        "llm_log": True,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def _sidebar() -> Path | None:
    st.sidebar.header("Project")
    if _demo_mode():
        st.sidebar.info("Demo Mode: precomputed walkthrough")
        st.sidebar.selectbox("Open project", [DEMO_PROJECT_NAME], disabled=True)
        st.sidebar.text_input("New project name", value="", disabled=True)
        st.sidebar.selectbox("LLM provider", ["demo-precomputed"], disabled=True)
        st.sidebar.checkbox("LLM streaming", value=False, disabled=True)
        st.sidebar.checkbox("LLM logging", value=False, disabled=True)
        st.session_state.current_project = DEMO_PROJECT_NAME
        st.session_state.provider_name = "demo-precomputed"
        st.session_state.llm_stream = False
        st.session_state.llm_log = False
        _reset_project_buffers_if_needed(DEMO_PROJECT_NAME)
        return PROJECTS_ROOT / DEMO_PROJECT_NAME

    existing = sorted(
        [path for path in PROJECTS_ROOT.iterdir() if path.is_dir()],
        key=lambda path: path.name.lower(),
    )
    options = ["<new project>", *[path.name for path in existing]]
    default_index = 0
    if st.session_state.current_project:
        for idx, name in enumerate(options):
            if name == st.session_state.current_project:
                default_index = idx
                break

    selected = st.sidebar.selectbox("Open project", options, index=default_index)
    new_name = st.sidebar.text_input(
        "New project name",
        value=st.session_state.current_project if selected == "<new project>" else "",
        placeholder="e.g. qwen_information_sharing_paper",
    )
    provider_options = _provider_names()
    provider_value = st.session_state.provider_name or (
        provider_options[0] if provider_options else ""
    )
    st.session_state.provider_name = st.sidebar.selectbox(
        "LLM provider",
        provider_options,
        index=provider_options.index(provider_value) if provider_value in provider_options else 0,
    )
    st.session_state.llm_stream = st.sidebar.checkbox(
        "LLM streaming",
        value=bool(st.session_state.llm_stream),
    )
    st.session_state.llm_log = st.sidebar.checkbox(
        "LLM logging",
        value=bool(st.session_state.llm_log),
    )

    if selected == "<new project>":
        slug = _slugify(new_name)
        if not slug:
            return None
        project_dir = PROJECTS_ROOT / slug
        project_dir.mkdir(parents=True, exist_ok=True)
        _reset_project_buffers_if_needed(slug)
        st.session_state.current_project = slug
        return project_dir

    _reset_project_buffers_if_needed(selected)
    st.session_state.current_project = selected
    return PROJECTS_ROOT / selected


def _render_guide_tab() -> None:
    st.subheader("Guide")
    if _demo_mode():
        st.info(
            "This online demo follows the same workflow as the full app. "
            "Run buttons load precomputed results instead of calling an LLM or WolframScript."
        )
    else:
        st.write(
            "Follow the tabs from left to right to extract, review, finalize, "
            "and solve a game-theoretic model."
        )

    st.markdown(
        """
### Workflow

1. **Project**: create or open a project and upload a paper/model document.
2. **Stage 1**: extract players, decisions, parameters, timing, information, payoffs, and scenarios.
3. **Stage 2**: extract the solving procedure and scenario-specific solving details.
4. **Finalize**: combine Stage 1 and Stage 2 into a `ModelSpec`.
5. **Phase 1**: generate Wolfram scripts and inspect equilibrium/payoff reports.

### Demo Mode

The demo uses a synthetic responsible-sourcing game. It does not upload the
original reference paper, does not call external LLM APIs, and does not run
WolframScript. Click the main workflow buttons to reveal each precomputed step.
        """.strip()
    )


def _render_project_tab(project_dir: Path, paper_path: Path) -> None:
    st.subheader("Paper")
    uploaded = st.file_uploader(
        "Upload paper markdown / pdf / docx / tex",
        type=None,
        key="paper_uploader",
    )
    if uploaded is not None:
        target = project_dir / "paper" / uploaded.name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(uploaded.getvalue())
        st.success(f"Saved uploaded paper to `{target}`")
        st.rerun()

    if paper_path.exists():
        preview, warnings = _paper_preview_text(paper_path)
        if warnings:
            for warning in warnings:
                st.warning(warning)
        st.code(preview[:4000], language="markdown")
        if len(preview) > 4000:
            st.caption("Preview truncated to the first 4000 characters.")
    else:
        st.info("No paper file yet. Upload one to unlock Stage 1.")

    st.subheader("Artifacts")
    for name, path in _artifact_paths(project_dir).items():
        if path.exists():
            st.write(f"- `{name}`: `{path}`")


def _render_stage1_tab(project_dir: Path, paper_path: Path) -> None:
    st.subheader("Stage 1: GameBasics")
    if not paper_path.exists():
        st.info("Upload a paper first.")
        return

    st.caption(
        "Stage 1 usually waits on document loading and one or more LLM calls. "
        "Large PDFs or slow providers can take a few minutes."
    )

    if st.button("Run Stage 1 parse", key="run_stage1"):
        if _demo_mode():
            _apply_demo_step(project_dir, "stage1_parse")
            st.success("Demo Stage 1 result loaded.")
            st.rerun()
        start = time.perf_counter()
        with st.status("Stage 1 parse is running...", expanded=True) as status:
            st.write(f"Provider: `{st.session_state.provider_name or 'default'}`")
            st.write(f"Paper: `{paper_path.name}`")
            st.write("Preparing parser and LLM client...")
            try:
                parser = _build_parser(project_dir)
                st.write("Loading paper and sending Stage 1 prompt to the LLM...")
                stage1 = parser.parse_stage1(
                    paper_path,
                    output_dir=project_dir,
                    save=True,
                )
                st.write("Validating output and preparing review JSONC...")
                st.session_state.stage1_review_jsonc = str(
                    parser.export_stage1_review_jsonc(stage1)
                )
                st.session_state.stage1_diff_markdown = ""
            except Exception as error:  # noqa: BLE001
                elapsed = time.perf_counter() - start
                status.update(
                    label=f"Stage 1 parse failed after {elapsed:.1f}s",
                    state="error",
                    expanded=True,
                )
                st.exception(error)
                _render_llm_log_tail(project_dir)
                return

            elapsed = time.perf_counter() - start
            status.update(
                label=f"Stage 1 parse completed in {elapsed:.1f}s",
                state="complete",
                expanded=True,
            )
        st.success("Stage 1 parse completed.")
        st.rerun()

    stage1 = _load_stage1(project_dir)
    if stage1 is None:
        st.caption("No Stage 1 output yet.")
        return

    st.markdown(stage1.summary_markdown())

    if not st.session_state.stage1_review_jsonc:
        parser = _build_parser(project_dir)
        st.session_state.stage1_review_jsonc = str(
            parser.export_stage1_review_jsonc(stage1)
        )

    st.subheader("Review JSONC")
    st.session_state.stage1_review_jsonc = st.text_area(
        "Edit Stage1Output JSONC",
        value=st.session_state.stage1_review_jsonc,
        height=420,
        key="stage1_review_jsonc_editor",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Apply Stage 1 JSONC revision", key="apply_stage1_jsonc"):
            if _demo_mode():
                st.info("JSONC revision is disabled in demo mode. Run locally to edit and revise outputs.")
                return
            parser = _build_parser(project_dir)
            revised = parser.stage1_revise_from_json(
                st.session_state.stage1_review_jsonc,
                output_dir=project_dir,
                save=True,
            )
            st.session_state.stage1_diff_markdown = parser.format_stage1_diff_markdown(
                stage1, revised
            )
            st.session_state.stage1_review_jsonc = str(
                parser.export_stage1_review_jsonc(revised)
            )
            st.success("Stage 1 JSONC revision applied.")
            st.rerun()
    with col2:
        if st.button("Confirm Stage 1", key="confirm_stage1"):
            if _demo_mode():
                _apply_demo_step(project_dir, "stage1_confirm")
                st.success("Demo Stage 1 confirmed.")
                st.rerun()
            parser = _build_parser(project_dir)
            parser.confirm_stage1(stage1, output_dir=project_dir)
            st.success("Stage 1 confirmed.")
            st.rerun()

    st.subheader("Natural-language revision")
    st.session_state.stage1_feedback_answers = st.text_area(
        "Clarification answers JSON",
        value=st.session_state.stage1_feedback_answers,
        height=120,
        key="stage1_feedback_answers_editor",
    )
    st.session_state.stage1_feedback_text = st.text_area(
        "Free-form feedback",
        value=st.session_state.stage1_feedback_text,
        height=120,
        key="stage1_feedback_text_editor",
    )
    if st.button("Run Stage 1 feedback revision", key="run_stage1_feedback"):
        if _demo_mode():
            st.info("Feedback revision is disabled in demo mode. Run locally to call LLM revisions.")
            return
        parser = _build_parser(project_dir)
        revised = parser.stage1_revise_from_feedback(
            previous=stage1,
            answers=_parse_json_object(st.session_state.stage1_feedback_answers),
            free_feedback=st.session_state.stage1_feedback_text,
            paper_content=_paper_text_for_feedback(paper_path),
            output_dir=project_dir,
            save=True,
        )
        st.session_state.stage1_diff_markdown = parser.format_stage1_diff_markdown(
            stage1, revised
        )
        st.session_state.stage1_review_jsonc = str(
            parser.export_stage1_review_jsonc(revised)
        )
        st.success("Stage 1 feedback revision completed.")
        st.rerun()

    if st.session_state.stage1_diff_markdown:
        st.subheader("Last diff")
        st.markdown(st.session_state.stage1_diff_markdown)


def _render_stage2_tab(project_dir: Path, paper_path: Path) -> None:
    st.subheader("Stage 2: SolvingProcedure")
    stage1 = _load_stage1(project_dir)
    if stage1 is None:
        st.info("Run Stage 1 first.")
        return

    if st.button("Run Stage 2 parse", key="run_stage2"):
        if _demo_mode():
            _apply_demo_step(project_dir, "stage2_parse")
            st.success("Demo Stage 2 result loaded.")
            st.rerun()
        start = time.perf_counter()
        with st.status("Stage 2 parse is running...", expanded=True) as status:
            st.write(f"Provider: `{st.session_state.provider_name or 'default'}`")
            st.write("Sending confirmed Stage 1 and paper content to the LLM...")
            try:
                parser = _build_parser(project_dir)
                stage2 = parser.parse_stage2(
                    stage1,
                    paper_path=paper_path,
                    output_dir=project_dir,
                    save=True,
                )
                st.write("Validating output and preparing review JSONC...")
                st.session_state.stage2_review_jsonc = str(
                    parser.export_stage2_review_jsonc(stage2)
                )
                st.session_state.stage2_diff_markdown = ""
            except Exception as error:  # noqa: BLE001
                elapsed = time.perf_counter() - start
                status.update(
                    label=f"Stage 2 parse failed after {elapsed:.1f}s",
                    state="error",
                    expanded=True,
                )
                st.exception(error)
                _render_llm_log_tail(project_dir)
                return

            elapsed = time.perf_counter() - start
            status.update(
                label=f"Stage 2 parse completed in {elapsed:.1f}s",
                state="complete",
                expanded=True,
            )
        st.success("Stage 2 parse completed.")
        st.rerun()

    stage2 = _load_stage2(project_dir)
    if stage2 is None:
        st.caption("No Stage 2 output yet.")
        return

    st.markdown(stage2.summary_markdown())

    if not st.session_state.stage2_review_jsonc:
        parser = _build_parser(project_dir)
        st.session_state.stage2_review_jsonc = str(
            parser.export_stage2_review_jsonc(stage2)
        )

    st.subheader("Review JSONC")
    st.session_state.stage2_review_jsonc = st.text_area(
        "Edit Stage2Output JSONC",
        value=st.session_state.stage2_review_jsonc,
        height=420,
        key="stage2_review_jsonc_editor",
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Apply Stage 2 JSONC revision", key="apply_stage2_jsonc"):
            if _demo_mode():
                st.info("JSONC revision is disabled in demo mode. Run locally to edit and revise outputs.")
                return
            parser = _build_parser(project_dir)
            revised = parser.stage2_revise_from_json(
                st.session_state.stage2_review_jsonc,
                stage1,
                output_dir=project_dir,
                save=True,
            )
            st.session_state.stage2_diff_markdown = parser.format_stage2_diff_markdown(
                stage2, revised
            )
            st.session_state.stage2_review_jsonc = str(
                parser.export_stage2_review_jsonc(revised)
            )
            st.success("Stage 2 JSONC revision applied.")
            st.rerun()
    with col2:
        if st.button("Confirm Stage 2", key="confirm_stage2"):
            if _demo_mode():
                _apply_demo_step(project_dir, "stage2_confirm")
                st.success("Demo Stage 2 confirmed.")
                st.rerun()
            parser = _build_parser(project_dir)
            parser.confirm_stage2(stage2, basics=stage1.basics, output_dir=project_dir)
            st.success("Stage 2 confirmed.")
            st.rerun()

    st.subheader("Natural-language revision")
    st.session_state.stage2_feedback_answers = st.text_area(
        "Clarification answers JSON",
        value=st.session_state.stage2_feedback_answers,
        height=120,
        key="stage2_feedback_answers_editor",
    )
    st.session_state.stage2_feedback_text = st.text_area(
        "Free-form feedback",
        value=st.session_state.stage2_feedback_text,
        height=120,
        key="stage2_feedback_text_editor",
    )
    if st.button("Run Stage 2 feedback revision", key="run_stage2_feedback"):
        if _demo_mode():
            st.info("Feedback revision is disabled in demo mode. Run locally to call LLM revisions.")
            return
        parser = _build_parser(project_dir)
        revised = parser.stage2_revise_from_feedback(
            previous=stage2,
            stage1=stage1,
            answers=_parse_json_object(st.session_state.stage2_feedback_answers),
            free_feedback=st.session_state.stage2_feedback_text,
            paper_path=paper_path,
            output_dir=project_dir,
            save=True,
        )
        st.session_state.stage2_diff_markdown = parser.format_stage2_diff_markdown(
            stage2, revised
        )
        st.session_state.stage2_review_jsonc = str(
            parser.export_stage2_review_jsonc(revised)
        )
        st.success("Stage 2 feedback revision completed.")
        st.rerun()

    if st.session_state.stage2_diff_markdown:
        st.subheader("Last diff")
        st.markdown(st.session_state.stage2_diff_markdown)


def _render_finalize_tab(project_dir: Path) -> None:
    st.subheader("Finalize ModelSpec")
    stage1 = _load_stage1(project_dir)
    stage2 = _load_stage2(project_dir)
    if stage1 is None or stage2 is None:
        st.info("Stage 1 and Stage 2 outputs are both required.")
        return

    if st.button("Finalize ModelSpec", key="finalize_modelspec"):
        if _demo_mode():
            _apply_demo_step(project_dir, "finalize")
            st.success("Demo ModelSpec finalized.")
            st.rerun()
        parser = _build_parser(project_dir)
        spec = parser.finalize(
            stage1,
            stage2,
            output_dir=project_dir,
            save=True,
            save_json=True,
        )
        st.success(f"ModelSpec finalized: {spec.basics.title}")
        st.rerun()

    spec = _load_modelspec(project_dir)
    if spec is not None:
        st.write(f"**Title**: {spec.basics.title}")
        st.write(f"**Game type**: `{spec.basics.game_type.value}`")
        yaml_path = project_dir / "modelspec_final.yaml"
        json_path = project_dir / "modelspec_final.json"
        if yaml_path.exists():
            st.code(yaml_path.read_text(encoding="utf-8")[:5000], language="yaml")
        if json_path.exists():
            st.caption(f"JSON artifact: `{json_path}`")


def _render_phase1_tab(project_dir: Path) -> None:
    st.subheader("Phase 1: Wolfram")
    spec = _load_modelspec(project_dir)
    if spec is None:
        st.info("Finalize ModelSpec first.")
        return

    st.session_state.phase1_solve_mode = st.selectbox(
        "Solve mode",
        ["symbolic", "semi_numeric", "numeric"],
        index=["symbolic", "semi_numeric", "numeric"].index(
            st.session_state.phase1_solve_mode
        ),
    )
    st.session_state.phase1_generate_timeout = st.number_input(
        "Solve timeout (seconds)",
        min_value=1,
        value=int(st.session_state.phase1_generate_timeout),
    )
    st.session_state.phase1_simplify_timeout = st.number_input(
        "Simplify timeout (seconds)",
        min_value=1,
        value=int(st.session_state.phase1_simplify_timeout),
    )
    st.session_state.phase1_parameter_values = st.text_area(
        "Parameter values JSON",
        value=st.session_state.phase1_parameter_values,
        height=120,
    )
    phase1_dir = project_dir / "phase1_wolfram"

    if st.button("Generate Wolfram scripts", key="generate_phase1"):
        if _demo_mode():
            _apply_demo_step(project_dir, "phase1_generate")
            st.success("Demo Wolfram scripts loaded.")
            st.rerun()
        options = WolframGenerationOptions(
            solve_timeout_seconds=int(st.session_state.phase1_generate_timeout),
            simplify_timeout_seconds=int(st.session_state.phase1_simplify_timeout),
            solve_mode=st.session_state.phase1_solve_mode,
            parameter_values=_parse_json_object(st.session_state.phase1_parameter_values),
        )
        result = generate_wolfram_scripts(spec, phase1_dir, options=options)
        st.success(f"Generated {len(result.scenario_scripts)} scenario scripts.")
        st.rerun()

    manifest_path = phase1_dir / "manifest.json"
    if manifest_path.exists():
        st.write(f"**Manifest**: `{manifest_path}`")

    st.session_state.phase1_wolframscript_path = st.text_input(
        "wolframscript path (optional)",
        value=st.session_state.phase1_wolframscript_path,
        placeholder=r"C:\Program Files\Wolfram Research\WolframScript\wolframscript.exe",
    )
    st.session_state.phase1_run_timeout = st.number_input(
        "Run timeout (seconds)",
        min_value=1,
        value=int(st.session_state.phase1_run_timeout),
    )
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Run Phase 1.5", key="run_phase15"):
            if _demo_mode():
                _apply_demo_step(project_dir, "phase15_run")
                st.success("Demo Phase 1.5 results loaded.")
                st.rerun()
            start = time.perf_counter()
            manifest = _load_phase1_manifest_for_ui(phase1_dir)
            scenario_count = len(manifest.get("scenarios", [])) if manifest else 0
            timeout_seconds = int(st.session_state.phase1_run_timeout)
            with st.status("Phase 1.5 Wolfram run is running...", expanded=True) as status:
                st.write(f"Output dir: `{phase1_dir}`")
                st.write(f"Scenarios: `{scenario_count}`")
                st.write(f"Per-scenario timeout: `{timeout_seconds}` seconds")
                st.write("Launching wolframscript for generated scenario files...")
                try:
                    kwargs: dict[str, Any] = {
                        "output_dir": phase1_dir,
                        "timeout_seconds": timeout_seconds,
                    }
                    if st.session_state.phase1_wolframscript_path.strip():
                        kwargs["wolframscript_path"] = (
                            st.session_state.phase1_wolframscript_path.strip()
                        )
                    result = run_wolfram_scripts(**kwargs)
                except Exception as error:  # noqa: BLE001
                    elapsed = time.perf_counter() - start
                    status.update(
                        label=f"Phase 1.5 failed after {elapsed:.1f}s",
                        state="error",
                        expanded=True,
                    )
                    st.exception(error)
                    _render_phase1_run_log_tail(phase1_dir)
                    return

                elapsed = time.perf_counter() - start
                status.update(
                    label=f"Phase 1.5 completed in {elapsed:.1f}s",
                    state="complete",
                    expanded=True,
                )
            st.success(f"Run complete: {result.diagnostics.counts}")
            st.rerun()
    with col2:
        if st.button("Diagnose existing results", key="diagnose_phase15"):
            if _demo_mode():
                st.info("Diagnostics refresh is disabled in demo mode. Precomputed diagnostics are loaded with Phase 1.5.")
                return
            diagnostics = write_phase1_diagnostics(phase1_dir)
            st.success(f"Diagnostics refreshed: {diagnostics.counts}")
            st.rerun()

    report_path = phase1_dir / "phase1_report.md"
    diagnostics_path = phase1_dir / "phase1_diagnostics.json"
    mechanism_path = phase1_dir / "mechanism_summaries.json"
    if diagnostics_path.exists():
        st.subheader("Diagnostics")
        st.json(json.loads(diagnostics_path.read_text(encoding="utf-8")))
    if mechanism_path.exists():
        st.subheader("Mechanisms")
        st.json(json.loads(mechanism_path.read_text(encoding="utf-8")))
    if report_path.exists():
        st.subheader("Report")
        st.markdown(report_path.read_text(encoding="utf-8"))
    _render_phase1_run_log_tail(phase1_dir)


def _build_parser(project_dir: Path) -> Parser:
    provider = st.session_state.provider_name.strip()
    if st.session_state.llm_log:
        os.environ["GTA_LLM_LOG_FILE"] = str(project_dir / "llm_streamlit.log")
    else:
        os.environ.pop("GTA_LLM_LOG_FILE", None)
    llm_client = LLMClient(provider=provider) if provider else None
    return Parser(
        llm_client=llm_client,
        output_root=project_dir,
        auto_save=False,
        llm_stream=bool(st.session_state.llm_stream),
        llm_log=bool(st.session_state.llm_log),
    )


def _render_llm_log_tail(project_dir: Path, *, max_lines: int = 80) -> None:
    path = project_dir / "llm_streamlit.log"
    if not path.exists():
        return
    lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    if not lines:
        return
    st.subheader("Recent LLM log")
    st.code("\n".join(lines[-max_lines:]), language="text")


class _NullLLMClient:
    """Placeholder used only for JSONC export in demo mode."""

    provider_config = None


def _demo_mode() -> bool:
    value = os.environ.get("GTA_DEMO_MODE", "")
    return value.lower() in {"1", "true", "yes", "on"}


def _ensure_demo_project_seed() -> None:
    target = PROJECTS_ROOT / DEMO_PROJECT_NAME
    if target.exists():
        return
    _apply_demo_step(target, "seed")


def _apply_demo_step(project_dir: Path, step: str) -> None:
    if step not in DEMO_STEPS:
        raise ValueError(f"Unknown demo step: {step}")
    if not DEMO_SOURCE_ROOT.exists():
        raise FileNotFoundError(f"Missing demo source directory: {DEMO_SOURCE_ROOT}")
    for source_rel, target_rel in DEMO_STEPS[step]:
        source = DEMO_SOURCE_ROOT / source_rel
        target = project_dir / target_rel
        if not source.exists():
            raise FileNotFoundError(f"Missing demo artifact: {source}")
        if source.is_dir():
            if target.exists():
                shutil.rmtree(target)
            shutil.copytree(source, target)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)


def _provider_names() -> list[str]:
    try:
        config = load_llm_config()
    except Exception:
        return [""]
    names = sorted(config.providers.keys())
    return [config.default_provider, *[name for name in names if name != config.default_provider]]


def _project_paper_path(project_dir: Path) -> Path:
    paper_dir = project_dir / "paper"
    if not paper_dir.exists():
        return paper_dir / "paper.md"
    candidates = sorted([path for path in paper_dir.iterdir() if path.is_file()])
    if candidates:
        return candidates[0]
    return paper_dir / "paper.md"


def _paper_preview_text(path: Path) -> tuple[str, list[str]]:
    ext = path.suffix.lower()
    try:
        if ext == ".docx":
            text, warnings = load_docx_as_text(path)
            return text or "(No previewable text extracted from this docx.)", warnings
        if ext == ".pdf":
            text, warnings = load_pdf_as_text(path)
            return text or "(No previewable text extracted from this PDF.)", warnings
        if ext in {".txt", ".md", ".markdown", ".tex"}:
            if ext == ".tex":
                text = path.read_text(encoding="utf-8", errors="replace")
                return text.strip(), []
            text, warnings = load_plain_text(path)
            return text, warnings
    except Exception as error:  # noqa: BLE001
        return (
            f"Preview failed for {path.name}: {type(error).__name__}: {error}",
            [],
        )
    return (
        f"Preview is not available for `{ext or 'unknown'}` files. "
        "The file is still saved in this project.",
        [],
    )


def _paper_text_for_feedback(path: Path) -> str:
    text, _warnings = _paper_preview_text(path)
    return text


def _artifact_paths(project_dir: Path) -> dict[str, Path]:
    return {
        "stage1_final": project_dir / "stage1_final.json",
        "stage2_final": project_dir / "stage2_final.json",
        "modelspec_yaml": project_dir / "modelspec_final.yaml",
        "modelspec_json": project_dir / "modelspec_final.json",
        "phase1_manifest": project_dir / "phase1_wolfram" / "manifest.json",
        "phase1_report": project_dir / "phase1_wolfram" / "phase1_report.md",
    }


def _hydrate_project_state(project_dir: Path) -> None:
    stage1 = _load_stage1(project_dir)
    if stage1 is not None and not st.session_state.stage1_review_jsonc:
        parser = Parser(llm_client=_NullLLMClient(), auto_save=False) if _demo_mode() else _build_parser(project_dir)
        st.session_state.stage1_review_jsonc = str(parser.export_stage1_review_jsonc(stage1))
    stage2 = _load_stage2(project_dir)
    if stage2 is not None and not st.session_state.stage2_review_jsonc:
        parser = Parser(llm_client=_NullLLMClient(), auto_save=False) if _demo_mode() else _build_parser(project_dir)
        st.session_state.stage2_review_jsonc = str(parser.export_stage2_review_jsonc(stage2))


def _reset_project_buffers_if_needed(project_name: str) -> None:
    active = st.session_state.get("_buffer_project_name", "")
    if active == project_name:
        return
    st.session_state._buffer_project_name = project_name
    st.session_state.stage1_review_jsonc = ""
    st.session_state.stage2_review_jsonc = ""
    st.session_state.stage1_diff_markdown = ""
    st.session_state.stage2_diff_markdown = ""


def _load_stage1(project_dir: Path) -> Stage1Output | None:
    path = _latest_existing(
        [
            project_dir / "stage1_final.json",
            *sorted(project_dir.glob("stage1_output_v*.json")),
        ]
    )
    if path is None:
        return None
    return Stage1Output.model_validate_json(path.read_text(encoding="utf-8"))


def _load_stage2(project_dir: Path) -> Stage2Output | None:
    path = _latest_existing(
        [
            project_dir / "stage2_final.json",
            *sorted(project_dir.glob("stage2_output_v*.json")),
        ]
    )
    if path is None:
        return None
    return Stage2Output.model_validate_json(path.read_text(encoding="utf-8"))


def _load_modelspec(project_dir: Path) -> ModelSpec | None:
    path = project_dir / "modelspec_final.json"
    if path.exists():
        return ModelSpec.model_validate_json(path.read_text(encoding="utf-8"))
    yaml_path = project_dir / "modelspec_final.yaml"
    if yaml_path.exists():
        return load_modelspec(yaml_path)
    return None


def _load_phase1_manifest_for_ui(phase1_dir: Path) -> dict[str, Any] | None:
    path = phase1_dir / "manifest.json"
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _render_phase1_run_log_tail(phase1_dir: Path, *, max_chars: int = 2000) -> None:
    logs_dir = phase1_dir / "run_logs"
    if not logs_dir.exists():
        return
    log_paths = sorted(
        [
            path
            for path in logs_dir.glob("*.txt")
            if path.is_file() and path.stat().st_size > 0
        ],
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not log_paths:
        return

    st.subheader("Recent Phase 1.5 logs")
    for path in log_paths[:4]:
        text = path.read_text(encoding="utf-8", errors="replace")
        st.caption(f"`{path}`")
        st.code(text[-max_chars:], language="text")


def _latest_existing(paths: list[Path]) -> Path | None:
    existing = [path for path in paths if path.exists()]
    if not existing:
        return None
    return sorted(existing, key=lambda path: path.name)[-1]


def _slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9._-]+", "_", text)
    return text.strip("._-")


def _parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        return {}
    data = json.loads(stripped)
    if not isinstance(data, dict):
        raise ValueError("Expected a JSON object.")
    return data


if __name__ == "__main__":
    main()
