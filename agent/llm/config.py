"""LLM 配置加载：从 agent_config.yaml + .env 读取配置。"""

from __future__ import annotations
import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel, Field, ConfigDict
from dotenv import load_dotenv

class ProviderCapabilities(BaseModel):
    supports_pdf: bool = False
    supports_image: bool = False


class ProviderConfig(BaseModel):
    """单个 provider 的配置。"""
    model_config = ConfigDict(extra="forbid")

    model: str = Field(..., description="模型名，如 'claude-sonnet-4-5'")
    api_key_env: str = Field(..., description="API key 在环境变量中的名字")
    base_url: Optional[str] = Field(
        None,
        description="OpenAI 兼容 provider 必须指定，Anthropic 可省略"
    )
    protocol: str = Field(
        "anthropic",
        description="'anthropic' 或 'openai'。决定用哪个 adapter。"
    )
    max_tokens: int = Field(4096, description="单次响应的最大 token 数")
    timeout: float = Field(120.0, description="API 请求超时时间（秒）")
    capabilities: ProviderCapabilities = Field(default_factory=ProviderCapabilities) #区分大模型的能力


    def get_api_key(self) -> str:
        """从环境变量读取 API key。"""
        key = os.environ.get(self.api_key_env)
        if not key:
            raise ValueError(
                f"环境变量 {self.api_key_env} 未设置。"
                f"请检查 .env 文件。"
            )
        return key


class LLMConfig(BaseModel):
    """整体 LLM 配置。"""
    model_config = ConfigDict(extra="forbid")

    default_provider: str
    providers: dict[str, ProviderConfig]
    use_phase_providers: bool = False
    phase_providers: dict[str, str] = Field(default_factory=dict)

    def get_provider_for_phase(self, phase: Optional[str]) -> str:
        """根据 phase 名查找应使用的 provider 名；fallback 到 default。"""
        if self.use_phase_providers and phase and phase in self.phase_providers:
            return self.phase_providers[phase]
        return self.default_provider

    def get_provider_config(self, provider_name: str) -> ProviderConfig:
        """获取指定 provider 的配置；不存在时报错。"""
        if provider_name not in self.providers:
            raise ValueError(
                f"未知的 provider '{provider_name}'。"
                f"已配置的有：{list(self.providers.keys())}"
            )
        return self.providers[provider_name]


def find_config_file(start_path: Optional[Path] = None) -> Path:
    """从指定路径开始向上查找 agent_config.yaml。
    
    这样无论从项目根目录还是 notebooks/ 子目录运行都能找到配置。
    """
    current = (start_path or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        candidate = path / "agent_config.yaml"
        if candidate.exists():
            return candidate
    raise FileNotFoundError(
        f"未找到 agent_config.yaml。从 {current} 开始向上查找均无果。"
    )


def find_dotenv(start_path: Optional[Path] = None) -> Optional[Path]:
    """同上逻辑查找 .env，找不到也不报错（.env 是可选的）。"""
    current = (start_path or Path.cwd()).resolve()
    for path in [current, *current.parents]:
        candidate = path / ".env"
        if candidate.exists():
            return candidate
    return None


def load_llm_config(
    config_path: Optional[Path] = None,
    load_env: bool = True,
) -> LLMConfig:
    """加载 LLM 配置。
    
    Args:
        config_path: 显式指定配置文件路径；None 则自动查找。
        load_env: 是否同时加载 .env 文件（推荐 True）。
    
    Returns:
        LLMConfig 对象。
    """
    if load_env:
        env_path = find_dotenv()
        if env_path:
            load_dotenv(env_path)

    if config_path is None:
        config_path = find_config_file()
    
    with open(config_path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    
    return LLMConfig.model_validate(raw)

