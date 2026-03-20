# UnixAgent 权限治理原型

这个项目实现了一个多 Agent 权限治理原型，核心特性：

- 初始 `root` Agent 拥有完整系统管理、招募与审批能力。
- 用户组（`AgentGroup`）用于承载一组配置一致的 Agent 模板。
- 权限支持下放与收回（包含 `HirePrivilege` 与 `ApprovalPrivilege`）。
- `ApprovalPrivilege` 支持按“请求来源组 + 可审批权限范围 + 是否覆盖未来组”拆分。
- `HirePrivilege` 支持按“可操作组 + 可执行治理动作 + 是否覆盖未来组”拆分。
- 所有越权动作通过 MCP 风格请求流（`MCPRequest`）评估并执行。
- 建组、改组、招募、剔除、下放权限、收回权限也可以作为治理操作走 MCP。
- 审批将请求发起者与执行者分离，并记录审计日志。
- 支持 Agent 间通信接口：对单个 Agent 发送消息、对用户组广播消息，并记录通信日志。
- 成本分为 `food_tokens`（仅统计量）、`food_cost`（按模型每百万 token 单价折算）、`budget_api`、`wage_compute`、`insurance` 四类核算维度。
- 新增 root 专属 `CostPolicy`（通过 MCP 治理操作更新），可约束总 Agent 数、单组 Agent 数、总保险成本、单 Agent 权限数。
- 新增 `ExternalToolPrivilege`，用于控制外部工具调用权限。
- 新增 `Operation` 抽象与子类（文件/Shell/外部工具），统一权限验证与执行流程。
- 每个 Agent 使用 LangChain 的 `ConversationSummaryBufferMemory` 管理记忆，并受组级上下文长度限制（`max_token_limit`）。
- Root 与模型配置外置在 `settings.yaml`，`secrets.yaml` 通过“模型名 -> `api_url` + `api_key` + `parameter_count` + `price_per_million_tokens`”进行绑定。

## 关键模块

- `agentGroup/agentGroup.py`
	- `Agent`：单个执行体，持有权限与成本台账。
	- `CostPolicy`：root 管理的全局成本约束。
	- `MessageEntry`：Agent 通信日志记录。
	- `AgentGroup`：用户组模板、成员管理、权限下放/回收。
	- `MCPRequest` / `MCPResult`：请求与执行结果。
	- `execute_via_mcp`：审批 + 执行核心流程。
	- `audit_log`：审计记录（请求者/审批者/执行者）。

- `privilege/`
	- `operations.py`：`IOPrivilege`、`ShellPrivilege`。
	- `hire.py`：`HirePrivilege` + `HireOperation`。
	- `approval.py`：`ApprovalPrivilege`。
	- `external_tool.py`：`ExternalToolPrivilege`。

- `operation.py`
	- `Operation`：操作抽象类，定义 `required_privilege`、`payload`、`execute`。
	- `FileOperation` / `ShellOperation` / `ExternalToolOperation`。
	- `CreateGroupOperation` / `UpdateGroupOperation` / `RecruitAgentOperation` / `UpdateCostPolicyOperation` 等治理操作。

- `agentGroup/memory.py`
	- LangChain `ConversationSummaryBufferMemory` 的创建与序列化辅助函数。

- `settings.yaml` / `secrets.yaml`
	- root 与可用模型名配置、模型绑定密钥配置。

## 运行演示

在项目根目录执行：

```bash
python .\main.py
```

`main.py` 现在仅作为模块入口，负责加载配置并启动 root。完整演示/测试脚本已迁移到：

```bash
python .\tmp\demo_mcp_flow.py
```

演示内容：

1. root 创建 `memberA/leaderA/memberB/leaderB` 四个组。
2. root 通过 MCP 治理操作对 leaderA、leaderB 下放分组审批权与部分执行权。
3. `memberA` 申请在 `workspaceA` 的越权操作，由 `leaderA` 审批执行。
4. `memberA` 申请 `workspaceB` 操作：
	 - 请求 `leaderA` 被拒（无对应审批+执行能力）。
	 - 请求 `root` 成功（全局审批 + 全局执行）。
5. `leaderA` 再使用自己被下放的 `HirePrivilege` 为 `memberA` 组招募新成员。
6. 输出全局成本报告与完整审计日志。
7. 演示 `Operation` 子类执行和外部工具调用权限验证。
8. 演示 Agent 记忆摘要缓冲与状态持久化后重载。
9. 演示 root 通过 MCP 更新并生效成本策略（超限时招募/授权会被拒绝）。

## 当前边界

- 系统冷启动约束：首次运行仅允许 root 组 + root Agent 初始化，其他组需在运行后由 root 招募权限创建。
- 已支持 JSON 持久化：`AgentGroup.save_state(...)` / `AgentGroup.load_state(...)`。
- 已支持可替换 MCP 执行器接口：
	- `DryRunMCPToolExecutor`：本地模拟执行（默认）。
	- `HttpMCPToolExecutor`：通过 HTTP POST 调用真实 MCP 工具端点。

## MCP 执行器接口

- 在 `agentGroup/mcp_executor.py` 中定义：
	- `MCPToolExecutor`（抽象接口）
	- `MCPExecutionResponse`（执行结果）
	- `DryRunMCPToolExecutor`（模拟执行）
	- `HttpMCPToolExecutor`（真实 HTTP MCP 调用）

配置方式：

```python
from agentGroup import AgentGroup, DryRunMCPToolExecutor

AgentGroup.configure_mcp_executor(DryRunMCPToolExecutor())
```

如需真实 MCP：

```python
from agentGroup import AgentGroup, HttpMCPToolExecutor

AgentGroup.configure_mcp_executor(HttpMCPToolExecutor(timeout_seconds=20.0))
```

说明：

- `HttpMCPToolExecutor` 会向执行 Agent 的 `api_url` 发起 POST，请求头自动带 `Authorization: Bearer <api_key>`（若配置）。
- 请求体包含 `action`、`payload`、`executor(name/group/model)`。
- 审批判定同时校验：审批者是否拥有对应组的审批域、是否拥有被请求操作的执行权、审批域是否覆盖请求权限集合。

## 外部工具调用接口

- 在 `agentGroup/mcp_executor.py` 中提供：
	- `ExternalToolCaller` 抽象接口
	- `DryRunExternalToolCaller` 默认实现
- `ExternalToolOperation` 会先走 `ExternalToolPrivilege` 权限比较，再调用 `ExternalToolCaller` 执行。

## 配置文件

- `settings.yaml`
	- root 的 system prompt、模型名、上下文上限
	- 可用模型列表
	- MCP 执行器模式
- 成本策略建议由 root 通过 `UpdateCostPolicyOperation` 统一管理并纳入审计日志。
- `secrets.yaml`
	- 模型名与 `api_url`/`api_key`/`parameter_count`/`price_per_million_tokens` 绑定（已加入 `.gitignore`，避免提交）

## 持久化

```python
from pathlib import Path
from agentGroup import AgentGroup

path = AgentGroup.save_state(Path("tmp/agent_state.json"))
AgentGroup.load_state(path)
```

保存内容：

- 用户组与组模板权限
- Agent 成员、Agent 权限与成本台账
- Agent 通信日志（单播/组播）
- root 组索引
- 审计日志

## 权限拆分语义

- `ApprovalPrivilege`
	- `allowTargetAgentGroup`：哪些组可以向自己发审批请求。
	- `allowPrivileges`：自己可以代为审批并执行的权限子集。
	- `allowAllCurrentAndFutureGroups`：是否覆盖当前和未来新增组。
	- `allowAllPrivileges`：是否覆盖所有权限类型和所有范围。

- `HirePrivilege`
	- `allowOperations`：允许的治理动作，如 `add/remove/addGroup/modifyGroup/givePrivilege`。
	- `allowTargetAgentGroup`：允许操作的组范围。
	- `allowAllCurrentAndFutureGroups`：是否覆盖当前和未来新增组。

- 这意味着“组长A对成员A有审批权，但只能审批 workspaceA 的 IO + python 运行请求”可以被精确表达，而不是通过额外白名单硬编码。
