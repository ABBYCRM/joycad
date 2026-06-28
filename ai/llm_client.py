"""Unified LLM client supporting OpenAI, Anthropic, Ollama, vLLM, and OpenRouter.

We deliberately keep the surface tiny: one ``complete()`` call.
Provider-specific quirks (Anthropic's system prompt, Ollama's streaming, etc.)
are normalised inside.
"""
from __future__ import annotations

import json
import os
from typing import Any

from loguru import logger
from dotenv import load_dotenv

from .base import LLMClient, LLMMessage, LLMResponse, LLMRole, ToolSpec

load_dotenv()


# ---------------------------------------------------------------------------
# OpenAI / vLLM / OpenRouter (all OpenAI-compatible)
# ---------------------------------------------------------------------------
class OpenAICompatClient(LLMClient):
    """OpenAI Chat Completions API — also covers vLLM and OpenRouter."""

    def __init__(self, provider_label: str, base_url: str | None, api_key: str | None,
                 model: str):
        self.name = provider_label
        self._model = model
        try:
            from openai import OpenAI
        except ImportError as e:
            raise RuntimeError("openai package not installed — `pip install openai`") from e
        self._client = OpenAI(base_url=base_url, api_key=api_key or "sk-no-key")

    def complete(self, messages, *, temperature=0.2, max_tokens=4096,
                 tools=None, tool_choice="auto", json_mode=False):
        payload: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }
        oai_msgs = [
            {"role": m.role.value, "content": m.content,
             **({"name": m.name} if m.name else {}),
             **({"tool_call_id": m.tool_call_id} if m.tool_call_id else {})}
            for m in messages
        ]
        payload["messages"] = oai_msgs
        if tools:
            payload["tools"] = [
                {"type": "function",
                 "function": {"name": t.name, "description": t.description,
                              "parameters": t.parameters}}
                for t in tools
            ]
            payload["tool_choice"] = tool_choice
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        resp = self._client.chat.completions.create(**payload)
        msg = resp.choices[0].message
        tool_calls = []
        if getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                args = tc.function.arguments or "{}"
                try:
                    parsed = json.loads(args)
                except Exception:
                    parsed = {"_raw": args}
                tool_calls.append({
                    "id": tc.id,
                    "name": tc.function.name,
                    "arguments": parsed,
                })
        usage = {}
        if getattr(resp, "usage", None):
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens,
                "completion_tokens": resp.usage.completion_tokens,
                "total_tokens": resp.usage.total_tokens,
            }
        return LLMResponse(
            content=msg.content or "",
            tool_calls=tool_calls,
            usage=usage,
            raw=resp,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Anthropic Claude (Messages API)
# ---------------------------------------------------------------------------
class AnthropicClient(LLMClient):
    def __init__(self, model: str = "claude-3-5-sonnet-latest"):
        self.name = "anthropic"
        self._model = model
        try:
            from anthropic import Anthropic
        except ImportError as e:
            raise RuntimeError("anthropic package not installed") from e
        self._client = Anthropic()

    def complete(self, messages, *, temperature=0.2, max_tokens=4096,
                 tools=None, tool_choice="auto", json_mode=False):
        # Anthropic requires system prompt separately, and tool_choice differs.
        system = None
        converted = []
        for m in messages:
            if m.role == LLMRole.SYSTEM:
                system = m.content
            else:
                converted.append({"role": m.role.value, "content": m.content})
        kwargs: dict[str, Any] = {
            "model": self._model,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": converted,
        }
        if system:
            kwargs["system"] = system
        if tools:
            kwargs["tools"] = [
                {"name": t.name, "description": t.description,
                 "input_schema": t.parameters}
                for t in tools
            ]
        if json_mode:
            # Anthropic doesn't have json_mode — use tool forcing instead.
            kwargs["tools"] = kwargs.get("tools", []) + [{
                "name": "respond_json",
                "description": "Return the assistant's response as JSON.",
                "input_schema": {"type": "object", "additionalProperties": True},
            }]
            kwargs["tool_choice"] = {"type": "tool", "name": "respond_json"}
        resp = self._client.messages.create(**kwargs)
        text_parts: list[str] = []
        tool_calls: list[dict] = []
        for block in resp.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "arguments": block.input,
                })
        return LLMResponse(
            content="\n".join(text_parts),
            tool_calls=tool_calls,
            usage={"input_tokens": resp.usage.input_tokens,
                   "output_tokens": resp.usage.output_tokens},
            raw=resp,
            provider=self.name,
        )


# ---------------------------------------------------------------------------
# Ollama (local LLM via /api/chat, OpenAI-compatible since v0.1.32)
# ---------------------------------------------------------------------------
class OllamaClient(OpenAICompatClient):
    def __init__(self, model: str | None = None,
                 base_url: str = "http://localhost:11434"):
        super().__init__(
            provider_label="ollama",
            base_url=f"{base_url.rstrip('/')}/v1",
            api_key="ollama",  # ignored
            model=model or os.getenv("OLLAMA_MODEL", "llama3.1"),
        )


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------
def llm_factory(provider: str | None = None, **overrides) -> LLMClient:
    """Build the LLM client based on env / override.

    Args:
        provider: one of ``mock | openai | anthropic | ollama | vllm | openrouter``.
        **overrides: e.g. model="gpt-4o", base_url="..."
    """
    provider = (provider or os.getenv("JOYCAD_LLM_PROVIDER", "openai")).lower()

    if provider == "mock":
        from .mock_llm import MockLLMClient
        return MockLLMClient()

    if provider == "openai":
        return OpenAICompatClient(
            provider_label="openai",
            base_url=None,
            api_key=os.getenv("OPENAI_API_KEY"),
            model=overrides.get("model", "gpt-4o"),
        )
    if provider == "anthropic":
        return AnthropicClient(model=overrides.get("model",
                                                   "claude-3-5-sonnet-latest"))
    if provider == "ollama":
        return OllamaClient(
            model=overrides.get("model", os.getenv("OLLAMA_MODEL", "llama3.1")),
            base_url=overrides.get("base_url",
                                   os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")),
        )
    if provider == "vllm":
        return OpenAICompatClient(
            provider_label="vllm",
            base_url=os.getenv("VLLM_BASE_URL", "http://localhost:8000/v1"),
            api_key=os.getenv("VLLM_API_KEY", "vllm"),
            model=overrides.get("model", "meta-llama/Llama-3.1-8B-Instruct"),
        )
    if provider == "openrouter":
        return OpenAICompatClient(
            provider_label="openrouter",
            base_url="https://openrouter.ai/api/v1",
            api_key=os.getenv("OPENROUTER_API_KEY"),
            model=overrides.get("model", "anthropic/claude-3.5-sonnet"),
        )
    raise ValueError(f"Unknown LLM provider: {provider!r}")


if __name__ == "__main__":
    # smoke test
    client = llm_factory()
    out = client.complete([
        LLMMessage(LLMRole.SYSTEM, "You are terse."),
        LLMMessage(LLMRole.USER, "Reply with one word: pong"),
    ], max_tokens=10)
    print(f"[{client.name}] {out.content!r}  usage={out.usage}")
