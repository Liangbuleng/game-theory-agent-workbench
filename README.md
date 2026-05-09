# Game Theory Agent Workbench

English | [中文](#中文说明)

A Streamlit workbench for game-theory and operations researchers. The app helps
you upload a model document, review extracted game structure, finalize a
machine-readable `ModelSpec`, and inspect Wolfram-based equilibrium reports.

## Quick Start

```powershell
git clone <repo-url>
cd game-theory-agent-workbench
conda env create -f environment.local.yml
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

## Local Demo Mode

To run the precomputed demo locally without API keys or WolframScript:

```powershell
$env:GTA_DEMO_MODE="1"
python -m streamlit run streamlit_app.py
```

## Online Demo

Online demo: `<streamlit-demo-url>`

The online demo should be deployed with:

```text
GTA_DEMO_MODE=1
```

Demo mode uses a synthetic responsible-sourcing example with precomputed
artifacts. It does not call external LLM APIs and does not run WolframScript.


---

# 中文说明

[English](#game-theory-agent-workbench) | 中文

这是一个面向博弈论与运营管理研究者的 Streamlit 网页工作台。它可以帮助你上传模型文档，审阅自动抽取的博弈结构，生成机器可读的 `ModelSpec`，并查看基于 Wolfram 的均衡与收益报告。

## 快速开始

```powershell
git clone <repo-url>
cd game-theory-agent-workbench
conda env create -f environment.local.yml
conda activate gta
pip install -e .
python -m streamlit run streamlit_app.py
```

然后打开：

```text
http://localhost:8501
```

网页中包含 **Guide** 标签页。按照页面从左到右的标签页操作即可。

## API Key 配置

复制 `.env.example` 为 `.env`，然后填写你要使用的模型服务 API key。

```powershell
Copy-Item .env.example .env
```

模型服务配置在 `agent_config.yaml` 中。

## 本地 Demo 模式

如果你只想查看预计算演示，不想配置 API key 或 WolframScript，可以运行：

```powershell
$env:GTA_DEMO_MODE="1"
python -m streamlit run streamlit_app.py
```

## 在线 Demo

在线演示地址：`<streamlit-demo-url>`

在线 demo 部署时应设置：

```text
GTA_DEMO_MODE=1
```

Demo 模式使用一个合成的 responsible sourcing 示例和预计算结果，不会调用外部 LLM API，也不会运行 WolframScript。


