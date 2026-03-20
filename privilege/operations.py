#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from copy import deepcopy
from fnmatch import fnmatchcase
import os
from pathlib import Path
import sys
from typing import Any, List, Mapping, Optional
from .privilege import Privilege


class ShellPrivilege(Privilege):
    ## ShellPrivilege represents the privilege of executing shell commands, which can be defined by a list of allowed or forbidden commands, and whether sudo is allowed.
    def __init__(
            self, 
            allowSudo: bool, 
            commandList: List[str], 
            isWhitelist: bool=True, 
            ):
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

    @staticmethod
    def _contains_wildcard(segment: str) -> bool:
        return "*" in segment or "?" in segment or "[" in segment

    @staticmethod
    def _normalize_command_pattern(command: str) -> str:
        normalized = " ".join(command.strip().lower().split())
        if not normalized:
            return ""

        parts = normalized.split(" ")
        head = parts[0].rstrip("/\\")
        parts[0] = head.split("/")[-1].split("\\")[-1]
        return " ".join(parts)

    @staticmethod
    def _command_includes(container_pattern: str, contained_pattern: str) -> bool:
        container = ShellPrivilege._normalize_command_pattern(container_pattern)
        contained = ShellPrivilege._normalize_command_pattern(contained_pattern)
        if not container or not contained:
            return False
        if container == contained:
            return True
        if not ShellPrivilege._contains_wildcard(contained):
            return fnmatchcase(contained, container)
        return False

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
        if self.isWhitelist and all(any(ShellPrivilege._command_includes(other_cmd, cmd) for other_cmd in other.commandList) for cmd in self.commandList):
            return self != other
        if not self.isWhitelist and all(any(ShellPrivilege._command_includes(cmd, other_cmd) for cmd in self.commandList) for other_cmd in other.commandList):
            return self != other
        return False

    def __gt__(self, other: 'Privilege') -> bool:
        # if this privilege strictly includes the other privilege, return True; otherwise, return False
        if not isinstance(other, ShellPrivilege):
            return False
        # Non-sudo privileges cannot strictly include sudo privileges
        if not self.allowSudo and other.allowSudo:
            return False
        # If one is a whitelist and the other is a blacklist, they are not comparable
        if self.isWhitelist != other.isWhitelist:
            return False
        # If both are whitelists, this must include all commands from other
        if self.isWhitelist and all(any(ShellPrivilege._command_includes(cmd, other_cmd) for cmd in self.commandList) for other_cmd in other.commandList):
            return self != other
        # If both are blacklists, this must blacklist no more than other
        if not self.isWhitelist and all(any(ShellPrivilege._command_includes(other_cmd, cmd) for other_cmd in other.commandList) for cmd in self.commandList):
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
    def _normalize_command(command: str) -> str:
        return ShellPrivilege._normalize_command_pattern(command)

    @staticmethod
    def _resolve_command_risk(command: str, risk_dict: Mapping[str, float | int], default_risk: float = 10.0) -> float:
        normalized = ShellPrivilege._normalize_command(command)
        if not normalized:
            return 0.0

        candidates = [
            float(risk)
            for cmd, risk in risk_dict.items()
            if fnmatchcase(normalized, cmd)
            or (ShellPrivilege._contains_wildcard(normalized) and fnmatchcase(cmd, normalized))
        ]
        if candidates:
            return max(candidates)

        primary = normalized.split(" ", 1)[0]
        primary_risk = risk_dict.get(primary)
        if primary_risk is not None:
            return float(primary_risk)

        return default_risk
    
    def ensurance(self) -> float:
        # list all volunerable paths and assign risk values, then calculate the average risk as the ensurance cost of this privilege. The more paths and the higher risk, the higher ensurance cost.
        if sys.platform.startswith('win'):
            risk_dict = {
                "powershell": 25.0,
                "powershell *": 30.0,
                "powershell *-executionpolicy*": 60.0,
                "cmd": 25.0,
                "cmd /c*": 30.0,
                "reg": 40.0,
                "reg add*": 55.0,
                "sc": 40.0,
                "sc *": 45.0,
                "net": 30.0,
            }
        elif sys.platform.startswith('linux'):
            risk_dict = {
                "rm": 20,
                "rm *": 25,
                "rm -rf*": 80,
                "mv": 15,
                "cp": 10,
                "chmod": 30,
                "chmod 777*": 50,
                "chown": 35,
                "sudo": 100,
                "sudo *": 100,
                "dd": 45,
            }
        elif sys.platform.startswith('darwin'):
            risk_dict = {
                "rm": 20.0,
                "rm *": 25.0,
                "rm -rf*": 80.0,
                "mv": 15.0,
                "cp": 10.0,
                "chmod": 30.0,
                "chmod 777*": 50.0,
                "chown": 35.0,
                "sudo": 100.0,
                "sudo *": 100.0,
            }
        else:
            raise OSError("Unsupported operating system for ShellPrivilege ensurance calculation.")
        
        # security_score relies on specific privileges
        security_score = 0.1
        if self.allowSudo:
            security_score *= 100.0 # Sudo privileges are considered much higher risk than non-sudo privileges

        normalized_commands = {
            ShellPrivilege._normalize_command(command)
            for command in self.commandList
            if ShellPrivilege._normalize_command(command)
        }
        command_risks = [ShellPrivilege._resolve_command_risk(command, risk_dict, default_risk=10.0) for command in normalized_commands]

        if self.isWhitelist:
            base_risk = sum(command_risks)
        else:
            baseline_unrestricted = 80.0
            blocked_reduction = sum(command_risks) * 0.6
            base_risk = max(5.0, baseline_unrestricted - blocked_reduction)

        return base_risk * security_score

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        return [ShellPrivilege(allowSudo=True, commandList=[], isWhitelist=False)]

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
    def __init__(
            self, 
            allowWrite: bool, 
            allowSudo: bool, 
            pathList: List[Path], 
            isWhitelist: bool=True
            ):
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

    @staticmethod
    def _existing_windows_drive_letters() -> List[str]:
        letters: List[str] = []
        for drive in range(ord('A'), ord('Z') + 1):
            letter = chr(drive)
            if os.path.exists(f"{letter}:\\"):
                letters.append(letter)
        return letters

    @staticmethod
    def _expand_path_pattern(path_pattern: str) -> List[str]:
        normalized = path_pattern.strip().replace("\\", "/")
        if not normalized:
            return []

        if sys.platform.startswith('win') and normalized.startswith("[A-Z]:"):
            suffix = normalized[len("[A-Z]:"):]
            return [f"{letter}:{suffix}" for letter in IOPrivilege._existing_windows_drive_letters()]

        return [normalized]

    @staticmethod
    def _expand_paths_for_scoring(path_list: List[Path]) -> List[str]:
        expanded: List[str] = []
        seen: set[str] = set()
        for path in path_list:
            pattern = IOPrivilege._normalize_path_pattern(path)
            for candidate in IOPrivilege._expand_path_pattern(pattern):
                if candidate not in seen:
                    seen.add(candidate)
                    expanded.append(candidate)
        return expanded

    @staticmethod
    def _resolve_path_risk(path: Path, risk_dict: Mapping[str, float | int], default_risk: float = 10.0) -> float:
        path_pattern = IOPrivilege._normalize_path_pattern(path)
        best_risk = 0.0

        for risk_pattern, risk in risk_dict.items():
            if (
                IOPrivilege._pattern_includes(path_pattern, risk_pattern)
                or IOPrivilege._pattern_includes(risk_pattern, path_pattern)
            ):
                best_risk = max(best_risk, float(risk))

        if best_risk > 0.0:
            return best_risk

        for risk_pattern, risk in risk_dict.items():
            if fnmatchcase(path_pattern, risk_pattern) or fnmatchcase(risk_pattern, path_pattern):
                best_risk = max(best_risk, float(risk))

        if best_risk > 0.0:
            return best_risk

        return default_risk
    
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

    def __gt__(self, other: 'Privilege') -> bool:
        if not isinstance(other, IOPrivilege):
            return False
        # Read-only privileges cannot strictly include write privileges
        if not self.allowWrite and other.allowWrite:
            return False
        # Non-sudo privileges cannot strictly include sudo privileges
        if not self.allowSudo and other.allowSudo:
            return False
        # If one is a whitelist and the other is a blacklist, they are not comparable
        if self.isWhitelist != other.isWhitelist:
            return False
        # If both are whitelists, this must include all paths from other
        if self.isWhitelist and all(any(IOPrivilege._path_includes(path, other_path) for path in self.pathList) for other_path in other.pathList):
            return self != other
        # If both are blacklists, this must blacklist no more than other
        if not self.isWhitelist and all(any(IOPrivilege._path_includes(other_path, path) for other_path in other.pathList) for path in self.pathList):
            return self != other
        return False
    
    def __eq__(self, other: object) -> bool:
        if not isinstance(other, IOPrivilege):
            return False
        return self.allowWrite == other.allowWrite and self.allowSudo == other.allowSudo and self.pathList == other.pathList and self.isWhitelist == other.isWhitelist
    
    def ensurance(self) -> float:
        # list all volunerable paths and assign risk values, then calculate the average risk as the ensurance cost of this privilege. The more paths and the higher risk, the higher ensurance cost.
        if sys.platform.startswith('win'):
            risk_dict = {
                "C:/**": 55.0,
                "[A-Z]:/**": 60.0,
                "C:/Windows/**": 100.0,
                "C:/Windows/System32/**": 110.0,
                "C:/Program Files/**": 65.0,
                "C:/Program Files(x86)/**": 65.0,
                "C:/ProgramData/**": 75.0,
                "C:/Users/**": 40.0,
                "[A-Z]:/Users/*/Desktop/**": 45.0,
                "[A-Z]:/Users/*/AppData/**": 60.0,
                "[A-Z]:/$Recycle.Bin/**": 50.0,
                # mounted volumes
                "[A-Z]:/System Volume Information/**": 80.0,
            }
        elif sys.platform.startswith('linux'):
            risk_dict = {
                "/**": 55.0,
                "/root/**": 100.0,
                "/boot/**": 90.0,
                "/etc/**": 80.0,
                "/etc/sudoers*": 110.0,
                "/usr/bin/**": 85.0,
                "/usr/sbin/**": 90.0,
                "/var/**": 70.0,
                "/var/lib/**": 80.0,
                "/var/log/**": 45.0,
                "/home/**": 30.0,
                "/home/*/.ssh/**": 75.0,
                # mounted volumes
                "/mnt/**": 60.0,
                "/media/**": 60.0,
            }
        elif sys.platform.startswith('darwin'):
            risk_dict = {
                "/**": 55.0,
                "/System/**": 100.0,
                "/Library/**": 80.0,
                "/private/**": 75.0,
                "/Applications/**": 70.0,
                "/Users/**": 30.0,
                "/Users/*/.ssh/**": 75.0,
                # mounted volumes
                "/Volumes/**": 60.0,
            }
        else:
            raise OSError("Unsupported operating system for IOPrivilege ensurance calculation.")
        
        # security_score relies on specific privileges
        security_score = 0.1
        if self.allowWrite:
            security_score *= 4.0
        if self.allowSudo:
            security_score *= 20.0

        normalized_paths = IOPrivilege._expand_paths_for_scoring(self.pathList)
        path_risks = [
            IOPrivilege._resolve_path_risk(Path(path_pattern), risk_dict, default_risk=10.0)
            for path_pattern in normalized_paths
        ]

        if self.isWhitelist:
            base_risk = sum(path_risks)
        else:
            baseline_unrestricted = 90.0
            blocked_reduction = sum(path_risks) * 0.5
            base_risk = max(5.0, baseline_unrestricted - blocked_reduction)

        return base_risk * security_score

    @staticmethod
    def FullPrivilege() -> List['Privilege']:
        if sys.platform.startswith('win'):
            drives = []
            for drive in range(ord('A'), ord('Z')+1):
                drive_name = chr(drive) + ":\\"
                if os.path.exists(drive_name):
                    drives.append(drive_name)
            full_paths = [Path(drive + ":/**") for drive in drives]
        elif sys.platform.startswith('linux'):
            full_paths = [Path("/**")]
        elif sys.platform.startswith('darwin'):
            full_paths = [Path("/**"), Path("/Volumes/**")]
        else:
            raise OSError("Unsupported operating system for IOPrivilege FullPrivilege.")
        return [IOPrivilege(allowWrite=True, allowSudo=True, pathList=full_paths, isWhitelist=True)]
    
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