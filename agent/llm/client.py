"""LLMClient: 对外的统一接口。"""

from __future__ import annotations
import os
from typing import Optional

from agent.llm.config import LLMConfig, load_llm_config
from agent.llm.adapters import ProviderAdapter, make_adapter


class LLMClient:
    """统一的 LLM 客户端。
    
    使用示例：
    
        # 用默认 provider
        client = LLMClient()
        reply = client.chat(messages=[{"role": "user", "content": "你好"}])
        
        # 用特定 provider
        client = LLMClient(provider="deepseek")
        
        # 按 phase 选 provider（从 phase_providers 配置查）
        client = LLMClient(phase="parser")
        
        # 一次性问答（不维护对话历史）
        reply = client.ask("用一句话解释博弈论。")
    """

    def __init__(
        self,
        provider: Optional[str] = None,
        phase: Optional[str] = None,
        config: Optional[LLMConfig] = None,
    ):
        """
        Args:
            provider: 显式指定 provider 名（覆盖 phase 和 default）。
            phase: 阶段名，从 phase_providers 配置查 provider。
            config: 显式传入配置；None 则自动加载 agent_config.yaml。
        """
        self.config: LLMConfig = config or load_llm_config()

        if provider:
            self.provider_name = provider
        elif phase:
            self.provider_name = self.config.get_provider_for_phase(phase)
        else:
            self.provider_name = self.config.default_provider

        self.provider_config = self.config.get_provider_config(
            self.provider_name
        )
        self.adapter: ProviderAdapter = make_adapter(self.provider_config)

    # ------------------------------------------------------------
    # 单次调用
    # ------------------------------------------------------------

    def chat(
        self,
        messages: list[dict],
        system: Optional[str] = None,
        max_tokens: Optional[int] = None,
        temperature: float = 1.0,
        max_retries: int = 3,
        stream: bool | None = None,
        log: bool | None = None,
    ) -> str:
        """发送一组 messages，返回 assistant 的回复文本。
        
        messages 格式：
            [
                {"role": "user", "content": "..."},
                {"role": "assistant", "content": "..."},
                ...
            ]
        
        多模态 content 见 adapters.py 顶部注释。
        """
        use_stream = _env_flag("GTA_LLM_STREAM") if stream is None else stream
        use_log = _env_flag("GTA_LLM_LOG") if log is None else log
        return self.adapter.chat_with_retry(
            messages=messages,
            system=system,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
            stream=use_stream,
            log=use_log,
        )

    def ask(
        self,
        prompt: str,
        system: Optional[str] = None,
        **kwargs,
    ) -> str:
        """一次性问答的便捷方法（无对话历史）。"""
        return self.chat(
            messages=[{"role": "user", "content": prompt}],
            system=system,
            **kwargs,
        )

    # ------------------------------------------------------------
    # 多轮对话
    # ------------------------------------------------------------

    def new_conversation(
        self,
        system: Optional[str] = None,
    ) -> "Conversation":
        """开启一个多轮对话。"""
        # 延迟导入避免循环依赖
        from agent.llm.conversation import Conversation
        return Conversation(client=self, system=system)

    # ------------------------------------------------------------
    # 信息
    # ------------------------------------------------------------

    def info(self) -> str:
        """返回当前使用的 provider/model 信息（便于调试）。"""
        return (
            f"LLMClient(provider={self.provider_name}, "
            f"model={self.provider_config.model})"
        )


def _env_flag(name: str) -> bool:
    value = os.environ.get(name, "")
    return value.lower() in {"1", "true", "yes", "on"}
