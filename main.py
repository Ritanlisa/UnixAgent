#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import logging
import pprint
import json
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Any

from agentGroup import Agent, AgentGroup, DryRunExternalToolCaller, DryRunMCPToolExecutor, MCPRequest, OllamaMCPToolExecutor
from agentGroup.memory import append_memory, build_context
from config import Secrets, Settings, load_settings
from operation import CreateGroupOperation, DelegateGroupPrivilegeOperation, RecruitAgentOperation, RevokeGroupPrivilegeOperation
from privilege import ApprovalPrivilege, ExternalToolPrivilege, HireOperation, HirePrivilege, IOPrivilege, Privilege, ShellPrivilege


LOGGER = logging.getLogger("unixagent.runtime")


def configure_runtime_logger() -> Path:
    log_dir = Path("log")
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"runtime-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"

    LOGGER.setLevel(logging.INFO)
    LOGGER.handlers.clear()
    LOGGER.propagate = False

    formatter = logging.Formatter("%(asctime)s | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S")

    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    LOGGER.addHandler(file_handler)

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    LOGGER.addHandler(stream_handler)

    return log_path


def format_mcp_result(result) -> str:
    output_preview = "none"
    if result.execution_output:
        output_preview = pprint.pformat(result.execution_output, sort_dicts=False, width=120)
    return (
        f"MCPResult | action={result.action} | requester={result.requester} | approver={result.approver} "
        f"| executor={result.executor} | approved={result.approved} | executed={result.executed} "
        f"| request_id={result.approval_request_id} | reason={result.reason} | output={output_preview}"
    )


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


def bootstrap_system(settings: Settings, secrets: Secrets) -> Agent:

    AgentGroup.reset_runtime_state()
    AgentGroup.configure_model_bindings(secrets.model_bindings)
    root_binding = secrets.model_bindings.get(settings.root.model_name, {})
    root_api_url = str(root_binding.get("api_url", ""))
    if "localhost:11434" in root_api_url:
        AgentGroup.configure_mcp_executor(OllamaMCPToolExecutor())
    else:
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


def _render_prompt(template: str, **kwargs: Any) -> str:
    rendered = template
    for key, value in kwargs.items():
        rendered = rendered.replace("{" + key + "}", str(value))
    return rendered


def ask_agent_llm(agent: Agent, *, action: str, payload: Dict[str, Any]) -> str:
    execution = AgentGroup.tool_executor.execute(
        executor=agent,
        action=action,
        payload=payload,
    )
    output = execution.output or {}
    text = str(output.get("text", "")).strip()
    if text:
        append_memory(agent.memory, "assistant", text)
        LOGGER.info("AgentReply | agent=%s | action=%s | text=%s", agent.name, action, text)
    else:
        LOGGER.info("AgentReply | agent=%s | action=%s | no-text-output", agent.name, action)
    return text


def _extract_json(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.startswith("json"):
            candidate = candidate[4:].strip()
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
        return {}
    except json.JSONDecodeError:
        return {}


def dispatch(request: MCPRequest):
    result = AgentGroup.execute_via_mcp(request)
    LOGGER.info(format_mcp_result(result))
    return result


def _build_privilege_from_plan(item: Dict[str, Any]) -> Privilege | None:
    privilege_payload = item.get("privilege")
    if isinstance(privilege_payload, dict):
        return AgentGroup._privilege_from_dict(privilege_payload)

    privilege_type = str(item.get("privilege_type", "")).strip().lower()
    if not privilege_type:
        return None

    if privilege_type == "io":
        raw_paths = item.get("paths", ["**"])
        paths = raw_paths if isinstance(raw_paths, list) else [raw_paths]
        return IOPrivilege(
            allowWrite=bool(item.get("allow_write", False)),
            allowSudo=bool(item.get("allow_sudo", False)),
            pathList=[Path(str(path_value)) for path_value in paths if str(path_value).strip()],
            isWhitelist=bool(item.get("is_whitelist", True)),
        )

    if privilege_type == "shell":
        raw_commands = item.get("commands", ["*"])
        commands = raw_commands if isinstance(raw_commands, list) else [raw_commands]
        return ShellPrivilege(
            allowSudo=bool(item.get("allow_sudo", False)),
            commandList=[str(command) for command in commands if str(command).strip()],
            isWhitelist=bool(item.get("is_whitelist", True)),
        )

    if privilege_type == "external_tool":
        raw_tools = item.get("tools", [])
        tools = raw_tools if isinstance(raw_tools, list) else [raw_tools]
        return ExternalToolPrivilege(
            allowTools=[str(tool_name) for tool_name in tools if str(tool_name).strip()],
            isWhitelist=bool(item.get("is_whitelist", True)),
        )

    return None


def _resolve_pending_request_id_for_actor(actor: Agent, target: str) -> str:
    pending = [entry for entry in AgentGroup.list_approval_requests(status="pending") if entry.approver == actor]
    if not pending:
        return ""

    if target:
        direct = AgentGroup.get_approval_request(target)
        if direct is not None and direct.approver == actor and direct.status == "pending":
            return target

        by_group = [entry for entry in pending if entry.requester.group.name == target]
        if by_group:
            return by_group[-1].request_id

    return pending[-1].request_id


def _generate_agent_name_for_group(group_name: str) -> str:
    base = f"{group_name}-agent"
    existing_names = {agent.name for agent in AgentGroup.all_agents()}
    if base not in existing_names:
        return base
    index = 2
    while f"{base}-{index}" in existing_names:
        index += 1
    return f"{base}-{index}"


def _execute_mcp_plan(actor: Agent, parsed: Dict[str, Any]) -> None:
    plan = parsed.get("mcp_plan", [])
    if not isinstance(plan, list):
        return

    for index, item in enumerate(plan):
        if not isinstance(item, dict):
            continue

        action = str(item.get("action", "")).strip().lower()
        target = str(item.get("target", "")).strip()
        reason = str(item.get("reason", "auto plan")).strip() or "auto plan"

        try:
            if action == "create_group":
                if not target:
                    LOGGER.warning("MCPPlan | actor=%s | index=%s | create_group skipped: empty target", actor.name, index)
                    continue
                operation = CreateGroupOperation(
                    action=f"create group {target}",
                    group_name=target,
                    description=str(item.get("description", "")),
                    system_prompt=str(item.get("system_prompt", "")),
                    model_name=str(item.get("model_name", actor.model_name)),
                    context_window_limit=int(item.get("context_window_limit", 4096)),
                )
                dispatch(MCPRequest(requester=actor, action=operation.action, required_privileges=[], operation=operation))
                continue

            if action == "recruit_agent":
                group_name = str(item.get("group_name", target)).strip()
                agent_name = str(item.get("agent_name", "")).strip()
                if not group_name:
                    LOGGER.warning("MCPPlan | actor=%s | index=%s | recruit_agent skipped: group_name missing", actor.name, index)
                    continue
                if not agent_name:
                    agent_name = _generate_agent_name_for_group(group_name)
                operation = RecruitAgentOperation(
                    action=f"recruit {agent_name}",
                    target_group_name=group_name,
                    agent_name=agent_name,
                )
                dispatch(MCPRequest(requester=actor, action=operation.action, required_privileges=[], operation=operation))
                continue

            if action in {"delegate_privilege", "revoke_privilege"}:
                privilege = _build_privilege_from_plan(item)
                if not target or privilege is None:
                    LOGGER.warning("MCPPlan | actor=%s | index=%s | %s skipped: target/privilege missing", actor.name, index, action)
                    continue
                if action == "delegate_privilege":
                    operation = DelegateGroupPrivilegeOperation(
                        action=f"delegate privilege to {target}",
                        target_group_name=target,
                        privilege=privilege,
                    )
                else:
                    operation = RevokeGroupPrivilegeOperation(
                        action=f"revoke privilege from {target}",
                        target_group_name=target,
                        privilege=privilege,
                    )
                dispatch(MCPRequest(requester=actor, action=operation.action, required_privileges=[], operation=operation))
                continue

            if action in {"approve_request", "reject_request"}:
                request_id = str(item.get("request_id", "")).strip()
                if not request_id:
                    request_id = _resolve_pending_request_id_for_actor(actor, target)
                if not request_id:
                    LOGGER.warning("MCPPlan | actor=%s | index=%s | %s skipped: no pending request found", actor.name, index, action)
                    continue
                result = AgentGroup.approve_request(
                    approver=actor,
                    request_id=request_id,
                    accept=(action == "approve_request"),
                    reason=reason,
                )
                LOGGER.info(format_mcp_result(result))
                continue

            LOGGER.warning("MCPPlan | actor=%s | index=%s | unsupported action=%s", actor.name, index, action)
        except Exception as error:
            LOGGER.exception("MCPPlan | actor=%s | index=%s | action=%s | failed=%s", actor.name, index, action, error)


def handle_one_pending_approval(agent: Agent, settings: Settings) -> bool:
    pending = [item for item in AgentGroup.list_approval_requests(status="pending") if item.approver == agent]
    if not pending:
        return False

    item = pending[0]
    request_text = (
        f"request_id={item.request_id}; requester={item.requester.name}; action={item.request.action}; "
        f"payload={item.request.payload}"
    )
    prompt = _render_prompt(
        settings.runtime.prompts.approval_prompt_template,
        system_prompt=agent.systemPrompt,
        request_text=request_text,
    )
    text = ask_agent_llm(
        agent,
        action="approval decision",
        payload={"prompt": prompt},
    )
    parsed = _extract_json(text)
    decision_raw = str(parsed.get("decision", "approve")).strip().lower()
    accept = decision_raw in {"approve", "approved", "accept", "yes", "true", "1"}
    reason = str(parsed.get("reason", "model decision"))

    result = AgentGroup.approve_request(
        approver=agent,
        request_id=item.request_id,
        accept=accept,
        reason=reason,
    )
    LOGGER.info(format_mcp_result(result))

    compressed = _render_prompt(
        settings.runtime.prompts.approval_memory_compact_template,
        decision_verb="批准" if accept else "拒绝",
        requester_name=item.requester.name,
        request_action=item.request.action,
        reason=reason,
    )
    append_memory(agent.memory, "system", compressed)
    LOGGER.info("ApprovalMemoryCompact | agent=%s | text=%s", agent.name, compressed)
    return True


def run_agent_todo_step(agent: Agent, todo_board: Dict[str, List[str]], settings: Settings) -> bool:
    todos = todo_board.get(agent.name, [])
    if not todos:
        return False

    prompt = _render_prompt(
        settings.runtime.prompts.todo_prompt_template,
        system_prompt=agent.systemPrompt,
        todos_json=json.dumps(todos, ensure_ascii=False),
        memory_summary=build_context(agent.memory),
    )
    text = ask_agent_llm(agent, action="todo loop", payload={"prompt": prompt})
    parsed = _extract_json(text)

    if not parsed:
        LOGGER.warning("TodoStep | agent=%s | failed to parse JSON response; keep todos unchanged", agent.name)
        return True

    reply = str(parsed.get("assistant_reply", "")).strip()
    if reply:
        append_memory(agent.memory, "assistant", reply)

    _execute_mcp_plan(agent, parsed)

    done_indexes_raw = parsed.get("done_indexes", [])
    done_indexes: List[int] = []
    if isinstance(done_indexes_raw, list):
        for value in done_indexes_raw:
            if isinstance(value, int):
                done_indexes.append(value)

    remaining = [todo for index, todo in enumerate(todos) if index not in set(done_indexes)]

    append_todos_raw = parsed.get("append_todos", [])
    if isinstance(append_todos_raw, list):
        for value in append_todos_raw:
            if isinstance(value, str) and value.strip():
                remaining.append(value.strip())

    assign_todos_raw = parsed.get("assign_todos", {})
    if isinstance(assign_todos_raw, dict):
        for target_agent_name, target_todos in assign_todos_raw.items():
            if not isinstance(target_agent_name, str):
                continue
            if not isinstance(target_todos, list):
                continue

            targets: List[Agent] = []
            target_agent = AgentGroup.get_agent_by_name(target_agent_name)
            if target_agent is not None:
                targets = [target_agent]
            else:
                target_group = AgentGroup.get_by_name(target_agent_name)
                if target_group is not None and target_group.members:
                    targets = list(target_group.members)

            if not targets:
                LOGGER.warning("TodoAssign | from=%s | target=%s | ignored=agent-or-group-not-found", agent.name, target_agent_name)
                continue

            valid_todos: List[str] = []
            for todo in target_todos:
                if isinstance(todo, str) and todo.strip():
                    valid_todos.append(todo.strip())

            if not valid_todos:
                continue

            for target in targets:
                bucket = todo_board.setdefault(target.name, [])
                bucket.extend(valid_todos)

            LOGGER.info(
                "TodoAssign | from=%s | target=%s | resolved=%s | todos=%s",
                agent.name,
                target_agent_name,
                [target.name for target in targets],
                valid_todos,
            )

    todo_board[agent.name] = remaining
    LOGGER.info("TodoStep | agent=%s | todos_now=%s", agent.name, remaining)
    return True


def run_agent_loop(root: Agent, todo_board: Dict[str, List[str]], settings: Settings) -> None:
    max_rounds = settings.runtime.max_rounds
    for round_index in range(1, max_rounds + 1):
        LOGGER.info("=== AgentLoop Round %s ===", round_index)
        did_work = False

        agents = [root] + [agent for agent in AgentGroup.all_agents() if agent != root]
        for agent in agents:
            if handle_one_pending_approval(agent, settings):
                did_work = True
                continue

            if run_agent_todo_step(agent, todo_board, settings):
                did_work = True

        for item in AgentGroup.list_approval_requests():
            if item.status in {"executed", "failed", "rejected"}:
                LOGGER.info(
                    "ApprovalFinal | request_id=%s | status=%s | action=%s | approver=%s | message=%s | output=%s",
                    item.request_id,
                    item.status,
                    item.request.action,
                    item.approver.name,
                    item.execution_message,
                    pprint.pformat(item.execution_output, sort_dicts=False, width=120) if item.execution_output else "none",
                )

        unfinished_approvals = [
            item for item in AgentGroup.list_approval_requests() if item.status in {"pending", "accepted", "executing"}
        ]
        has_todos = any(todo_board.get(agent.name, []) for agent in agents)

        if not unfinished_approvals and not has_todos:
            LOGGER.info("Agent loop finished: no pending approvals and no todos.")
            return

        if not did_work:
            LOGGER.warning("Agent loop made no progress in round %s; stopping to avoid dead loop.", round_index)
            return

        time.sleep(0.2)

    LOGGER.warning("Agent loop reached max rounds (%s).", max_rounds)


def run_runtime(root: Agent, settings: Settings) -> None:
    LOGGER.info("=== Runtime Loop ===")
    if not settings.runtime.initial_root_todos:
        raise ReferenceError("initial_root_todos is empty; please set at least one initial TODO for the root agent to start the runtime loop")
    initial_root_todos = settings.runtime.initial_root_todos
    todo_board: Dict[str, List[str]] = {
        root.name: initial_root_todos,
    }

    run_agent_loop(root, todo_board, settings)

    report = AgentGroup.group_cost_report(root)
    LOGGER.info("=== Runtime Cost Report ===")
    LOGGER.info("\n%s", pprint.pformat(report, sort_dicts=False, width=120))


def main():
    settings_path = Path("settings.yaml")
    secrets_path = Path("secrets.yaml")
    settings, secrets = load_settings(settings_path, secrets_path)

    log_path = configure_runtime_logger()
    root = bootstrap_system(settings, secrets)
    LOGGER.info("UnixAgent runtime started. root=%s, group=%s, agents=%s", root.name, root.group.name, len(AgentGroup.all_agents()))
    LOGGER.info("Log file: %s", log_path)
    run_runtime(root, settings)


if __name__ == "__main__":
    main()
