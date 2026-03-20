#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import time
from pathlib import Path
from typing import List

from agentGroup import Agent, AgentGroup, DryRunExternalToolCaller, DryRunMCPToolExecutor, MCPRequest
from config import load_settings
from operation import (
    CreateGroupOperation,
    DelegateGroupPrivilegeOperation,
    ExternalToolOperation,
    FileOperation,
    RecruitAgentOperation,
    ShellOperation,
)
from privilege import ApprovalPrivilege, ExternalToolPrivilege, HireOperation, HirePrivilege, IOPrivilege, Privilege, ShellPrivilege


def build_root_privileges() -> List[Privilege]:
    return [
        ShellPrivilege.FullPrivilege()[0],
        IOPrivilege(allowWrite=True, allowSudo=True, pathList=[Path("**")], isWhitelist=True),
        HirePrivilege(allowTargetAgentGroup=[], allowOperations=list(HireOperation), allowAllCurrentAndFutureGroups=True),
        ApprovalPrivilege(
            allowTargetAgentGroup=[],
            allowAllCurrentAndFutureGroups=True,
        ),
        ExternalToolPrivilege(allowTools=[], isWhitelist=False),
    ]


def bootstrap_system(settings_path: Path = Path("settings.yaml"), secrets_path: Path = Path("secrets.yaml")) -> Agent:
    settings, secrets = load_settings(settings_path, secrets_path)

    AgentGroup.reset_runtime_state()
    AgentGroup.configure_model_bindings(secrets.model_bindings)
    AgentGroup.configure_mcp_executor(DryRunMCPToolExecutor())
    AgentGroup.configure_external_tool_caller(DryRunExternalToolCaller())

    return AgentGroup.bootstrap_root(
        root_system_prompt=settings.root.system_prompt,
        model_name=settings.root.model_name,
        privileges=build_root_privileges(),
        root_group_name=settings.root.group_name,
        root_agent_name=settings.root.agent_name,
        context_window_limit=settings.root.context_window_limit,
    )


def dispatch(request: MCPRequest):
    result = AgentGroup.execute_via_mcp(request)
    print(result)
    return result


def ensure_group(root: Agent, *, name: str, description: str, system_prompt: str, model_name: str, context_window_limit: int) -> AgentGroup:
    existing = AgentGroup.get_by_name(name)
    if existing is not None:
        return existing
    dispatch(
        MCPRequest(
            requester=root,
            action=f"create group {name}",
            required_privileges=[],
            operation=CreateGroupOperation(
                action=f"create group {name}",
                group_name=name,
                description=description,
                system_prompt=system_prompt,
                model_name=model_name,
                context_window_limit=context_window_limit,
            ),
        )
    )
    created = AgentGroup.get_by_name(name)
    if created is None:
        raise RuntimeError(f"Group {name} should exist after creation.")
    return created


def ensure_agent(root: Agent, *, group_name: str, agent_name: str) -> Agent:
    existing = AgentGroup.get_agent_by_name(agent_name)
    if existing is not None:
        return existing
    dispatch(
        MCPRequest(
            requester=root,
            action=f"recruit {agent_name}",
            required_privileges=[],
            operation=RecruitAgentOperation(
                action=f"recruit {agent_name}",
                target_group_name=group_name,
                agent_name=agent_name,
            ),
        )
    )
    recruited = AgentGroup.get_agent_by_name(agent_name)
    if recruited is None:
        raise RuntimeError(f"Agent {agent_name} should exist after recruit.")
    return recruited


def configure_default_org(root: Agent) -> tuple[Agent, Agent]:
    root_model = root.model_name

    member_a_group = ensure_group(
        root,
        name="memberA",
        description="A组成员",
        system_prompt="执行工作任务，遇到越权通过审批流程。",
        model_name=root_model,
        context_window_limit=4096,
    )
    ensure_group(
        root,
        name="leaderA",
        description="A组组长",
        system_prompt="负责审批 memberA 组越权请求并执行。",
        model_name=root_model,
        context_window_limit=6144,
    )

    workspace_a_rw = IOPrivilege(allowWrite=True, allowSudo=False, pathList=[Path("workspaceA/**")], isWhitelist=True)
    workspace_b_rw = IOPrivilege(allowWrite=True, allowSudo=False, pathList=[Path("workspaceB/**")], isWhitelist=True)
    run_python = ShellPrivilege(allowSudo=False, commandList=["python *"], isWhitelist=True)

    for action, group_name, privilege in [
        ("delegate workspaceA rw to memberA", "memberA", workspace_a_rw),
        ("delegate workspaceA rw to leaderA", "leaderA", workspace_a_rw),
        ("delegate run python to leaderA", "leaderA", run_python),
        ("delegate scoped approval to leaderA", "leaderA", ApprovalPrivilege(allowTargetAgentGroup=[member_a_group])),
        ("delegate external tools to leaderA", "leaderA", ExternalToolPrivilege(["web-search", "repo-index"], isWhitelist=True)),
        ("delegate workspaceB rw to root only demo", "sudo", workspace_b_rw),
    ]:
        dispatch(
            MCPRequest(
                requester=root,
                action=action,
                required_privileges=[],
                operation=DelegateGroupPrivilegeOperation(
                    action=action,
                    target_group_name=group_name,
                    privilege=privilege,
                ),
            )
        )

    member_a = ensure_agent(root, group_name="memberA", agent_name="memberA-1")
    leader_a = ensure_agent(root, group_name="leaderA", agent_name="leaderA-1")
    return member_a, leader_a


def auto_process_approvals(timeout_seconds: float = 15.0) -> None:
    start = time.time()
    while True:
        pending = AgentGroup.list_approval_requests(status="pending")
        for item in pending:
            decision = AgentGroup.approve_request(
                approver=item.approver,
                request_id=item.request_id,
                accept=True,
                reason="auto-approved by runtime scheduler",
            )
            print(decision)

        unfinished = [
            item
            for item in AgentGroup.list_approval_requests()
            if item.status in {"pending", "accepted", "executing"}
        ]
        if not unfinished:
            return
        if time.time() - start > timeout_seconds:
            print("Approval processing timeout reached; unresolved requests remain.")
            return
        time.sleep(0.2)


def run_workload(root: Agent, member_a: Agent, leader_a: Agent) -> None:
    print("=== Runtime Workload ===")
    requests = [
        MCPRequest(
            requester=member_a,
            action="run tests in workspaceA",
            required_privileges=[],
            operation=ShellOperation(action="run tests in workspaceA", command="python -m pytest workspaceA/tests", sudo=False),
            estimated_food_tokens=120,
            estimated_budget_api=0.03,
            requested_approver=leader_a,
        ),
        MCPRequest(
            requester=member_a,
            action="invoke web-search tool",
            required_privileges=[],
            operation=ExternalToolOperation(
                action="invoke web-search tool",
                tool_name="web-search",
                tool_input={"query": "workspaceA test failure"},
            ),
            estimated_food_tokens=40,
            estimated_budget_api=0.02,
            requested_approver=leader_a,
        ),
        MCPRequest(
            requester=member_a,
            action="run migration in workspaceB (ask root)",
            required_privileges=[],
            operation=FileOperation(
                action="run migration in workspaceB (ask root)",
                target_path=Path("workspaceB/migrate.py"),
                write=True,
                sudo=False,
            ),
            estimated_food_tokens=160,
            estimated_budget_api=0.06,
            requested_approver=root,
        ),
    ]

    for request in requests:
        dispatch(request)

    auto_process_approvals()

    report = AgentGroup.group_cost_report(root)
    print("=== Runtime Cost Report ===")
    print(report)


def main():
    root = bootstrap_system()
    print(f"UnixAgent runtime started. root={root.name}, group={root.group.name}, agents={len(AgentGroup.all_agents())}")
    member_a, leader_a = configure_default_org(root)
    run_workload(root, member_a, leader_a)


if __name__ == "__main__":
    main()
