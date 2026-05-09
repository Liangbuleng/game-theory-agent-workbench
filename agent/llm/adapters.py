"""Provider adapters with optional streaming and diagnostics."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

from agent.llm.config import ProviderConfig
from agent.llm.diagnostics import emit_log


class ProviderAdapter(ABC):
    """Base class for provider adapters."""

    def __init__(self, config: ProviderConfig):
        self.config = config

    @abstractmethod
    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        stream: bool = False,
        log: bool = False,
    ) -> str:
        ...

    def chat_with_retry(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        max_retries: int = 3,
        stream: bool = False,
        log: bool = False,
    ) -> str:
        last_error: Exception | None = None
        for attempt in range(max_retries):
            try:
                return self.chat(
                    messages=messages,
                    system=system,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    stream=stream,
                    log=log,
                )
            except Exception as error:  # noqa: BLE001
                last_error = error
                if attempt < max_retries - 1:
                    wait = 2**attempt
                    emit_log(
                        f"[LLM] call_failed attempt={attempt + 1}/{max_retries} "
                        f"{type(error).__name__}: {error}; retry_in={wait}s"
                    )
                    time.sleep(wait)
        raise RuntimeError(
            f"LLM call failed after {max_retries} attempts. "
            f"Last error: {last_error}"
        ) from last_error


class AnthropicAdapter(ProviderAdapter):
    """Adapter for Anthropic's native API."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        try:
            from anthropic import Anthropic
        except ImportError as error:
            raise ImportError("Install anthropic to use this provider.") from error

        self._client = Anthropic(
            api_key=config.get_api_key(),
            timeout=config.timeout,
        )

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        stream: bool = False,
        log: bool = False,
    ) -> str:
        # Anthropic streaming can be added later; diagnostics still tell us
        # request start/end timing for non-streaming calls.
        effective_max_tokens = max_tokens or self.config.max_tokens
        start = time.perf_counter()
        if log:
            _log_request_start(
                provider="anthropic",
                model=self.config.model,
                messages=messages,
                system=system,
                max_tokens=effective_max_tokens,
                stream=False,
            )

        response = self._client.messages.create(
            model=self.config.model,
            max_tokens=effective_max_tokens,
            temperature=temperature,
            system=system or "",
            messages=messages,
        )
        text = "".join(
            block.text for block in response.content if block.type == "text"
        )
        if log:
            _log_request_done(start=start, text=text, first_chunk_time=None)
        return text


class OpenAICompatibleAdapter(ProviderAdapter):
    """Adapter for OpenAI-compatible providers: Qwen, DeepSeek, Zhipu, etc."""

    def __init__(self, config: ProviderConfig):
        super().__init__(config)
        try:
            from openai import OpenAI
        except ImportError as error:
            raise ImportError("Install openai to use this provider.") from error

        if not config.base_url:
            raise ValueError("OpenAI-compatible providers require base_url.")

        self._client = OpenAI(
            api_key=config.get_api_key(),
            base_url=config.base_url,
            timeout=config.timeout,
        )

    def _convert_messages(
        self,
        messages: list[dict],
        system: str | None,
    ) -> list[dict]:
        converted: list[dict] = []
        if system:
            converted.append({"role": "system", "content": system})

        for message in messages:
            role = message["role"]
            content = message["content"]
            if isinstance(content, str):
                converted.append({"role": role, "content": content})
                continue

            new_content = []
            for block in content:
                block_type = block.get("type")
                if block_type == "text":
                    new_content.append({"type": "text", "text": block["text"]})
                elif block_type == "image":
                    src = block["source"]
                    if src["type"] != "base64":
                        raise ValueError("Only base64 images are supported.")
                    data_url = f"data:{src['media_type']};base64,{src['data']}"
                    new_content.append(
                        {"type": "image_url", "image_url": {"url": data_url}}
                    )
                elif block_type == "document":
                    raise ValueError(
                        "OpenAI-compatible chat does not accept native PDF "
                        "document blocks. Preprocess PDFs into text/markdown."
                    )
                else:
                    raise ValueError(f"Unknown content block type: {block_type}")
            converted.append({"role": role, "content": new_content})

        return converted

    def chat(
        self,
        messages: list[dict],
        system: str | None = None,
        max_tokens: int | None = None,
        temperature: float = 1.0,
        stream: bool = False,
        log: bool = False,
    ) -> str:
        converted = self._convert_messages(messages, system)
        effective_max_tokens = max_tokens or self.config.max_tokens
        start = time.perf_counter()

        if log:
            _log_request_start(
                provider="openai-compatible",
                model=self.config.model,
                messages=converted,
                system=None,
                max_tokens=effective_max_tokens,
                stream=stream,
            )

        if stream:
            return self._chat_streaming(
                messages=converted,
                max_tokens=effective_max_tokens,
                temperature=temperature,
                start=start,
                log=log,
            )

        response = self._client.chat.completions.create(
            model=self.config.model,
            messages=converted,
            max_tokens=effective_max_tokens,
            temperature=temperature,
        )
        text = response.choices[0].message.content or ""
        if log:
            _log_request_done(start=start, text=text, first_chunk_time=None)
        return text

    def _chat_streaming(
        self,
        *,
        messages: list[dict],
        max_tokens: int,
        temperature: float,
        start: float,
        log: bool,
    ) -> str:
        pieces: list[str] = []
        first_chunk_time: float | None = None
        last_reported_bucket = -1

        response_stream = self._client.chat.completions.create(
            model=self.config.model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        for chunk in response_stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            piece = getattr(delta, "content", None) or ""
            if not piece:
                continue

            now = time.perf_counter()
            if first_chunk_time is None:
                first_chunk_time = now
                if log:
                    emit_log(f"[LLM] first_chunk_after={now - start:.2f}s")

            pieces.append(piece)
            if log:
                total_chars = sum(len(item) for item in pieces)
                bucket = total_chars // 2000
                if total_chars < 1000 or bucket != last_reported_bucket:
                    last_reported_bucket = bucket
                    emit_log(f"[LLM] streamed_chars={total_chars}")

        text = "".join(pieces)
        if log:
            _log_request_done(
                start=start,
                text=text,
                first_chunk_time=first_chunk_time,
            )
        return text


def make_adapter(config: ProviderConfig) -> ProviderAdapter:
    protocol = config.protocol.lower()
    if protocol == "anthropic":
        return AnthropicAdapter(config)
    if protocol == "openai":
        return OpenAICompatibleAdapter(config)
    raise ValueError(
        f"Unknown protocol {config.protocol!r}. Supported: anthropic, openai."
    )


def _message_char_count(messages: list[dict], system: str | None = None) -> int:
    total = len(system or "")
    for message in messages:
        content = message.get("content", "")
        if isinstance(content, str):
            total += len(content)
        elif isinstance(content, list):
            for block in content:
                if block.get("type") == "text":
                    total += len(block.get("text", ""))
                else:
                    total += len(block.get("source", {}).get("data", ""))
    return total


def _log_request_start(
    *,
    provider: str,
    model: str,
    messages: list[dict],
    system: str | None,
    max_tokens: int,
    stream: bool,
) -> None:
    chars = _message_char_count(messages, system)
    emit_log(
        "[LLM] request_start "
        f"provider={provider} model={model} stream={stream} "
        f"input_chars={chars} approx_input_tokens={max(1, chars // 4)} "
        f"max_tokens={max_tokens}"
    )


def _log_request_done(
    *,
    start: float,
    text: str,
    first_chunk_time: float | None,
) -> None:
    elapsed = time.perf_counter() - start
    first_chunk = (
        "n/a"
        if first_chunk_time is None
        else f"{first_chunk_time - start:.2f}s"
    )
    emit_log(
        "[LLM] request_done "
        f"elapsed={elapsed:.2f}s first_chunk={first_chunk} "
        f"output_chars={len(text)} approx_output_tokens={max(1, len(text) // 4)}"
    )
