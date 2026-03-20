#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, ClassVar, Dict, Iterable, List, Optional, Sequence, Union
from pydantic import SecretStr

from .mcp_executor import DryRunExternalToolCaller, DryRunMCPToolExecutor, ExternalToolCaller, MCPToolExecutor
from .memory import ConversationSummaryBufferMemory, append_memory, create_memory, memory_from_dict, memory_to_dict
from privilege.privilege import Privilege

if TYPE_CHECKING:
    from operation import Operation


@dataclass(slots=True)
class CostLedger:
    food_tokens: int = 0
    food_cost: float = 0.0
    budget_api: float = 0.0
    wage_compute: float = 0.0
    last_wage_accrual_at: Optional[str] = None

    def total(self, insurance_cost: float) -> float:
        return self.food_cost + self.budget_api + self.wage_compute + insurance_cost


@dataclass(slots=True)
class CostPolicy:
    max_total_agents: Optional[int] = None
    max_group_agents: Optional[int] = None
    max_total_insurance: Optional[float] = None
    max_privileges_per_agent: Optional[int] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "max_total_agents": self.max_total_agents,
            "max_group_agents": self.max_group_agents,
            "max_total_insurance": self.max_total_insurance,
            "max_privileges_per_agent": self.max_privileges_per_agent,
        }

    @staticmethod
    def from_dict(data: Dict[str, Any]) -> "CostPolicy":
        return CostPolicy(
            max_total_agents=int(data["max_total_agents"]) if data.get("max_total_agents") is not None else None,
            max_group_agents=int(data["max_group_agents"]) if data.get("max_group_agents") is not None else None,
            max_total_insurance=float(data["max_total_insurance"]) if data.get("max_total_insurance") is not None else None,
            max_privileges_per_agent=(
                int(data["max_privileges_per_agent"])
                if data.get("max_privileges_per_agent") is not None
                else None
            ),
        )


@dataclass(slots=True)
class Agent:
    name: str
    group: "AgentGroup"
    systemPrompt: str
    model_name: str
    model_parameter_count: int
    price_per_million_tokens: float
    api_url: str
    api_key: SecretStr
    privileges: List[Privilege]
    memory: ConversationSummaryBufferMemory
    is_root: bool = False
    cost: CostLedger = field(default_factory=CostLedger)

    def has_privilege(self, required: Privilege) -> bool:
        return any(owned == required or owned > required for owned in self.privileges)

    def has_all_privileges(self, required_privileges: Iterable[Privilege]) -> bool:
        return all(self.has_privilege(required) for required in required_privileges)

    def insurance_cost(self) -> float:
        return sum(privilege.ensurance() for privilege in self.privileges)

    def total_cost(self) -> float:
        return self.cost.total(self.insurance_cost())

    def add_privilege(self, privilege: Privilege) -> bool:
        if self.has_privilege(privilege):
            return False
        self.privileges.append(privilege)
        return True

    def revoke_privilege(self, privilege: Privilege) -> bool:
        for index, owned in enumerate(self.privileges):
            if owned == privilege:
                del self.privileges[index]
                return True
        return False


@dataclass(slots=True)
class MCPRequest:
    requester: Agent
    action: str
    required_privileges: List[Privilege]
    payload: Dict[str, Any] = field(default_factory=dict)
    operation: Optional["Operation"] = None
    requested_approver: Optional[Agent] = None
    estimated_food_tokens: int = 0
    estimated_budget_api: float = 0.0
    estimated_wage_compute: float = 0.02

    def __post_init__(self) -> None:
        if self.operation is not None and not self.required_privileges:
            self.required_privileges = [self.operation.required_privilege()]
        if self.operation is not None and not self.payload:
            self.payload = self.operation.payload()


@dataclass(slots=True)
class MCPResult:
    approved: bool
    executed: bool
    action: str
    requester: str
    executor: Optional[str]
    approver: Optional[str]
    reason: str
    timestamp: str
    approval_request_id: Optional[str] = None
    execution_output: Optional[Dict[str, Any]] = None


@dataclass(slots=True)
class AuditEntry:
    timestamp: str
    requester: str
    approver: Optional[str]
    executor: Optional[str]
    group: str
    action: str
    approved: bool
    reason: str


@dataclass(slots=True)
class MessageEntry:
    timestamp: str
    sender: str
    sender_group: str
    recipient_type: str
    recipient: str
    delivered_to: List[str]
    content: str


@dataclass(slots=True)
class ApprovalRequestEntry:
    request_id: str
    status: str
    created_at: str
    decided_at: Optional[str]
    finished_at: Optional[str]
    requester: Agent
    approver: Agent
    request: MCPRequest
    decision_reason: str
    execution_message: Optional[str] = None
    execution_output: Optional[Dict[str, Any]] = None


class AgentGroup:
    rootGroup: ClassVar[Optional["AgentGroup"]] = None
    AgentGroups: ClassVar[List["AgentGroup"]] = []
    agents: ClassVar[List[Agent]] = []
    audit_log: ClassVar[List[AuditEntry]] = []
    message_log: ClassVar[List[MessageEntry]] = []
    approval_requests: ClassVar[Dict[str, ApprovalRequestEntry]] = {}
    approval_lock: ClassVar[threading.Lock] = threading.Lock()
    wage_rate_per_second: ClassVar[float] = 0.0001
    tool_executor: ClassVar[MCPToolExecutor] = DryRunMCPToolExecutor()
    external_tool_caller: ClassVar[ExternalToolCaller] = DryRunExternalToolCaller()
    model_bindings: ClassVar[Dict[str, Dict[str, str | int | float]]] = {}
    cost_policy: ClassVar[CostPolicy] = CostPolicy()

    @staticmethod
    def configure_model_bindings(bindings: Dict[str, Dict[str, str | int | float]]) -> None:
        AgentGroup.model_bindings = dict(bindings)

    @staticmethod
    def _resolve_model_binding(model_name: str) -> tuple[str, SecretStr, int, float]:
        binding = AgentGroup.model_bindings.get(model_name)
        if binding is None:
            raise KeyError(f"Model binding for '{model_name}' is not configured.")
        api_url = str(binding.get("api_url", ""))
        api_key = SecretStr(str(binding.get("api_key", "")))
        parameter_count = int(binding.get("parameter_count", 0))
        price_per_million_tokens = float(binding.get("price_per_million_tokens", 0.0))
        return api_url, api_key, parameter_count, price_per_million_tokens

    @staticmethod
    def configure_mcp_executor(executor: MCPToolExecutor) -> None:
        AgentGroup.tool_executor = executor

    @staticmethod
    def configure_external_tool_caller(caller: ExternalToolCaller) -> None:
        AgentGroup.external_tool_caller = caller

    @staticmethod
    def reset_runtime_state() -> None:
        AgentGroup.rootGroup = None
        AgentGroup.AgentGroups = []
        AgentGroup.agents = []
        AgentGroup.audit_log = []
        AgentGroup.message_log = []
        AgentGroup.approval_requests = {}
        AgentGroup.cost_policy = CostPolicy()

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(tz=timezone.utc).isoformat()

    @staticmethod
    def _utc_now_dt() -> datetime:
        return datetime.now(tz=timezone.utc)

    @staticmethod
    def _parse_iso_utc(value: str) -> datetime:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def all() -> List["AgentGroup"]:
        return list(AgentGroup.AgentGroups)

    @staticmethod
    def add(agentGroup: "AgentGroup") -> int:
        if agentGroup not in AgentGroup.AgentGroups:
            AgentGroup.AgentGroups.append(agentGroup)
        return AgentGroup.AgentGroups.index(agentGroup)

    @staticmethod
    def remove(agentGroup: Union["AgentGroup", int]) -> bool:
        target: Optional[AgentGroup]
        if isinstance(agentGroup, int):
            target = AgentGroup.get(agentGroup)
        elif isinstance(agentGroup, AgentGroup):
            target = agentGroup
        else:
            return False

        if target is None or target == AgentGroup.rootGroup:
            return False
        if target.members:
            return False

        try:
            AgentGroup.AgentGroups.remove(target)
            return True
        except ValueError:
            return False

    @staticmethod
    def get(agentGroup: int) -> Optional["AgentGroup"]:
        if 0 <= agentGroup < len(AgentGroup.AgentGroups):
            return AgentGroup.AgentGroups[agentGroup]
        return None

    @staticmethod
    def get_by_name(name: str) -> Optional["AgentGroup"]:
        for group in AgentGroup.AgentGroups:
            if group.name == name:
                return group
        return None

    @staticmethod
    def all_agents() -> List[Agent]:
        return list(AgentGroup.agents)

    @staticmethod
    def get_agent_by_name(name: str) -> Optional[Agent]:
        for agent in AgentGroup.agents:
            if agent.name == name:
                return agent
        return None

    @staticmethod
    def root_agent() -> Optional[Agent]:
        if AgentGroup.rootGroup is None:
            return None
        return AgentGroup.rootGroup.members[0] if AgentGroup.rootGroup.members else None

    @staticmethod
    def bootstrap_root(
        *,
        root_system_prompt: str,
        model_name: str,
        privileges: Sequence[Privilege],
        root_group_name: str = "sudo",
        root_agent_name: str = "root",
        context_window_limit: int = 8192,
    ) -> Agent:
        if AgentGroup.rootGroup is not None:
            root = AgentGroup.root_agent()
            if root is None:
                raise RuntimeError("Root group already exists but root agent is missing.")
            return root
        if AgentGroup.AgentGroups:
            raise RuntimeError("System bootstrap requires empty runtime except root initialization.")

        root_group = AgentGroup(
            name=root_group_name,
            description="Root group with full governance authority",
            systemPrompt=root_system_prompt,
            model_name=model_name,
            privileges=list(privileges),
            context_window_limit=context_window_limit,
        )
        AgentGroup.rootGroup = root_group
        AgentGroup.add(root_group)
        root_agent = root_group.recruit(name=root_agent_name, is_root=True)
        return root_agent

    @staticmethod
    def _record_audit(
        requester: Agent,
        action: str,
        approved: bool,
        reason: str,
        approver: Optional[Agent],
        executor: Optional[Agent],
    ) -> None:
        AgentGroup.audit_log.append(
            AuditEntry(
                timestamp=AgentGroup._utc_now(),
                requester=requester.name,
                approver=approver.name if approver else None,
                executor=executor.name if executor else None,
                group=requester.group.name,
                action=action,
                approved=approved,
                reason=reason,
            )
        )

    @staticmethod
    def _record_message(
        *,
        sender: Agent,
        recipient_type: str,
        recipient: str,
        delivered_to: List[str],
        content: str,
    ) -> MessageEntry:
        entry = MessageEntry(
            timestamp=AgentGroup._utc_now(),
            sender=sender.name,
            sender_group=sender.group.name,
            recipient_type=recipient_type,
            recipient=recipient,
            delivered_to=list(delivered_to),
            content=content,
        )
        AgentGroup.message_log.append(entry)
        return entry

    @staticmethod
    def send_message_to_agent(sender: Agent, recipient: Union[Agent, str], content: str) -> MessageEntry:
        recipient_agent = recipient if isinstance(recipient, Agent) else AgentGroup.get_agent_by_name(recipient)
        if recipient_agent is None:
            raise ValueError("Recipient agent does not exist.")

        message = content.strip()
        if not message:
            raise ValueError("Message content cannot be empty.")

        append_memory(sender.memory, "system", f"sent to {recipient_agent.name}: {message}")
        append_memory(recipient_agent.memory, "request", f"[from {sender.name}] {message}")

        return AgentGroup._record_message(
            sender=sender,
            recipient_type="agent",
            recipient=recipient_agent.name,
            delivered_to=[recipient_agent.name],
            content=message,
        )

    @staticmethod
    def broadcast_message_to_group(
        sender: Agent,
        target_group: Union["AgentGroup", str],
        content: str,
        include_sender: bool = False,
    ) -> MessageEntry:
        group = target_group if isinstance(target_group, AgentGroup) else AgentGroup.get_by_name(target_group)
        if group is None:
            raise ValueError("Target group does not exist.")

        message = content.strip()
        if not message:
            raise ValueError("Message content cannot be empty.")

        recipients = [member for member in group.members if include_sender or member != sender]
        delivered_names = [member.name for member in recipients]

        append_memory(sender.memory, "system", f"broadcast to group {group.name}: {message}")
        for member in recipients:
            append_memory(member.memory, "request", f"[broadcast from {sender.name}] {message}")

        return AgentGroup._record_message(
            sender=sender,
            recipient_type="group",
            recipient=group.name,
            delivered_to=delivered_names,
            content=message,
        )

    @staticmethod
    def _consume_cost(agent: Agent, food_tokens: int, budget_api: float, wage_compute: float) -> None:
        AgentGroup._accrue_wage(agent)
        safe_tokens = max(food_tokens, 0)
        agent.cost.food_tokens += safe_tokens
        agent.cost.food_cost += (float(safe_tokens) / 1_000_000.0) * max(agent.price_per_million_tokens, 0.0)
        agent.cost.budget_api += max(budget_api, 0.0)
        agent.cost.wage_compute += max(wage_compute, 0.0)

    @staticmethod
    def _accrue_wage(agent: Agent, now: Optional[datetime] = None) -> None:
        current = now or AgentGroup._utc_now_dt()
        if agent.cost.last_wage_accrual_at is None:
            agent.cost.last_wage_accrual_at = current.isoformat()
            return

        last = AgentGroup._parse_iso_utc(agent.cost.last_wage_accrual_at)
        delta_seconds = (current - last).total_seconds()
        if delta_seconds > 0:
            agent.cost.wage_compute += delta_seconds * max(AgentGroup.wage_rate_per_second, 0.0)
            agent.cost.last_wage_accrual_at = current.isoformat()

    @staticmethod
    def _accrue_wage_all() -> None:
        now = AgentGroup._utc_now_dt()
        for agent in AgentGroup.agents:
            AgentGroup._accrue_wage(agent, now=now)

    @staticmethod
    def _total_insurance_cost() -> float:
        return sum(agent.insurance_cost() for agent in AgentGroup.all_agents())

    @staticmethod
    def set_cost_policy(
        actor: Agent,
        *,
        max_total_agents: Optional[int] = None,
        max_group_agents: Optional[int] = None,
        max_total_insurance: Optional[float] = None,
        max_privileges_per_agent: Optional[int] = None,
    ) -> CostPolicy:
        if not actor.is_root:
            raise PermissionError("Only root agent can manage cost policy.")

        AgentGroup.cost_policy = CostPolicy(
            max_total_agents=max_total_agents,
            max_group_agents=max_group_agents,
            max_total_insurance=max_total_insurance,
            max_privileges_per_agent=max_privileges_per_agent,
        )
        return AgentGroup.cost_policy

    @staticmethod
    def _enforce_recruit_policy(target_group: "AgentGroup") -> None:
        policy = AgentGroup.cost_policy
        if policy.max_total_agents is not None:
            projected_total_agents = len(AgentGroup.agents) + 1
            if projected_total_agents > policy.max_total_agents:
                raise PermissionError("Cost policy violation: max_total_agents exceeded.")
        if policy.max_group_agents is not None:
            projected_group_agents = len(target_group.members) + 1
            if projected_group_agents > policy.max_group_agents:
                raise PermissionError("Cost policy violation: max_group_agents exceeded.")

    @staticmethod
    def _enforce_delegate_policy(target_group: "AgentGroup", privilege: Privilege) -> None:
        policy = AgentGroup.cost_policy

        if policy.max_privileges_per_agent is not None:
            for member in target_group.members:
                already_has = any(existing == privilege for existing in member.privileges)
                projected_privilege_count = len(member.privileges) if already_has else len(member.privileges) + 1
                if projected_privilege_count > policy.max_privileges_per_agent:
                    raise PermissionError("Cost policy violation: max_privileges_per_agent exceeded.")

        if policy.max_total_insurance is not None:
            if any(existing == privilege for existing in target_group.privileges):
                return
            projected_delta = float(len(target_group.members)) * float(privilege.ensurance())
            projected_total_insurance = AgentGroup._total_insurance_cost() + projected_delta
            if projected_delta > 0.0 and projected_total_insurance > policy.max_total_insurance:
                raise PermissionError("Cost policy violation: max_total_insurance exceeded.")

    @staticmethod
    def _can_approve_request(candidate: Agent, request: MCPRequest) -> bool:
        from privilege.approval import ApprovalPrivilege

        if candidate.is_root:
            return candidate.has_all_privileges(request.required_privileges)

        approval_privileges = [
            privilege
            for privilege in candidate.privileges
            if isinstance(privilege, ApprovalPrivilege)
        ]
        if not approval_privileges:
            return False
        if not candidate.has_all_privileges(request.required_privileges):
            return False
        return any(
            privilege.can_approve_request(request.requester.group, request.required_privileges)
            for privilege in approval_privileges
        )

    @staticmethod
    def _select_approver(request: MCPRequest) -> Optional[Agent]:
        AgentGroup._accrue_wage_all()
        candidates = AgentGroup.all_agents()
        if request.requested_approver is not None:
            return request.requested_approver if AgentGroup._can_approve_request(request.requested_approver, request) else None

        eligible = [candidate for candidate in candidates if candidate != request.requester and AgentGroup._can_approve_request(candidate, request)]
        if not eligible:
            return None

        return min(eligible, key=lambda candidate: candidate.total_cost())

    @staticmethod
    def _build_approval_message(request_id: str, request: MCPRequest, requester: Agent) -> str:
        return (
            f"approval request {request_id}: action={request.action}; "
            f"from={requester.name}/{requester.group.name}; payload={request.payload}"
        )

    @staticmethod
    def _create_approval_request(request: MCPRequest, approver: Agent) -> ApprovalRequestEntry:
        request_id = str(uuid.uuid4())
        entry = ApprovalRequestEntry(
            request_id=request_id,
            status="pending",
            created_at=AgentGroup._utc_now(),
            decided_at=None,
            finished_at=None,
            requester=request.requester,
            approver=approver,
            request=request,
            decision_reason="",
            execution_message=None,
        )
        with AgentGroup.approval_lock:
            AgentGroup.approval_requests[request_id] = entry
        AgentGroup.send_message_to_agent(
            request.requester,
            approver,
            AgentGroup._build_approval_message(request_id, request, request.requester),
        )
        return entry

    @staticmethod
    def list_approval_requests(status: Optional[str] = None) -> List[ApprovalRequestEntry]:
        with AgentGroup.approval_lock:
            requests = list(AgentGroup.approval_requests.values())
        if status is None:
            return requests
        normalized = status.strip().lower()
        return [item for item in requests if item.status.lower() == normalized]

    @staticmethod
    def get_approval_request(request_id: str) -> Optional[ApprovalRequestEntry]:
        with AgentGroup.approval_lock:
            return AgentGroup.approval_requests.get(request_id)

    @staticmethod
    def _execute_approved_request(request_id: str) -> None:
        with AgentGroup.approval_lock:
            entry = AgentGroup.approval_requests.get(request_id)
            if entry is None or entry.status != "accepted":
                return
            entry.status = "executing"

        request = entry.request
        approver = entry.approver
        requester = entry.requester

        AgentGroup._consume_cost(requester, request.estimated_food_tokens, request.estimated_budget_api, request.estimated_wage_compute)
        AgentGroup._consume_cost(approver, 0, 0.0, request.estimated_wage_compute)

        if request.operation is not None:
            execution = request.operation.execute(
                executor=approver,
                tool_executor=AgentGroup.tool_executor,
                external_tool_caller=AgentGroup.external_tool_caller,
            )
        else:
            execution = AgentGroup.tool_executor.execute(
                executor=approver,
                action=request.action,
                payload=request.payload,
            )

        final_status = "executed" if execution.success else "failed"
        reason = "approved by agent with approval + execution privileges"
        if not execution.success:
            reason = f"approved but execution failed: {execution.message}"

        AgentGroup._record_audit(
            requester=requester,
            action=request.action,
            approved=execution.success,
            reason=reason,
            approver=approver,
            executor=approver,
        )
        append_memory(requester.memory, "system", reason)
        append_memory(approver.memory, "system", f"executed delegated request: {request.action}")

        with AgentGroup.approval_lock:
            current = AgentGroup.approval_requests.get(request_id)
            if current is not None:
                current.status = final_status
                current.finished_at = AgentGroup._utc_now()
                current.execution_message = execution.message
                current.execution_output = execution.output

    @staticmethod
    def approve_request(approver: Agent, request_id: str, accept: bool, reason: str = "") -> MCPResult:
        timestamp = AgentGroup._utc_now()
        with AgentGroup.approval_lock:
            entry = AgentGroup.approval_requests.get(request_id)
            if entry is None:
                return MCPResult(
                    approved=False,
                    executed=False,
                    action="approval decision",
                    requester="",
                    executor=None,
                    approver=approver.name,
                    reason="approval request does not exist",
                    timestamp=timestamp,
                    approval_request_id=request_id,
                    execution_output=None,
                )

            if entry.status != "pending":
                return MCPResult(
                    approved=False,
                    executed=False,
                    action=entry.request.action,
                    requester=entry.requester.name,
                    executor=None,
                    approver=approver.name,
                    reason=f"approval request is not pending (current={entry.status})",
                    timestamp=timestamp,
                    approval_request_id=request_id,
                    execution_output=None,
                )

            if approver != entry.approver:
                return MCPResult(
                    approved=False,
                    executed=False,
                    action=entry.request.action,
                    requester=entry.requester.name,
                    executor=None,
                    approver=approver.name,
                    reason="only assigned approver can decide this request",
                    timestamp=timestamp,
                    approval_request_id=request_id,
                    execution_output=None,
                )

            if not AgentGroup._can_approve_request(approver, entry.request):
                return MCPResult(
                    approved=False,
                    executed=False,
                    action=entry.request.action,
                    requester=entry.requester.name,
                    executor=None,
                    approver=approver.name,
                    reason="approver no longer has required approval scope/execution privileges",
                    timestamp=timestamp,
                    approval_request_id=request_id,
                    execution_output=None,
                )

            entry.decided_at = timestamp
            entry.decision_reason = reason
            entry.status = "accepted" if accept else "rejected"

        if not accept:
            reject_reason = reason.strip() or "rejected by approver"
            AgentGroup._record_audit(
                requester=entry.requester,
                action=entry.request.action,
                approved=False,
                reason=reject_reason,
                approver=approver,
                executor=None,
            )
            append_memory(entry.requester.memory, "system", reject_reason)
            append_memory(approver.memory, "system", f"rejected approval request {request_id}: {entry.request.action}")
            with AgentGroup.approval_lock:
                current = AgentGroup.approval_requests.get(request_id)
                if current is not None:
                    current.finished_at = AgentGroup._utc_now()
            return MCPResult(
                approved=False,
                executed=False,
                action=entry.request.action,
                requester=entry.requester.name,
                executor=None,
                approver=approver.name,
                reason=reject_reason,
                timestamp=timestamp,
                approval_request_id=request_id,
                execution_output=None,
            )

        worker = threading.Thread(
            target=AgentGroup._execute_approved_request,
            args=(request_id,),
            daemon=True,
        )
        worker.start()
        accept_reason = reason.strip() or "accepted and queued for asynchronous execution"
        append_memory(approver.memory, "system", f"accepted approval request {request_id}: {entry.request.action}")
        append_memory(entry.requester.memory, "system", accept_reason)
        return MCPResult(
            approved=True,
            executed=False,
            action=entry.request.action,
            requester=entry.requester.name,
            executor=approver.name,
            approver=approver.name,
            reason=accept_reason,
            timestamp=timestamp,
            approval_request_id=request_id,
            execution_output=None,
        )

    @staticmethod
    def execute_via_mcp(request: MCPRequest) -> MCPResult:
        requester = request.requester
        timestamp = AgentGroup._utc_now()
        AgentGroup._accrue_wage_all()

        append_memory(requester.memory, "request", f"{request.action} | payload={request.payload}")

        if request.operation is not None and not request.operation.validate_permission(requester):
            if request.requested_approver is not None and not AgentGroup._can_approve_request(request.requested_approver, request):
                reason = "requested approver does not have both approval scope and execution privileges"
                AgentGroup._record_audit(
                    requester=requester,
                    action=request.action,
                    approved=False,
                    reason=reason,
                    approver=request.requested_approver,
                    executor=None,
                )
                append_memory(requester.memory, "system", reason)
                return MCPResult(
                    approved=False,
                    executed=False,
                    action=request.action,
                    requester=requester.name,
                    executor=None,
                    approver=request.requested_approver.name,
                    reason=reason,
                    timestamp=timestamp,
                    execution_output=None,
                )

            approver_for_operation = AgentGroup._select_approver(request)
            if approver_for_operation is None:
                reason = "operation denied: requester lacks permission and no approver found"
                AgentGroup._record_audit(
                    requester=requester,
                    action=request.action,
                    approved=False,
                    reason=reason,
                    approver=None,
                    executor=None,
                )
                append_memory(requester.memory, "system", reason)
                return MCPResult(
                    approved=False,
                    executed=False,
                    action=request.action,
                    requester=requester.name,
                    executor=None,
                    approver=None,
                    reason=reason,
                    timestamp=timestamp,
                    execution_output=None,
                )

        if requester.has_all_privileges(request.required_privileges):
            AgentGroup._consume_cost(requester, request.estimated_food_tokens, request.estimated_budget_api, request.estimated_wage_compute)
            if request.operation is not None:
                execution = request.operation.execute(
                    executor=requester,
                    tool_executor=AgentGroup.tool_executor,
                    external_tool_caller=AgentGroup.external_tool_caller,
                )
            else:
                execution = AgentGroup.tool_executor.execute(
                    executor=requester,
                    action=request.action,
                    payload=request.payload,
                )
            execute_reason = "requester already has required privileges"
            if not execution.success:
                execute_reason = f"execution failed: {execution.message}"
            AgentGroup._record_audit(
                requester=requester,
                action=request.action,
                approved=execution.success,
                reason=execute_reason,
                approver=None,
                executor=requester,
            )
            append_memory(requester.memory, "system", execute_reason)
            return MCPResult(
                approved=True,
                executed=execution.success,
                action=request.action,
                requester=requester.name,
                executor=requester.name,
                approver=None,
                reason=execute_reason,
                timestamp=timestamp,
                execution_output=execution.output,
            )

        approver = AgentGroup._select_approver(request)
        if approver is None:
            reason = "no approver has both approval authority and required execution privileges"
            AgentGroup._record_audit(
                requester=requester,
                action=request.action,
                approved=False,
                reason=reason,
                approver=None,
                executor=None,
            )
            return MCPResult(
                approved=False,
                executed=False,
                action=request.action,
                requester=requester.name,
                executor=None,
                approver=None,
                reason=reason,
                timestamp=timestamp,
                execution_output=None,
            )

        approval_entry = AgentGroup._create_approval_request(request, approver)
        reason = f"approval request created and sent to approver (request_id={approval_entry.request_id})"
        AgentGroup._record_audit(
            requester=requester,
            action=request.action,
            approved=False,
            reason=reason,
            approver=approver,
            executor=None,
        )
        append_memory(requester.memory, "system", reason)
        return MCPResult(
            approved=False,
            executed=False,
            action=request.action,
            requester=requester.name,
            executor=None,
            approver=approver.name,
            reason=reason,
            timestamp=timestamp,
            approval_request_id=approval_entry.request_id,
            execution_output=None,
        )

    @staticmethod
    def _privilege_from_dict(data: Dict[str, Any]) -> Privilege:
        from privilege.approval import ApprovalPrivilege
        from privilege.external_tool import ExternalToolPrivilege
        from privilege.hire import HirePrivilege
        from privilege.operations import IOPrivilege, ShellPrivilege

        for privilege_cls in (ShellPrivilege, IOPrivilege, HirePrivilege, ApprovalPrivilege, ExternalToolPrivilege):
            privilege = privilege_cls.create(data)
            if privilege is not None:
                return privilege
        raise ValueError(f"Unsupported privilege payload: {data}")

    @staticmethod
    def save_state(path: Union[str, Path]) -> Path:
        def _json_safe(value: Any) -> Any:
            if isinstance(value, Path):
                return str(value)
            if isinstance(value, dict):
                return {str(k): _json_safe(v) for k, v in value.items()}
            if isinstance(value, list):
                return [_json_safe(item) for item in value]
            if isinstance(value, tuple):
                return [_json_safe(item) for item in value]
            if isinstance(value, (str, int, float, bool)) or value is None:
                return value
            return str(value)

        target = Path(path)
        if not target.parent.exists():
            target.parent.mkdir(parents=True, exist_ok=True)

        groups_payload: List[Dict[str, Any]] = []
        for group in AgentGroup.AgentGroups:
            groups_payload.append(
                {
                    "name": group.name,
                    "description": group.description,
                    "systemPrompt": group.systemPrompt,
                    "model_name": group.model_name,
                    "context_window_limit": group.context_window_limit,
                    "privileges": [_json_safe(privilege.to_dict()) for privilege in group.privileges],
                }
            )

        agents_payload: List[Dict[str, Any]] = []
        for agent in AgentGroup.agents:
            agents_payload.append(
                {
                    "name": agent.name,
                    "group": AgentGroup.AgentGroups.index(agent.group),
                    "systemPrompt": agent.systemPrompt,
                    "model_name": agent.model_name,
                    "model_parameter_count": agent.model_parameter_count,
                    "price_per_million_tokens": agent.price_per_million_tokens,
                    "is_root": agent.is_root,
                    "privileges": [_json_safe(privilege.to_dict()) for privilege in agent.privileges],
                    "memory": memory_to_dict(agent.memory),
                    "cost": {
                        "food_tokens": agent.cost.food_tokens,
                        "food_cost": agent.cost.food_cost,
                        "budget_api": agent.cost.budget_api,
                        "wage_compute": agent.cost.wage_compute,
                        "last_wage_accrual_at": agent.cost.last_wage_accrual_at,
                    },
                }
            )

        payload = {
            "root_group": AgentGroup.AgentGroups.index(AgentGroup.rootGroup) if AgentGroup.rootGroup in AgentGroup.AgentGroups else None,
            "cost_policy": AgentGroup.cost_policy.to_dict(),
            "groups": groups_payload,
            "agents": agents_payload,
            "message_log": [
                {
                    "timestamp": entry.timestamp,
                    "sender": entry.sender,
                    "sender_group": entry.sender_group,
                    "recipient_type": entry.recipient_type,
                    "recipient": entry.recipient,
                    "delivered_to": list(entry.delivered_to),
                    "content": entry.content,
                }
                for entry in AgentGroup.message_log
            ],
            "audit_log": [
                {
                    "timestamp": entry.timestamp,
                    "requester": entry.requester,
                    "approver": entry.approver,
                    "executor": entry.executor,
                    "group": entry.group,
                    "action": entry.action,
                    "approved": entry.approved,
                    "reason": entry.reason,
                }
                for entry in AgentGroup.audit_log
            ],
        }

        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return target

    @staticmethod
    def load_state(path: Union[str, Path]) -> None:
        source = Path(path)
        payload = json.loads(source.read_text(encoding="utf-8"))

        AgentGroup.reset_runtime_state()

        loaded_groups: List[AgentGroup] = []
        for group_data in payload.get("groups", []):
            group = AgentGroup(
                name=group_data["name"],
                description=group_data.get("description", ""),
                systemPrompt=group_data.get("systemPrompt", ""),
                model_name=group_data.get("model_name", group_data.get("model", "")),
                context_window_limit=int(group_data.get("context_window_limit", 8192)),
                privileges=[],
            )
            AgentGroup.add(group)
            loaded_groups.append(group)

        for group, group_data in zip(loaded_groups, payload.get("groups", []), strict=False):
            group.privileges = [
                AgentGroup._privilege_from_dict(privilege_data)
                for privilege_data in group_data.get("privileges", [])
            ]

        root_group_index = payload.get("root_group")
        if isinstance(root_group_index, int):
            AgentGroup.rootGroup = AgentGroup.get(root_group_index)

        cost_policy_data = payload.get("cost_policy")
        if isinstance(cost_policy_data, dict):
            AgentGroup.cost_policy = CostPolicy.from_dict(cost_policy_data)

        for agent_data in payload.get("agents", []):
            group_index = int(agent_data["group"])
            group = AgentGroup.get(group_index)
            if group is None:
                continue

            cost_data = agent_data.get("cost", {})
            model_name = agent_data.get("model_name", group.model_name)
            resolved_api_url, resolved_api_key, resolved_parameter_count, resolved_price_per_million_tokens = AgentGroup._resolve_model_binding(model_name)
            agent = Agent(
                name=agent_data["name"],
                group=group,
                systemPrompt=agent_data.get("systemPrompt", group.systemPrompt),
                model_name=model_name,
                model_parameter_count=int(agent_data.get("model_parameter_count", resolved_parameter_count)),
                price_per_million_tokens=float(agent_data.get("price_per_million_tokens", resolved_price_per_million_tokens)),
                api_url=resolved_api_url,
                api_key=resolved_api_key,
                privileges=[
                    AgentGroup._privilege_from_dict(privilege_data)
                    for privilege_data in agent_data.get("privileges", [])
                ],
                memory=memory_from_dict(agent_data.get("memory", {"max_token_limit": group.context_window_limit})),
                is_root=bool(agent_data.get("is_root", False)),
                cost=CostLedger(
                    food_tokens=int(cost_data.get("food_tokens", 0)),
                    food_cost=float(cost_data.get("food_cost", 0.0)),
                    budget_api=float(cost_data.get("budget_api", 0.0)),
                    wage_compute=float(cost_data.get("wage_compute", 0.0)),
                    last_wage_accrual_at=cost_data.get("last_wage_accrual_at"),
                ),
            )
            group.members.append(agent)
            AgentGroup.agents.append(agent)

        AgentGroup.audit_log = [
            AuditEntry(
                timestamp=entry_data["timestamp"],
                requester=entry_data["requester"],
                approver=entry_data.get("approver"),
                executor=entry_data.get("executor"),
                group=entry_data["group"],
                action=entry_data["action"],
                approved=bool(entry_data["approved"]),
                reason=entry_data["reason"],
            )
            for entry_data in payload.get("audit_log", [])
        ]

        AgentGroup.message_log = [
            MessageEntry(
                timestamp=entry_data["timestamp"],
                sender=entry_data["sender"],
                sender_group=entry_data.get("sender_group", ""),
                recipient_type=entry_data.get("recipient_type", "agent"),
                recipient=entry_data["recipient"],
                delivered_to=list(entry_data.get("delivered_to", [])),
                content=entry_data.get("content", ""),
            )
            for entry_data in payload.get("message_log", [])
        ]

    @staticmethod
    def group_cost_report(requester: Agent) -> Dict[str, Any]:
        if not requester.is_root:
            raise PermissionError("Only root agent can manage global cost reports.")

        AgentGroup._accrue_wage_all()

        details = []
        total = 0.0
        for agent in AgentGroup.all_agents():
            agent_total = agent.total_cost()
            total += agent_total
            details.append(
                {
                    "agent": agent.name,
                    "group": agent.group.name,
                    "food_tokens": agent.cost.food_tokens,
                    "food_cost": round(agent.cost.food_cost, 6),
                    "budget_api": round(agent.cost.budget_api, 4),
                    "wage_compute": round(agent.cost.wage_compute, 4),
                    "insurance": round(agent.insurance_cost(), 4),
                    "model_parameter_count": agent.model_parameter_count,
                    "price_per_million_tokens": agent.price_per_million_tokens,
                    "total": round(agent_total, 4),
                }
            )
        return {"generatedAt": AgentGroup._utc_now(), "total": round(total, 4), "agents": details}

    def __init__(
        self,
        name: str,
        description: str,
        systemPrompt: str,
        model_name: str,
        privileges: List[Privilege],
        context_window_limit: int = 8192,
    ):
        self.name = name
        self.description = description
        self.systemPrompt = systemPrompt
        self.model_name = model_name
        self.context_window_limit = context_window_limit
        self.privileges = list(privileges)
        self.members: List[Agent] = []

    def recruit(self, name: str, is_root: bool = False) -> Agent:
        api_url, api_key, parameter_count, price_per_million_tokens = AgentGroup._resolve_model_binding(self.model_name)
        agent = Agent(
            name=name,
            group=self,
            systemPrompt=self.systemPrompt,
            model_name=self.model_name,
            model_parameter_count=parameter_count,
            price_per_million_tokens=price_per_million_tokens,
            api_url=api_url,
            api_key=api_key,
            privileges=list(self.privileges),
            memory=create_memory(max_token_limit=self.context_window_limit),
            is_root=is_root,
            cost=CostLedger(last_wage_accrual_at=AgentGroup._utc_now()),
        )
        self.members.append(agent)
        AgentGroup.agents.append(agent)
        return agent

    def dismiss(self, agent: Agent) -> bool:
        if agent.is_root:
            return False
        if agent not in self.members:
            return False

        self.members.remove(agent)
        if agent in AgentGroup.agents:
            AgentGroup.agents.remove(agent)
        return True

    def calculateCost(self) -> float:
        return sum(member.total_cost() for member in self.members)

    def update_template_privileges(self, privileges: Sequence[Privilege]) -> None:
        self.privileges = list(privileges)

    @staticmethod
    def _require_hire_privilege(actor: Agent, target_group: Optional["AgentGroup"], operation_value: str) -> None:
        from privilege.hire import HirePrivilege

        if actor.is_root:
            return

        for privilege in actor.privileges:
            if not isinstance(privilege, HirePrivilege):
                continue
            if not privilege.allows_operation(operation_value):
                continue
            if target_group is None and not privilege.allowAllCurrentAndFutureGroups:
                continue
            if target_group is not None and not privilege.allows_group(target_group):
                continue
            return
        raise PermissionError("Actor does not own required hire privilege for this target group and operation.")

    @staticmethod
    def create_group(
        actor: Agent,
        *,
        name: str,
        description: str,
        systemPrompt: str,
        model_name: str,
        context_window_limit: int = 8192,
    ) -> "AgentGroup":
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, None, HireOperation.ADDGROUP.value)

        if AgentGroup.get_by_name(name) is not None:
            raise ValueError(f"Group '{name}' already exists.")

        group = AgentGroup(
            name=name,
            description=description,
            systemPrompt=systemPrompt,
            model_name=model_name,
            context_window_limit=context_window_limit,
            privileges=[],
        )
        AgentGroup.add(group)
        return group

    @staticmethod
    def update_group(
        actor: Agent,
        target_group: "AgentGroup",
        *,
        name: Optional[str] = None,
        description: Optional[str] = None,
        systemPrompt: Optional[str] = None,
        model_name: Optional[str] = None,
        context_window_limit: Optional[int] = None,
    ) -> "AgentGroup":
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, target_group, HireOperation.MODIFYGROUP.value)

        if name is not None and name != target_group.name:
            if AgentGroup.get_by_name(name) is not None:
                raise ValueError(f"Group '{name}' already exists.")
            target_group.name = name
        if description is not None:
            target_group.description = description
        if systemPrompt is not None:
            target_group.systemPrompt = systemPrompt
            for member in target_group.members:
                member.systemPrompt = systemPrompt
        if model_name is not None:
            api_url, api_key, parameter_count, price_per_million_tokens = AgentGroup._resolve_model_binding(model_name)
            target_group.model_name = model_name
            for member in target_group.members:
                member.model_name = model_name
                member.model_parameter_count = parameter_count
                member.price_per_million_tokens = price_per_million_tokens
                member.api_url = api_url
                member.api_key = api_key
        if context_window_limit is not None:
            target_group.context_window_limit = int(context_window_limit)
            for member in target_group.members:
                member.memory.max_token_limit = int(context_window_limit)
        return target_group

    @staticmethod
    def remove_group(actor: Agent, target_group: "AgentGroup") -> bool:
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, target_group, HireOperation.REMOVEGROUP.value)
        return AgentGroup.remove(target_group)

    @staticmethod
    def recruit_agent(actor: Agent, target_group: "AgentGroup", *, agent_name: str) -> Agent:
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, target_group, HireOperation.ADD.value)
        AgentGroup._enforce_recruit_policy(target_group)
        return target_group.recruit(name=agent_name)

    @staticmethod
    def dismiss_agent(actor: Agent, agent: Agent) -> bool:
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, agent.group, HireOperation.REMOVE.value)
        return agent.group.dismiss(agent)

    @staticmethod
    def delegate_privilege(actor: Agent, target_group: "AgentGroup", privilege: Privilege) -> None:
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, target_group, HireOperation.GIVEPRIVILEGE.value)
        if (not actor.is_root) and (not actor.has_privilege(privilege)):
            raise PermissionError("Actor cannot delegate privilege that it does not possess.")

        AgentGroup._enforce_delegate_policy(target_group, privilege)

        if any(existing == privilege for existing in target_group.privileges):
            return
        target_group.privileges.append(privilege)
        for member in target_group.members:
            member.add_privilege(privilege)

    @staticmethod
    def revoke_group_privilege(actor: Agent, target_group: "AgentGroup", privilege: Privilege) -> bool:
        from privilege.hire import HireOperation

        AgentGroup._require_hire_privilege(actor, target_group, HireOperation.REVOKEPRIVILEGE.value)
        for index, existing in enumerate(target_group.privileges):
            if existing == privilege:
                del target_group.privileges[index]
                for member in target_group.members:
                    member.revoke_privilege(privilege)
                return True
        return False