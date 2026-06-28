"""JoyCAD AI layer — LLM clients, prompt refinement, RAG, and tool definitions.

Public surface:
    llm_factory        →  unified LLM client (OpenAI / Anthropic / Ollama / vLLM / OpenRouter)
    PromptRefiner      →  natural-language → StructuredBrief
    CADScriptGenerator →  StructuredBrief → executable CAD script
    RAGStore           →  FAISS-backed snippet retrieval
    ToolRegistry       →  function-call definitions for tool-using LLMs
"""

from .llm_client import llm_factory, LLMClient, LLMMessage, LLMRole
from .prompt_refiner import PromptRefiner, StructuredBrief, FeatureSpec
from .cad_script_generator import CADScriptGenerator, CADScript
from .rag_store import RAGStore
from .tool_definitions import ToolRegistry

__all__ = [
    "llm_factory",
    "LLMClient",
    "LLMMessage",
    "LLMRole",
    "PromptRefiner",
    "StructuredBrief",
    "FeatureSpec",
    "CADScriptGenerator",
    "CADScript",
    "RAGStore",
    "ToolRegistry",
]
