#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from copy import deepcopy
from fnmatch import fnmatchcase
from pathlib import Path
from typing import Any, List, Optional
from privilege.privilege import Privilege


class ShellPrivilege(Privilege):
    ## ShellPrivilege represents the privilege of executing shell commands, which can be defined by a list of allowed or forbidden commands, and whether sudo is allowed.
    def __init__(self, allowSudo: bool, commandList: List[str], isWhitelist: bool=True, *args, **kwargs):
        self.allowSudo = allowSudo
        self.commandList = deepcopy(commandList)
        self.isWhitelist = isWhitelist
        super().__init__()

    def __str__(self) -> str:
        return f"ShellPrivilege(allowSudo={self.allowSudo}, commandList={self.commandList}, isWhitelist={self.isWhitelist})"

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        return {"type": "ShellPrivilege", "allowSudo": self.allowSudo, "commandList": self.commandList, "isWhitelist": self.isWhitelist}

    def __lt__(self, other: 'Privilege') -> bool: 
        # if this privilege is strictly less than the other privilege, return True; otherwise, return False
        if not isinstance(other, ShellPrivilege):
            return False
        # Sudo privileges are considered higher than non-sudo privileges
        if self.allowSudo and not other.allowSudo:
            return False
        # If one is a whitelist and the other is a blacklist, they are not comparable
        if self.isWhitelist != other.isWhitelist:
            return False
        # If both are whitelists, the one include another all commands is considered more privileged
        if self.isWhitelist and all(cmd in other.commandList for cmd in self.commandList):
            return self != other
        if not self.isWhitelist and all(cmd in self.commandList for cmd in other.commandList):
            return self != other
        return False
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ShellPrivilege):
            return False
        return self.allowSudo == other.allowSudo and self.commandList == other.commandList and self.isWhitelist == other.isWhitelist

    def __getattr__(self, name: str) -> Any:
        if name in ['allowSudo', 'commandList', 'isWhitelist']:
            return deepcopy(super().__getattribute__(name))
    
    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        if data.get("type") == "ShellPrivilege":
            return ShellPrivilege(
                allowSudo=data.get("allowSudo", False),
                commandList=data.get("commandList", []),
                isWhitelist=data.get("isWhitelist", True)
            )
        return None


class IOPrivilege(Privilege):
    ## IOPrivilege represents the privilege of performing IO operations, which can be defined by a list of allowed or forbidden file paths, and whether write operations are allowed.
    def __init__(self, allowWrite: bool, allowSudo: bool, pathList: List[Path], isWhitelist: bool=True, *args, **kwargs):
        self.allowWrite = allowWrite
        self.allowSudo = allowSudo
        self.pathList = deepcopy(pathList)
        self.isWhitelist = isWhitelist
        super().__init__()

    def __str__(self) -> str:
        return f"IOPrivilege(allowWrite={self.allowWrite}, allowSudo={self.allowSudo}, pathList={self.pathList}, isWhitelist={self.isWhitelist})"

    def __repr__(self) -> str:
        return self.__str__()

    def to_dict(self) -> dict:
        return {"type": "IOPrivilege", "allowWrite": self.allowWrite, "allowSudo": self.allowSudo, "pathList": self.pathList, "isWhitelist": self.isWhitelist}

    @staticmethod
    def _normalize_path_pattern(path: Path) -> str:
        return str(path).replace("\\", "/")

    @staticmethod
    def _contains_wildcard(segment: str) -> bool:
        return "*" in segment or "?" in segment or "[" in segment

    @staticmethod
    def _split_pattern(pattern: str) -> tuple[bool, List[str]]:
        normalized = pattern.strip()
        is_absolute = normalized.startswith("/")
        parts = [part for part in normalized.split("/") if part]
        return is_absolute, parts

    @staticmethod
    def _segment_includes(container: str, contained: str) -> bool:
        if container == contained:
            return True
        if container == "*":
            return True
        if not IOPrivilege._contains_wildcard(contained):
            return fnmatchcase(contained, container)
        return False

    @staticmethod
    def _pattern_includes(container_pattern: str, contained_pattern: str) -> bool:
        c_abs, c_parts = IOPrivilege._split_pattern(container_pattern)
        t_abs, t_parts = IOPrivilege._split_pattern(contained_pattern)

        if c_abs != t_abs:
            return False

        def _includes(ci: int, ti: int) -> bool:
            if ti == len(t_parts):
                return all(part == "**" for part in c_parts[ci:])
            if ci == len(c_parts):
                return False

            c_part = c_parts[ci]
            t_part = t_parts[ti]

            if c_part == "**":
                return _includes(ci + 1, ti) or _includes(ci, ti + 1)

            if t_part == "**":
                return False

            if IOPrivilege._segment_includes(c_part, t_part):
                return _includes(ci + 1, ti + 1)

            return False

        return _includes(0, 0)

    @staticmethod
    def _path_includes(container_path: Path, contained_path: Path) -> bool:
        container = IOPrivilege._normalize_path_pattern(container_path)
        contained = IOPrivilege._normalize_path_pattern(contained_path)
        return IOPrivilege._pattern_includes(container, contained)
    
    def __lt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, IOPrivilege):
            return False
        # Write privileges are considered higher than read-only privileges
        if self.allowWrite and not other.allowWrite:
            return False
        # Sudo privileges are considered higher than non-sudo privileges
        if self.allowSudo and not other.allowSudo:
            return False
        # If one is a whitelist and the other is a blacklist, they are not comparable
        if self.isWhitelist != other.isWhitelist:
            return False
        # If both are whitelists, the one include another all paths is considered more privileged
        if self.isWhitelist and all(any(IOPrivilege._path_includes(other_path, path) for other_path in other.pathList) for path in self.pathList):
            return self != other
        if not self.isWhitelist and all(any(IOPrivilege._path_includes(path, other_path) for path in self.pathList) for other_path in other.pathList):
            return self != other
        return False
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IOPrivilege):
            return False
        return self.allowWrite == other.allowWrite and self.allowSudo == other.allowSudo and self.pathList == other.pathList and self.isWhitelist == other.isWhitelist

    @staticmethod
    def create(data: dict) -> Optional['Privilege']:
        if data.get("type") == "IOPrivilege":
            return IOPrivilege(
                allowWrite=data.get("allowWrite", False),
                allowSudo=data.get("allowSudo", False),
                pathList=[Path(p) for p in data.get("pathList", [])],
                isWhitelist=data.get("isWhitelist", True)
            )
        return None