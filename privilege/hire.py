#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from enum import Enum
from typing import Any, List, Optional

from .privilege import Privilege


class HireOperation(Enum):
    ADD = "add"
    REMOVE = "remove"
    ADDGROUP = "addGroup"
    REMOVEGROUP = "removeGroup"
    MODIFYGROUP = "modifyGroup"
    GIVEPRIVILEGE = "givePrivilege"
    REVOKEPRIVILEGE = "revokePrivilege"


class HirePrivilege(Privilege):
    def __init__(
        self,
        allowTargetAgentGroup: List['AgentGroup'],
        allowOperations: List[HireOperation],
        allowAllCurrentAndFutureGroups: bool = False,
    ):
        self.allowTargetAgentGroup = list(allowTargetAgentGroup)
        self.allowOperations = list(allowOperations)
        self.allowAllCurrentAndFutureGroups = allowAllCurrentAndFutureGroups
        super().__init__()

    def __str__(self) -> str:
        return (
            f"HirePrivilege(allowTargetAgentGroup={self.allowTargetAgentGroup}, "
            f"allowOperations={self.allowOperations}, "
            f"allowAllCurrentAndFutureGroups={self.allowAllCurrentAndFutureGroups})"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        from agentGroup.agentGroup import AgentGroup

        return {
            "type": "HirePrivilege",
            "allowTargetAgentGroup": [AgentGroup.all().index(group) for group in self.allowTargetAgentGroup],
            "allowOperations": [operation.value for operation in self.allowOperations],
            "allowAllCurrentAndFutureGroups": self.allowAllCurrentAndFutureGroups,
        }

    def allows_group(self, group: Optional['AgentGroup']) -> bool:
        if self.allowAllCurrentAndFutureGroups:
            return True
        if group is None:
            return False
        return group in self.allowTargetAgentGroup

    def allows_operation(self, operation: HireOperation | str) -> bool:
        expected = operation.value if isinstance(operation, HireOperation) else operation
        return any(item.value == expected for item in self.allowOperations)

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        if self.allowAllCurrentAndFutureGroups and not other.allowAllCurrentAndFutureGroups:
            return False
        if not all(operation in other.allowOperations for operation in self.allowOperations):
            return False
        if not other.allowAllCurrentAndFutureGroups and not all(group in other.allowTargetAgentGroup for group in self.allowTargetAgentGroup):
            return False
        return self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        if other.allowAllCurrentAndFutureGroups and not self.allowAllCurrentAndFutureGroups:
            return False
        if not all(operation in self.allowOperations for operation in other.allowOperations):
            return False
        if not self.allowAllCurrentAndFutureGroups and not all(group in self.allowTargetAgentGroup for group in other.allowTargetAgentGroup):
            return False
        return self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        return (
            self.allowAllCurrentAndFutureGroups == other.allowAllCurrentAndFutureGroups
            and
            set(self.allowTargetAgentGroup) == set(other.allowTargetAgentGroup)
            and set(self.allowOperations) == set(other.allowOperations)
        )

    def __getattr__(self, name: str) -> Any:
        if name in ["allowTargetAgentGroup", "allowOperations"]:
            return list(super().__getattribute__(name))
        if name == "allowAllCurrentAndFutureGroups":
            return super().__getattribute__(name)
        raise AttributeError(name)

    def ensurance(self) -> float:
        operation_factor = max(len(self.allowOperations), 1)
        group_factor = 10 if self.allowAllCurrentAndFutureGroups else max(len(self.allowTargetAgentGroup), 1)
        return 10.0 + operation_factor * group_factor * 1.5

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        from agentGroup.agentGroup import AgentGroup

        return [
            HirePrivilege(
                allowTargetAgentGroup=[],
                allowOperations=list(HireOperation),
                allowAllCurrentAndFutureGroups=True,
            )
        ]

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        from agentGroup.agentGroup import AgentGroup

        if data.get("type") != "HirePrivilege":
            return None

        target_groups = []
        for group_index in data.get("allowTargetAgentGroup", []):
            group = AgentGroup.get(group_index)
            if group is not None:
                target_groups.append(group)

        operations = []
        for operation in data.get("allowOperations", []):
            try:
                operations.append(HireOperation(operation))
            except ValueError:
                continue

        return HirePrivilege(
            allowTargetAgentGroup=target_groups,
            allowOperations=operations,
            allowAllCurrentAndFutureGroups=bool(data.get("allowAllCurrentAndFutureGroups", False)),
        )
    

