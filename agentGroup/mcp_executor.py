#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
import json
from typing import Any, Dict, TYPE_CHECKING
from urllib import request as urllib_request
from urllib import error as urllib_error

if TYPE_CHECKING:
    from .agentGroup import Agent


@dataclass(slots=True)
class MCPExecutionResponse:
    success: bool
    message: str
    output: Dict[str, Any] = field(default_factory=dict)


class MCPToolExecutor(ABC):
    @abstractmethod
    def execute(self, *, executor: "Agent", action: str, payload: Dict[str, Any]) -> MCPExecutionResponse:
        pass


class ExternalToolCaller(ABC):
    @abstractmethod
    def call_tool(self, *, executor: "Agent", tool_name: str, tool_input: Dict[str, Any]) -> MCPExecutionResponse:
        pass


class DryRunMCPToolExecutor(MCPToolExecutor):
    def execute(self, *, executor: "Agent", action: str, payload: Dict[str, Any]) -> MCPExecutionResponse:
        return MCPExecutionResponse(
            success=True,
            message="dry-run executor accepted request",
            output={
                "executor": executor.name,
                "group": executor.group.name,
                "action": action,
                "payload": payload,
            },
        )


class DryRunExternalToolCaller(ExternalToolCaller):
    def call_tool(self, *, executor: "Agent", tool_name: str, tool_input: Dict[str, Any]) -> MCPExecutionResponse:
        return MCPExecutionResponse(
            success=True,
            message="dry-run external tool call accepted",
            output={
                "executor": executor.name,
                "group": executor.group.name,
                "tool_name": tool_name,
                "tool_input": tool_input,
            },
        )


class HttpMCPToolExecutor(MCPToolExecutor):
    def __init__(self, timeout_seconds: float = 20.0):
        self.timeout_seconds = timeout_seconds

    def execute(self, *, executor: "Agent", action: str, payload: Dict[str, Any]) -> MCPExecutionResponse:
        body = {
            "action": action,
            "payload": payload,
            "executor": {
                "name": executor.name,
                "group": executor.group.name,
                "model_name": executor.model_name,
                "model_parameter_count": executor.model_parameter_count,
                "price_per_million_tokens": executor.price_per_million_tokens,
            },
        }

        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        api_key = executor.api_key.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        req = urllib_request.Request(executor.api_url, data=data, headers=headers, method="POST")
        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return MCPExecutionResponse(success=True, message="http executor returned empty response")
                try:
                    parsed = json.loads(raw)
                except json.JSONDecodeError:
                    return MCPExecutionResponse(success=True, message="http executor returned non-json response", output={"raw": raw})

                success = bool(parsed.get("success", True))
                message = str(parsed.get("message", "http executor response"))
                output = parsed.get("output", {})
                if not isinstance(output, dict):
                    output = {"output": output}
                return MCPExecutionResponse(success=success, message=message, output=output)
        except urllib_error.HTTPError as exc:
            return MCPExecutionResponse(success=False, message=f"http error {exc.code}: {exc.reason}")
        except urllib_error.URLError as exc:
            return MCPExecutionResponse(success=False, message=f"url error: {exc.reason}")
        except Exception as exc:
            return MCPExecutionResponse(success=False, message=f"unexpected executor error: {exc}")


class OllamaMCPToolExecutor(MCPToolExecutor):
    def __init__(self, timeout_seconds: float = 60.0, temperature: float = 0.2):
        self.timeout_seconds = timeout_seconds
        self.temperature = temperature

    @staticmethod
    def _build_prompt(action: str, payload: Dict[str, Any]) -> str:
        payload_text = json.dumps(payload, ensure_ascii=False)
        return (
            "You are an execution assistant.\n"
            "Given the requested action and payload, produce a concise execution plan and expected result.\n"
            f"Action: {action}\n"
            f"Payload: {payload_text}\n"
            "Output in plain text."
        )

    def execute(self, *, executor: "Agent", action: str, payload: Dict[str, Any]) -> MCPExecutionResponse:
        prompt = self._build_prompt(action, payload)
        body = {
            "model": executor.model_name,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.temperature,
            },
        }

        data = json.dumps(body).encode("utf-8")
        headers = {"Content-Type": "application/json"}
        req = urllib_request.Request(executor.api_url, data=data, headers=headers, method="POST")

        try:
            with urllib_request.urlopen(req, timeout=self.timeout_seconds) as response:
                raw = response.read().decode("utf-8")
                if not raw:
                    return MCPExecutionResponse(success=False, message="ollama returned empty response")
                parsed = json.loads(raw)
                text = str(parsed.get("response", "")).strip()
                return MCPExecutionResponse(
                    success=bool(parsed.get("done", True)),
                    message="ollama generation completed",
                    output={
                        "model": parsed.get("model", executor.model_name),
                        "text": text,
                        "eval_count": parsed.get("eval_count"),
                        "prompt_eval_count": parsed.get("prompt_eval_count"),
                    },
                )
        except urllib_error.HTTPError as exc:
            return MCPExecutionResponse(success=False, message=f"ollama http error {exc.code}: {exc.reason}")
        except urllib_error.URLError as exc:
            return MCPExecutionResponse(success=False, message=f"ollama url error: {exc.reason}")
        except Exception as exc:
            return MCPExecutionResponse(success=False, message=f"ollama executor error: {exc}")
