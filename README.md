# Game Theory Agent Workbench

A Streamlit workbench for game-theory and operations researchers. The app helps
you upload a model document, review extracted game structure, finalize a
machine-readable `ModelSpec`, and inspect Wolfram-based equilibrium reports.

## Quick Start

```powershell
conda env create -f environment.yml
conda activate gta
pip install -e .
python -m streamlit run streamlit_app.py
```

Then open:

```text
http://localhost:8501
```

The web app includes a **Guide** tab. Follow the tabs from left to right.

## API Keys

Copy `.env.example` to `.env`, then fill in the provider key you want to use.

```powershell
Copy-Item .env.example .env
```

Provider settings live in `agent_config.yaml`.

## Online Demo

The online demo should be deployed with:

```text
GTA_DEMO_MODE=1
```

Demo mode uses a synthetic responsible-sourcing example with precomputed
artifacts. It does not call external LLM APIs and does not run WolframScript.

## Generated Files

User projects, uploaded papers, logs, and generated outputs are written under
`output/` and are intentionally ignored by git.

Do not commit `.env`, real papers, or generated project outputs.
