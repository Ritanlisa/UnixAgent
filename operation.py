#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional, TYPE_CHECKING

from privilege.hire import HireOperation, HirePrivilege
from privilege.external_tool import ExternalToolPrivilege
from privilege.operations import IOPrivilege, ShellPrivilege
from privilege.privilege import Privilege

if TYPE_CHECKING:
    from agentGroup.agentGroup import Agent
    from agentGroup.mcp_executor import ExternalToolCaller, MCPExecutionResponse, MCPToolExecutor


@dataclass(slots=True)
class Operation(ABC):
    action: str

    @abstractmethod
    def required_privilege(self) -> Privilege:
        pass

    @abstractmethod
    def payload(self) -> Dict[str, Any]:
        pass

    def validate_permission(self, agent: "Agent") -> bool:
        required = self.required_privilege()
        return any((required <= owned) and (owned >= required) for owned in agent.privileges)

    def execute(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        if not self.validate_permission(executor):
            from agentGroup.mcp_executor import MCPExecutionResponse

            return MCPExecutionResponse(
                success=False,
                message="operation permission denied by privilege comparison",
                output={"action": self.action, "required": self.required_privilege().to_dict()},
            )
        return self._execute_impl(executor=executor, tool_executor=tool_executor, external_tool_caller=external_tool_caller)

    @abstractmethod
    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        pass


@dataclass(slots=True)
class FileOperation(Operation):
    target_path: Path
    write: bool = False
    sudo: bool = False

    def required_privilege(self) -> Privilege:
        return IOPrivilege(
            allowWrite=self.write,
            allowSudo=self.sudo,
            pathList=[self.target_path],
            isWhitelist=True,
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "file",
            "path": str(self.target_path),
            "write": self.write,
            "sudo": self.sudo,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        return tool_executor.execute(executor=executor, action=self.action, payload=self.payload())


@dataclass(slots=True)
class ShellOperation(Operation):
    command: str
    sudo: bool = False

    def required_privilege(self) -> Privilege:
        return ShellPrivilege(
            allowSudo=self.sudo,
            commandList=[self.command],
            isWhitelist=True,
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "shell",
            "command": self.command,
            "sudo": self.sudo,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        return tool_executor.execute(executor=executor, action=self.action, payload=self.payload())


@dataclass(slots=True)
class ExternalToolOperation(Operation):
    tool_name: str
    tool_input: Dict[str, Any]

    def required_privilege(self) -> Privilege:
        return ExternalToolPrivilege(allowTools=[self.tool_name], isWhitelist=True)

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "external_tool",
            "tool_name": self.tool_name,
            "tool_input": self.tool_input,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        if external_tool_caller is None:
            from agentGroup.mcp_executor import MCPExecutionResponse

            return MCPExecutionResponse(success=False, message="external tool caller is not configured")
        return external_tool_caller.call_tool(executor=executor, tool_name=self.tool_name, tool_input=self.tool_input)


def _success_response(message: str, **output: Any):
    from agentGroup.mcp_executor import MCPExecutionResponse

    return MCPExecutionResponse(success=True, message=message, output=output)


def _resolve_group(group_name: str):
    from agentGroup.agentGroup import AgentGroup

    group = AgentGroup.get_by_name(group_name)
    if group is None:
        raise ValueError(f"Group '{group_name}' does not exist.")
    return group


def _resolve_agent(agent_name: str):
    from agentGroup.agentGroup import AgentGroup

    for agent in AgentGroup.all_agents():
        if agent.name == agent_name:
            return agent
    raise ValueError(f"Agent '{agent_name}' does not exist.")


@dataclass(slots=True)
class CreateGroupOperation(Operation):
    group_name: str
    description: str
    system_prompt: str
    model_name: str
    context_window_limit: int = 8192

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[],
            allowOperations=[HireOperation.ADDGROUP],
            allowAllCurrentAndFutureGroups=True,
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.create_group",
            "group_name": self.group_name,
            "description": self.description,
            "system_prompt": self.system_prompt,
            "model_name": self.model_name,
            "context_window_limit": self.context_window_limit,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        group = AgentGroup.create_group(
            executor,
            name=self.group_name,
            description=self.description,
            systemPrompt=self.system_prompt,
            model_name=self.model_name,
            context_window_limit=self.context_window_limit,
        )
        return _success_response("group created", group=group.name)


@dataclass(slots=True)
class UpdateGroupOperation(Operation):
    target_group_name: str
    new_name: Optional[str] = None
    new_description: Optional[str] = None
    new_system_prompt: Optional[str] = None
    new_model_name: Optional[str] = None
    new_context_window_limit: Optional[int] = None

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[_resolve_group(self.target_group_name)],
            allowOperations=[HireOperation.MODIFYGROUP],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.update_group",
            "target_group_name": self.target_group_name,
            "new_name": self.new_name,
            "new_description": self.new_description,
            "new_system_prompt": self.new_system_prompt,
            "new_model_name": self.new_model_name,
            "new_context_window_limit": self.new_context_window_limit,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        group = _resolve_group(self.target_group_name)
        AgentGroup.update_group(
            executor,
            group,
            name=self.new_name,
            description=self.new_description,
            systemPrompt=self.new_system_prompt,
            model_name=self.new_model_name,
            context_window_limit=self.new_context_window_limit,
        )
        return _success_response("group updated", group=group.name if self.new_name is None else self.new_name)


@dataclass(slots=True)
class RemoveGroupOperation(Operation):
    target_group_name: str

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[_resolve_group(self.target_group_name)],
            allowOperations=[HireOperation.REMOVEGROUP],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.remove_group",
            "target_group_name": self.target_group_name,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        removed = AgentGroup.remove_group(executor, _resolve_group(self.target_group_name))
        return _success_response("group removed" if removed else "group removal refused", removed=removed)


@dataclass(slots=True)
class RecruitAgentOperation(Operation):
    target_group_name: str
    agent_name: str

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[_resolve_group(self.target_group_name)],
            allowOperations=[HireOperation.ADD],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.recruit_agent",
            "target_group_name": self.target_group_name,
            "agent_name": self.agent_name,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        agent = AgentGroup.recruit_agent(executor, _resolve_group(self.target_group_name), agent_name=self.agent_name)
        return _success_response("agent recruited", agent=agent.name, group=agent.group.name)


@dataclass(slots=True)
class DismissAgentOperation(Operation):
    agent_name: str

    def required_privilege(self) -> Privilege:
        agent = _resolve_agent(self.agent_name)
        return HirePrivilege(
            allowTargetAgentGroup=[agent.group],
            allowOperations=[HireOperation.REMOVE],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.dismiss_agent",
            "agent_name": self.agent_name,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        removed = AgentGroup.dismiss_agent(executor, _resolve_agent(self.agent_name))
        return _success_response("agent dismissed" if removed else "agent dismissal refused", removed=removed, agent=self.agent_name)


@dataclass(slots=True)
class DelegateGroupPrivilegeOperation(Operation):
    target_group_name: str
    privilege: Privilege

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[_resolve_group(self.target_group_name)],
            allowOperations=[HireOperation.GIVEPRIVILEGE],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.delegate_privilege",
            "target_group_name": self.target_group_name,
            "privilege": self.privilege.to_dict(),
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        AgentGroup.delegate_privilege(executor, _resolve_group(self.target_group_name), self.privilege)
        return _success_response("privilege delegated", group=self.target_group_name, privilege=self.privilege.to_dict())


@dataclass(slots=True)
class RevokeGroupPrivilegeOperation(Operation):
    target_group_name: str
    privilege: Privilege

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[_resolve_group(self.target_group_name)],
            allowOperations=[HireOperation.REVOKEPRIVILEGE],
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.revoke_privilege",
            "target_group_name": self.target_group_name,
            "privilege": self.privilege.to_dict(),
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        revoked = AgentGroup.revoke_group_privilege(executor, _resolve_group(self.target_group_name), self.privilege)
        return _success_response("privilege revoked" if revoked else "privilege revoke skipped", group=self.target_group_name, revoked=revoked)


@dataclass(slots=True)
class UpdateCostPolicyOperation(Operation):
    max_total_agents: Optional[int] = None
    max_group_agents: Optional[int] = None
    max_total_insurance: Optional[float] = None
    max_privileges_per_agent: Optional[int] = None

    def required_privilege(self) -> Privilege:
        return HirePrivilege(
            allowTargetAgentGroup=[],
            allowOperations=[HireOperation.MODIFYGROUP],
            allowAllCurrentAndFutureGroups=True,
        )

    def payload(self) -> Dict[str, Any]:
        return {
            "type": "governance.update_cost_policy",
            "max_total_agents": self.max_total_agents,
            "max_group_agents": self.max_group_agents,
            "max_total_insurance": self.max_total_insurance,
            "max_privileges_per_agent": self.max_privileges_per_agent,
        }

    def _execute_impl(self, *, executor: "Agent", tool_executor: "MCPToolExecutor", external_tool_caller: Optional["ExternalToolCaller"] = None) -> "MCPExecutionResponse":
        from agentGroup.agentGroup import AgentGroup

        policy = AgentGroup.set_cost_policy(
            executor,
            max_total_agents=self.max_total_agents,
            max_group_agents=self.max_group_agents,
            max_total_insurance=self.max_total_insurance,
            max_privileges_per_agent=self.max_privileges_per_agent,
        )
        return _success_response("cost policy updated", policy=policy.to_dict())
