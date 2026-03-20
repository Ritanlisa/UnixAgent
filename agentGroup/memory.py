#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, List

from langchain_classic.memory import ConversationSummaryBufferMemory
from langchain_community.llms.fake import FakeListLLM
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage


class LocalCountingFakeLLM(FakeListLLM):
    def get_num_tokens(self, text: str) -> int:
        return max(1, len(text) // 4)

    def get_num_tokens_from_messages(self, messages: List[BaseMessage], tools: Any | None = None) -> int:
        return sum(self.get_num_tokens(str(message.content)) for message in messages)


def create_memory(max_token_limit: int) -> ConversationSummaryBufferMemory:
    llm = LocalCountingFakeLLM(responses=["summary"])  # deterministic + local token counting
    return ConversationSummaryBufferMemory(
        llm=llm,
        max_token_limit=max_token_limit,
        return_messages=False,
        memory_key="history",
        input_key="input",
        output_key="output",
    )


def append_memory(memory: ConversationSummaryBufferMemory, role: str, content: str) -> None:
    if role == "request" or role == "human" or role == "user":
        memory.save_context({"input": content}, {"output": ""})
    elif role == "system":
        memory.chat_memory.add_message(SystemMessage(content=content))
    else:
        memory.chat_memory.add_message(AIMessage(content=content))


def build_context(memory: ConversationSummaryBufferMemory) -> str:
    data = memory.load_memory_variables({})
    history = data.get("history", "")
    if isinstance(history, str):
        return history
    return str(history)


def memory_to_dict(memory: ConversationSummaryBufferMemory) -> dict:
    messages: List[Dict[str, str]] = []
    for message in memory.chat_memory.messages:
        msg_type = getattr(message, "type", "unknown")
        messages.append({"type": msg_type, "content": str(message.content)})

    return {
        "max_token_limit": int(memory.max_token_limit),
        "moving_summary_buffer": str(memory.moving_summary_buffer),
        "messages": messages,
    }


def memory_from_dict(data: Dict[str, Any]) -> ConversationSummaryBufferMemory:
    memory = create_memory(int(data.get("max_token_limit", 1024)))
    memory.moving_summary_buffer = str(data.get("moving_summary_buffer", ""))

    for item in data.get("messages", []):
        msg_type = str(item.get("type", "")).lower()
        content = str(item.get("content", ""))
        if msg_type in ("human", "user"):
            memory.chat_memory.add_message(HumanMessage(content=content))
        elif msg_type in ("system",):
            memory.chat_memory.add_message(SystemMessage(content=content))
        else:
            memory.chat_memory.add_message(AIMessage(content=content))

    return memory
