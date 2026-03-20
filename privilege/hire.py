#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from enum import Enum
from typing import Any, List, Optional
from .privilege import Privilege
from agentGroup import AgentGroup

class HireOperation(Enum):
    ADD = "add"
    REMOVE = "remove"
    ADDGROUP = "addGroup"
    REMOVEGROUP = "removeGroup"
    GIVEPRIVILEGE = "givePrivilege"
    REVOKEPRIVILEGE = "revokePrivilege"

class HirePrivilege(Privilege):
    def __init__(
            self,
            allowTargetAgentGroup: List[AgentGroup],
            allowOperations: List[HireOperation],
            ):
        self.allowTargetAgentGroup = list(allowTargetAgentGroup)
        self.allowOperations = list(allowOperations)
        super().__init__()

    def __str__(self) -> str:
        return (
            f"HirePrivilege(allowTargetAgentGroup={self.allowTargetAgentGroup}, "
            f"allowOperations={self.allowOperations})"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        return {
            "type": "HirePrivilege",
            "allowTargetAgentGroup": [AgentGroup.all().index(group) for group in self.allowTargetAgentGroup],
            "allowOperations": [operation.value for operation in self.allowOperations],
        }

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        if not all(operation in other.allowOperations for operation in self.allowOperations):
            return False
        if not all(group in other.allowTargetAgentGroup for group in self.allowTargetAgentGroup):
            return False
        return self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        if not all(operation in self.allowOperations for operation in other.allowOperations):
            return False
        if not all(group in self.allowTargetAgentGroup for group in other.allowTargetAgentGroup):
            return False
        return self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, HirePrivilege):
            return False
        return (
            self.allowTargetAgentGroup == other.allowTargetAgentGroup
            and self.allowOperations == other.allowOperations
        )

    def __getattr__(self, name: str) -> Any:
        if name in ["allowTargetAgentGroup", "allowOperations"]:
            return list(super().__getattribute__(name))
        raise AttributeError(name)

    def ensurance(self) -> float:
        return super().ensurance()

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [
            HirePrivilege(
                allowTargetAgentGroup=AgentGroup.all(),
                allowOperations=list(HireOperation),
            )
        ]

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
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
        )
    

