#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import TYPE_CHECKING, Any, List, Optional, Sequence

from .privilege import Privilege

if TYPE_CHECKING:
    from agentGroup.agentGroup import AgentGroup


class ApprovalPrivilege(Privilege):
    def __init__(
        self,
        allowTargetAgentGroup: List['AgentGroup'],
        allowAllCurrentAndFutureGroups: bool = False,
    ):
        self.allowTargetAgentGroup = list(allowTargetAgentGroup)
        self.allowAllCurrentAndFutureGroups = allowAllCurrentAndFutureGroups
        super().__init__()

    def __str__(self) -> str:
        return (
            "ApprovalPrivilege("
            f"allowTargetAgentGroup={self.allowTargetAgentGroup}, "
            f"allowAllCurrentAndFutureGroups={self.allowAllCurrentAndFutureGroups}"
            ")"
        )

    def __repr__(self) -> str:
        return self.__str__()

    def allows_group(self, group: 'AgentGroup') -> bool:
        return self.allowAllCurrentAndFutureGroups or group in self.allowTargetAgentGroup

    def can_approve_request(self, requester_group: 'AgentGroup', required_privileges: Sequence[Privilege]) -> bool:
        _ = required_privileges
        return self.allows_group(requester_group)

    def to_dict(self) -> dict:
        from agentGroup.agentGroup import AgentGroup

        return {
            "type": "ApprovalPrivilege",
            "allowTargetAgentGroup": [AgentGroup.all().index(group) for group in self.allowTargetAgentGroup],
            "allowAllCurrentAndFutureGroups": self.allowAllCurrentAndFutureGroups,
        }

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if self.allowAllCurrentAndFutureGroups and not other.allowAllCurrentAndFutureGroups:
            return False
        if not other.allowAllCurrentAndFutureGroups and not all(group in other.allowTargetAgentGroup for group in self.allowTargetAgentGroup):
            return False
        return self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if other.allowAllCurrentAndFutureGroups and not self.allowAllCurrentAndFutureGroups:
            return False
        if not self.allowAllCurrentAndFutureGroups and not all(group in self.allowTargetAgentGroup for group in other.allowTargetAgentGroup):
            return False
        return self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        return (
            self.allowAllCurrentAndFutureGroups == other.allowAllCurrentAndFutureGroups
            and set(self.allowTargetAgentGroup) == set(other.allowTargetAgentGroup)
        )

    def __getattr__(self, name: str) -> Any:
        if name in {
            "allowTargetAgentGroup",
        }:
            return list(super().__getattribute__(name))
        if name in {
            "allowAllCurrentAndFutureGroups",
        }:
            return super().__getattribute__(name)
        raise AttributeError(name)

    def ensurance(self) -> float:
        group_span = 10.0 if self.allowAllCurrentAndFutureGroups else float(max(len(self.allowTargetAgentGroup), 1))
        return 8.0 + group_span * 1.5

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [
            ApprovalPrivilege(
                allowTargetAgentGroup=[],
                allowAllCurrentAndFutureGroups=True,
            )
        ]

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        from agentGroup.agentGroup import AgentGroup

        if data.get("type") != "ApprovalPrivilege":
            return None

        target_groups = []
        for group_index in data.get("allowTargetAgentGroup", []):
            group = AgentGroup.get(group_index)
            if group is not None:
                target_groups.append(group)

        return ApprovalPrivilege(
            allowTargetAgentGroup=target_groups,
            allowAllCurrentAndFutureGroups=bool(data.get("allowAllCurrentAndFutureGroups", False)),
        )
    
    
    