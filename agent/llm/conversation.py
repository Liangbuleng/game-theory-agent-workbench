"""Conversation: 多轮对话的状态管理。"""

from __future__ import annotations
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from agent.llm.client import LLMClient


class Conversation:
    """维护多轮对话的状态。
    
    使用示例：
    
        client = LLMClient(phase="parser")
        conv = client.new_conversation(system="你是博弈论专家。")
        
        conv.add_user("请帮我分析一个 Cournot 双寡头模型。")
        reply1 = conv.send()
        
        conv.add_user("如果我把 P=a-Q 改成 P=a-bQ 呢？")
        reply2 = conv.send()
        
        # reply2 时 LLM 已经有前面对话历史的上下文
    
    支持多模态：
    
        conv.add_user_with_pdf("请解析这篇论文。", pdf_path="paper.pdf")
        reply = conv.send()
    """

    def __init__(
        self,
        client: "LLMClient",
        system: Optional[str] = None,
    ):
        self.client = client
        self.system = system
        self.messages: list[dict] = []

    # ------------------------------------------------------------
    # 添加消息
    # ------------------------------------------------------------

    def add_user(self, text: str) -> None:
        """添加一条纯文本用户消息。"""
        self.messages.append({"role": "user", "content": text})

    def add_assistant(self, text: str) -> None:
        """手工添加一条 assistant 消息（通常 send() 自动做这件事，
        手工调用用于注入预设回复）。"""
        self.messages.append({"role": "assistant", "content": text})

    def add_user_with_pdf(self, text: str, pdf_path: str) -> None:
        """添加一条带 PDF 附件的用户消息。
        
        注意：PDF block 仅 Anthropic provider 支持。OpenAI 兼容 provider 会
        在调用时报错——届时请改用 Anthropic 或在外部预处理 PDF。
        """
        import base64
        from pathlib import Path

        pdf_bytes = Path(pdf_path).read_bytes()
        b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": b64,
                    },
                },
                {"type": "text", "text": text},
            ],
        })

    def add_user_with_image(self, text: str, image_path: str) -> None:
        """添加一条带图像的用户消息。两种 provider 都支持。"""
        import base64
        from pathlib import Path

        path = Path(image_path)
        ext = path.suffix.lower().lstrip(".")
        media_type_map = {
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        if ext not in media_type_map:
            raise ValueError(f"不支持的图像格式：{ext}")

        img_bytes = path.read_bytes()
        b64 = base64.standard_b64encode(img_bytes).decode("utf-8")
        self.messages.append({
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type_map[ext],
                        "data": b64,
                    },
                },
                {"type": "text", "text": text},
            ],
        })

    # ------------------------------------------------------------
    # 发送
    # ------------------------------------------------------------

    def send(
        self,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        stream: Optional[bool] = None,
        log: Optional[bool] = None,
    ) -> str:
        """发送当前 messages，自动把 assistant 回复加入历史，并返回回复文本。"""
        if not self.messages:
            raise RuntimeError(
                "Conversation 尚无消息。请先调用 add_user()。"
            )
        if self.messages[-1]["role"] != "user":
            raise RuntimeError(
                "Conversation 的最后一条消息不是 user。"
                "请检查消息添加顺序。"
            )

        reply = self.client.chat(
            messages=self.messages,
            system=self.system,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=stream,
            log=log,
        )
        self.messages.append({"role": "assistant", "content": reply})
        return reply

    # ------------------------------------------------------------
    # 工具方法
    # ------------------------------------------------------------

    def reset(self) -> None:
        """清空对话历史（保留 system prompt）。"""
        self.messages = []

    def turn_count(self) -> int:
        """返回对话轮数（每对 user+assistant 算一轮）。"""
        return len([m for m in self.messages if m["role"] == "assistant"])

    def __repr__(self) -> str:
        return (
            f"Conversation(provider={self.client.provider_name}, "
            f"turns={self.turn_count()})"
        )
