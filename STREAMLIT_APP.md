# Streamlit Workbench

The repository now includes a lightweight Streamlit shell for the existing
Phase 0 and Phase 1 workflow:

- upload a paper into a named project workspace
- run Stage 1 and Stage 2 parsing
- review and edit JSONC outputs in place
- confirm stages and finalize `ModelSpec`
- generate Wolfram scripts
- run or diagnose Phase 1.5 outputs

## Run

From the repo root:

```powershell
streamlit run streamlit_app.py
```

If `streamlit` is not installed yet:

```powershell
pip install streamlit
```

## Project Layout

Each workspace is stored under:

```text
output/streamlit_projects/<project_name>/
```

The app reuses the same artifact names as the notebook workflow:

- `stage1_output_v*.json`
- `stage1_final.json`
- `stage2_output_v*.json`
- `stage2_final.json`
- `modelspec_final.yaml`
- `modelspec_final.json`
- `phase1_wolfram/`

## Current Scope

This is a thin UI shell over the current Python workflow, not a separate app
backend. It is designed to make the existing agent easier to operate while
keeping the parser and solver code unchanged.
