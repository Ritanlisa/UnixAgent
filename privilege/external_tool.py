#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, List, Optional
from .privilege import Privilege


class ExternalToolPrivilege(Privilege):
    def __init__(self, allowTools: List[str], isWhitelist: bool = True):
        normalized = sorted({tool.strip().lower() for tool in allowTools if tool.strip()})
        self.allowTools = normalized
        self.isWhitelist = isWhitelist
        super().__init__()

    def __str__(self) -> str:
        return f"ExternalToolPrivilege(allowTools={self.allowTools}, isWhitelist={self.isWhitelist})"

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        return {
            "type": "ExternalToolPrivilege",
            "allowTools": list(self.allowTools),
            "isWhitelist": self.isWhitelist,
        }

    @staticmethod
    def _set_includes(container: List[str], contained: List[str]) -> bool:
        container_set = set(container)
        return all(item in container_set for item in contained)

    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ExternalToolPrivilege):
            return False
        if self.isWhitelist != other.isWhitelist:
            return False
        if self.isWhitelist:
            return self._set_includes(other.allowTools, self.allowTools) and self != other
        return self._set_includes(self.allowTools, other.allowTools) and self != other

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, ExternalToolPrivilege):
            return False
        if self.isWhitelist != other.isWhitelist:
            return False
        if self.isWhitelist:
            return self._set_includes(self.allowTools, other.allowTools) and self != other
        return self._set_includes(other.allowTools, self.allowTools) and self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ExternalToolPrivilege):
            return False
        return set(self.allowTools) == set(other.allowTools) and self.isWhitelist == other.isWhitelist

    def __getattr__(self, name: str) -> Any:
        if name == "allowTools":
            return list(super().__getattribute__(name))
        if name == "isWhitelist":
            return super().__getattribute__(name)
        raise AttributeError(name)

    def ensurance(self) -> float:
        if self.isWhitelist:
            return 6.0 + len(self.allowTools) * 2.0
        return 28.0 - min(len(self.allowTools) * 1.2, 20.0)

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [ExternalToolPrivilege(allowTools=[], isWhitelist=False)]

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        if data.get("type") != "ExternalToolPrivilege":
            return None
        return ExternalToolPrivilege(
            allowTools=list(data.get("allowTools", [])),
            isWhitelist=bool(data.get("isWhitelist", True)),
        )
