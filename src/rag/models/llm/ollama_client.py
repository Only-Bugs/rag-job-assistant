"""
ollama_client.py
Shared LangChain Ollama client + helper to run prompts.
"""

from __future__ import annotations

import os

from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.output_parsers import StrOutputParser

from rag.config.settings import MODEL_NAME, OLLAMA_HOST_DEFAULT

OLLAMA_HOST = os.getenv("OLLAMA_HOST", OLLAMA_HOST_DEFAULT)
LLM_MODEL = os.getenv("LLM_MODEL", MODEL_NAME)

llm = ChatOllama(
    base_url=OLLAMA_HOST,
    model=LLM_MODEL,
    temperature=0.3,
)
parser = StrOutputParser()


def run_prompt(system_prompt: str, user_text: str) -> str:
    """Build a chat prompt and invoke the Ollama model."""
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", system_prompt),
            ("user", "{input}"),
        ]
    )
    chain = prompt | llm | parser
    return chain.invoke({"input": user_text})


__all__ = ["run_prompt"]
