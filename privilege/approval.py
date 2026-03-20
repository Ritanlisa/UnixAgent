#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, List, Optional, Sequence

from .privilege import Privilege

if TYPE_CHECKING:
    from agentGroup.agentGroup import AgentGroup


class ApprovalPrivilege(Privilege):
    def __init__(
        self,
        allowTargetAgentGroup: List['AgentGroup'],
        allowPrivileges: Optional[List[Privilege]] = None,
        allowAllCurrentAndFutureGroups: bool = False,
        allowAllPrivileges: bool = False,
    ):
        self.allowTargetAgentGroup = list(allowTargetAgentGroup)
        self.allowPrivileges = list(allowPrivileges or [])
        self.allowAllCurrentAndFutureGroups = allowAllCurrentAndFutureGroups
        self.allowAllPrivileges = allowAllPrivileges
        super().__init__()

    def __str__(self) -> str:
        return (
            "ApprovalPrivilege("
            f"allowTargetAgentGroup={self.allowTargetAgentGroup}, "
            f"allowPrivileges={self.allowPrivileges}, "
            f"allowAllCurrentAndFutureGroups={self.allowAllCurrentAndFutureGroups}, "
            f"allowAllPrivileges={self.allowAllPrivileges}"
            ")"
        )

    def __repr__(self) -> str:
        return self.__str__()

    @staticmethod
    def _privilege_signature(privilege: Privilege) -> str:
        return json.dumps(privilege.to_dict(), ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _privilege_scope_covers(granted: Sequence[Privilege], required: Sequence[Privilege]) -> bool:
        return all(any(owned == needed or owned > needed for owned in granted) for needed in required)

    def allows_group(self, group: 'AgentGroup') -> bool:
        return self.allowAllCurrentAndFutureGroups or group in self.allowTargetAgentGroup

    def allows_privileges(self, required_privileges: Sequence[Privilege]) -> bool:
        if self.allowAllPrivileges:
            return True
        return self._privilege_scope_covers(self.allowPrivileges, required_privileges)

    def can_approve_request(self, requester_group: 'AgentGroup', required_privileges: Sequence[Privilege]) -> bool:
        return self.allows_group(requester_group) and self.allows_privileges(required_privileges)

    def to_dict(self) -> dict:
        from agentGroup.agentGroup import AgentGroup

        return {
            "type": "ApprovalPrivilege",
            "allowTargetAgentGroup": [AgentGroup.all().index(group) for group in self.allowTargetAgentGroup],
            "allowPrivileges": [privilege.to_dict() for privilege in self.allowPrivileges],
            "allowAllCurrentAndFutureGroups": self.allowAllCurrentAndFutureGroups,
            "allowAllPrivileges": self.allowAllPrivileges,
        }

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if self.allowAllCurrentAndFutureGroups and not other.allowAllCurrentAndFutureGroups:
            return False
        if self.allowAllPrivileges and not other.allowAllPrivileges:
            return False
        if not other.allowAllCurrentAndFutureGroups and not all(group in other.allowTargetAgentGroup for group in self.allowTargetAgentGroup):
            return False
        if not other.allowAllPrivileges and not self._privilege_scope_covers(other.allowPrivileges, self.allowPrivileges):
            return False
        return self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        if other.allowAllCurrentAndFutureGroups and not self.allowAllCurrentAndFutureGroups:
            return False
        if other.allowAllPrivileges and not self.allowAllPrivileges:
            return False
        if not self.allowAllCurrentAndFutureGroups and not all(group in self.allowTargetAgentGroup for group in other.allowTargetAgentGroup):
            return False
        if not self.allowAllPrivileges and not self._privilege_scope_covers(self.allowPrivileges, other.allowPrivileges):
            return False
        return self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ApprovalPrivilege):
            return False
        return (
            self.allowAllCurrentAndFutureGroups == other.allowAllCurrentAndFutureGroups
            and self.allowAllPrivileges == other.allowAllPrivileges
            and set(self.allowTargetAgentGroup) == set(other.allowTargetAgentGroup)
            and {
                self._privilege_signature(privilege)
                for privilege in self.allowPrivileges
            }
            == {
                self._privilege_signature(privilege)
                for privilege in other.allowPrivileges
            }
        )

    def __getattr__(self, name: str) -> Any:
        if name in {
            "allowTargetAgentGroup",
            "allowPrivileges",
        }:
            return list(super().__getattribute__(name))
        if name in {
            "allowAllCurrentAndFutureGroups",
            "allowAllPrivileges",
        }:
            return super().__getattribute__(name)
        raise AttributeError(name)

    def ensurance(self) -> float:
        group_span = 10.0 if self.allowAllCurrentAndFutureGroups else float(max(len(self.allowTargetAgentGroup), 1))
        privilege_span = 12.0 if self.allowAllPrivileges else float(max(len(self.allowPrivileges), 1))
        return 8.0 + group_span * 1.5 + privilege_span * 2.0

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [
            ApprovalPrivilege(
                allowTargetAgentGroup=[],
                allowPrivileges=[],
                allowAllCurrentAndFutureGroups=True,
                allowAllPrivileges=True,
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

        allow_privileges = []
        for privilege_data in data.get("allowPrivileges", []):
            allow_privileges.append(AgentGroup._privilege_from_dict(privilege_data))

        return ApprovalPrivilege(
            allowTargetAgentGroup=target_groups,
            allowPrivileges=allow_privileges,
            allowAllCurrentAndFutureGroups=bool(data.get("allowAllCurrentAndFutureGroups", False)),
            allowAllPrivileges=bool(data.get("allowAllPrivileges", False)),
        )
    
    
    