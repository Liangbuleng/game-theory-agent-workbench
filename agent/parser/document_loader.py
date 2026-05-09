"""Document loader: 统一加载论文文件，根据 provider 能力分流。

对外只暴露 load_document() 一个函数。
"""

from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from agent.llm.config import ProviderConfig
from agent.parser._doc_utils import (
    load_pdf_as_base64,
    load_pdf_as_images,
    load_pdf_as_text,
    load_docx_as_text,
    load_plain_text,
)


# ============================================================
# 返回类型
# ============================================================

@dataclass
class LoadResult:
    """document_loader 的返回结构。
    
    Attributes:
        content_blocks: 给 LLM messages 用的 content block 列表。
            可以直接拼进 user message 的 content 字段。
        warnings: 加载过程中的警告（公式丢失、编码问题等）。
        degraded: 是否走了降级路径。
            True 表示 parser 上层应当显示警告并让用户决定是否继续。
        loaded_via: 实际走的加载路径，便于调试。
            可能值：
              - "pdf_native"     PDF base64 直传
              - "pdf_image"      PDF 转图像
              - "pdf_text"       PDF 抽文本（降级）
              - "docx_text"      docx 抽文本
              - "plain_text"     txt/md 直接读
        suggestion: 当 degraded=True 时给用户的建议文本。
    """
    content_blocks: list[dict]
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    loaded_via: str = ""
    suggestion: Optional[str] = None


# ============================================================
# 主接口
# ============================================================

# 文件扩展名归一化
_PDF_EXTS = {".pdf"}
_DOCX_EXTS = {".docx"}
_TEXT_EXTS = {".txt", ".md", ".markdown"}


def load_document(
    file_path: str | Path,
    provider_config: ProviderConfig,
) -> LoadResult:
    """加载文档，返回适合传给 LLM 的 content blocks。
    
    Args:
        file_path: 文档路径，支持 .pdf / .docx / .txt / .md
        provider_config: 当前使用的 provider 配置（用于判断能力）
    
    Returns:
        LoadResult，content_blocks 可直接拼进 messages
    
    Raises:
        FileNotFoundError: 文件不存在
        ValueError: 不支持的文件类型 / 文件过大
        NotImplementedError: 走 Tier 2 但 pdf2image 未配置
    """
    path = Path(file_path).resolve()
    
    if not path.exists():
        raise FileNotFoundError(f"文件不存在：{path}")
    
    if not path.is_file():
        raise ValueError(f"路径不是文件：{path}")
    
    ext = path.suffix.lower()
    caps = provider_config.capabilities
    
    # ============================================
    # 路由分发
    # ============================================
    
    if ext in _PDF_EXTS:
        return _load_pdf(path, caps)
    
    elif ext in _DOCX_EXTS:
        return _load_docx(path)
    
    elif ext in _TEXT_EXTS:
        return _load_plain(path)
    
    else:
        raise ValueError(
            f"不支持的文件类型：{ext}\n"
            f"支持的格式：.pdf, .docx, .txt, .md"
        )


# ============================================================
# 各类型分支
# ============================================================

def _load_pdf(path: Path, caps) -> LoadResult:
    """根据 provider 能力选择 PDF 加载方式。"""
    
    # Tier 1: 原生 PDF
    if caps.supports_pdf:
        b64 = load_pdf_as_base64(path)
        return LoadResult(
            content_blocks=[{
                "type": "document",
                "source": {
                    "type": "base64",
                    "media_type": "application/pdf",
                    "data": b64,
                },
            }],
            warnings=[],
            degraded=False,
            loaded_via="pdf_native",
        )
    
    # Tier 2: 视觉模型，转图像
    if caps.supports_image:
        # 暂未实现，给清晰错误
        try:
            images = load_pdf_as_images(path)
        except NotImplementedError as e:
            return LoadResult(
                content_blocks=[],
                warnings=[str(e)],
                degraded=True,
                loaded_via="pdf_image_failed",
                suggestion=(
                    "Tier 2（视觉模型）路径尚未实现。建议改用支持原生 "
                    "PDF 的 provider，或把 PDF 用网页端 LLM 转成 markdown 文本。"
                ),
            )
        
        blocks = []
        for media_type, b64 in images:
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": media_type,
                    "data": b64,
                },
            })
        
        return LoadResult(
            content_blocks=blocks,
            warnings=[],
            degraded=False,
            loaded_via="pdf_image",
        )
    
    # Tier 3: 纯文本，降级抽文字
    text, warnings = load_pdf_as_text(path)
    
    suggestion = (
        "当前 provider 不支持原生 PDF 或图像，已降级为文本提取。\n"
        "如果论文含复杂数学公式，建议采用以下方案之一：\n"
        "  1. 在 agent_config.yaml 中切换到支持视觉的 provider\n"
        "     （如 anthropic、openai、qwen-vl）\n"
        "  2. 在网页端 LLM（DeepSeek、ChatGPT 等）上传论文，"
        "请它输出含 LaTeX 公式的 markdown 文本，"
        "保存为 .md 文件后用本 agent 处理\n"
        "  3. 接受公式丢失，仅基于结构化文字处理（精度受限）"
    )
    
    return LoadResult(
        content_blocks=[{
            "type": "text",
            "text": _wrap_extracted_text(text, source=f"PDF: {path.name}"),
        }],
        warnings=warnings,
        degraded=True,
        loaded_via="pdf_text",
        suggestion=suggestion,
    )


def _load_docx(path: Path) -> LoadResult:
    """加载 docx 文件。"""
    text, warnings = load_docx_as_text(path)
    
    # docx 抽文字总是会丢公式，标记为 degraded（让 parser 上层提示）
    suggestion = (
        "docx 文档的数学公式（OMML 格式）会在文本提取时丢失。\n"
        "如果论文含复杂公式，建议先用 Word 把 docx 导出为 PDF，"
        "并配合支持原生 PDF 的 provider 处理。"
    )
    
    return LoadResult(
        content_blocks=[{
            "type": "text",
            "text": _wrap_extracted_text(text, source=f"docx: {path.name}"),
        }],
        warnings=warnings,
        degraded=False,
        loaded_via="docx_text",
        suggestion=suggestion,
    )


def _load_plain(path: Path) -> LoadResult:
    """加载纯文本文件。"""
    text, warnings = load_plain_text(path)
    return LoadResult(
        content_blocks=[{
            "type": "text",
            "text": text,
        }],
        warnings=warnings,
        degraded=False,
        loaded_via="plain_text",
    )


# ============================================================
# 辅助
# ============================================================

def _wrap_extracted_text(text: str, source: str) -> str:
    """给提取的文本加一个来源标识，方便 LLM 区分。"""
    return f"[Document: {source}]\n\n{text}"