"""
Shared LangChain Ollama client + helper to run prompts.

Model quantisation: this project talks to the Ollama daemon over HTTP; weights and
quant level are determined by the model tag you install (e.g. `ollama pull llama3.2:3b`).
To try a faster/smaller variant for A/B quality tests, switch `model_name` in
`rag/config/model_config.yaml` or set env `LLM_MODEL`, then revert when done.

Keep the model resident between requests: set OLLAMA_KEEP_ALIVE (e.g. `24h`) in the
environment where `ollama serve` runs so the server does not unload after each chat.
See: https://github.com/ollama/ollama/blob/main/docs/faq.md
"""

from __future__ import annotations

import os
from threading import Lock
from typing import Optional

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from rag.config.settings import LLM_MAX_TOKENS, LLM_TEMPERATURE, MODEL_NAME, OLLAMA_HOST

LLM_MODEL = os.getenv("LLM_MODEL", MODEL_NAME)

parser = StrOutputParser()

_shared_llm: Optional[ChatOllama] = None
_shared_llm_lock = Lock()


def _get_shared_chat_ollama() -> ChatOllama:
    """Single ChatOllama instance; use `.bind(num_predict=...)` per call for token limits."""
    global _shared_llm
    with _shared_llm_lock:
        if _shared_llm is None:
            _shared_llm = ChatOllama(
                base_url=OLLAMA_HOST,
                model=LLM_MODEL,
                temperature=LLM_TEMPERATURE,
            )
        return _shared_llm


def run_prompt(system_prompt: str, user_text: str, max_tokens: int | None = None) -> str:
    """Build a chat prompt, stream tokens from Ollama, and return the full reply."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )
    token_limit = max_tokens if max_tokens is not None else int(LLM_MAX_TOKENS.get("default", 512))
    llm = _get_shared_chat_ollama().bind(num_predict=token_limit)
    chain = prompt | llm | parser
    parts: list[str] = []
    for chunk in chain.stream({"input": user_text}):
        if chunk:
            parts.append(chunk if isinstance(chunk, str) else str(chunk))
    return "".join(parts)


__all__ = ["run_prompt"]
