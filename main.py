#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
from typing import List

from agentGroup import Agent, AgentGroup, DryRunExternalToolCaller, DryRunMCPToolExecutor
from config import load_settings
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


def main():
    root = bootstrap_system()
    print(f"UnixAgent started. root={root.name}, group={root.group.name}, agents={len(AgentGroup.all_agents())}")
    print("Demo/Test flow moved to tmp/demo_mcp_flow.py")


if __name__ == "__main__":
    main()
