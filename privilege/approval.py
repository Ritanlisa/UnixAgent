#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import Any, List, Optional
from .privilege import Privilege
from agentGroup import AgentGroup


class ApprovalPrivilege(Privilege):
    def __init__(
            self,
            allowTargetAgentGroup: List[AgentGroup],
            ):
        self.allowTargetAgentGroup = list(allowTargetAgentGroup)
        super().__init__()

    def __str__(self) -> str:
        return f"ApprovalPrivilege(allowTargetAgentGroup={self.allowTargetAgentGroup})"

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        return {
            "type": "ApprovalPrivilege",
            "allowTargetAgentGroup": [AgentGroup.all().index(group) for group in self.allowTargetAgentGroup],
        }

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if not all(group in other.allowTargetAgentGroup for group in self.allowTargetAgentGroup):
            return False
        return self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if not all(group in self.allowTargetAgentGroup for group in other.allowTargetAgentGroup):
            return False
        return self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        return self.allowTargetAgentGroup == other.allowTargetAgentGroup

    def __getattr__(self, name: str) -> Any:
        if name == "allowTargetAgentGroup":
            return list(super().__getattribute__(name))
        raise AttributeError(name)

    def ensurance(self) -> float:
        return super().ensurance()

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [
            ApprovalPrivilege(
                allowTargetAgentGroup=AgentGroup.all(),
            )
        ]

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        if data.get("type") != "ApprovalPrivilege":
            return None

        target_groups = []
        for group_index in data.get("allowTargetAgentGroup", []):
            group = AgentGroup.get(group_index)
            if group is not None:
                target_groups.append(group)

        return ApprovalPrivilege(
            allowTargetAgentGroup=target_groups,
        )
    
    
    