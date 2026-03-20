#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from typing import ClassVar, List, Optional, Union
from pydantic import SecretStr
from privilege import Privilege

class Agent:
    def __init__(
            self,
            systemPrompt: str,
            model: str,
            api_url: str,
            api_key: SecretStr,
            privileges: List[Privilege],
    ):
        self.systemPrompt = systemPrompt
        self.model = model
        self.api_url = api_url
        self.api_key = api_key
        self.privileges = privileges
    
    # TODO: Implement Agent methods for interaction, privilege checking, etc.

class AgentGroup:
    rootGroup: ClassVar['AgentGroup']
    AgentGroups: ClassVar[List['AgentGroup']]

    @staticmethod
    def all() -> List['AgentGroup']:
        return AgentGroup.AgentGroups
    
    @staticmethod
    def add(agentGroup: 'AgentGroup') -> int:
        AgentGroup.AgentGroups.append(agentGroup)
        return len(AgentGroup.AgentGroups) - 1

    @staticmethod
    def remove(agentGroup: Union['AgentGroup',int]) -> bool:
        if isinstance(agentGroup, int):
            if 0 < agentGroup < len(AgentGroup.AgentGroups):
                del AgentGroup.AgentGroups[agentGroup]
                return True
            else:
                return False
        elif isinstance(agentGroup, AgentGroup):
            if agentGroup == AgentGroup.rootGroup:
                return False
            try:
                AgentGroup.AgentGroups.remove(agentGroup)
                return True
            except ValueError:
                return False
        else:
            return False
    
    @staticmethod
    def get(agentGroup: int) -> Optional['AgentGroup']:
        if 0 <= agentGroup < len(AgentGroup.AgentGroups):
            return AgentGroup.AgentGroups[agentGroup]
        else:
            return None
        
    def __init__(
            self, 
            name: str, 
            description: str,
            ## Agent Informations
            systemPrompt: str,
            model: str,
            api_url: str,
            api_key: SecretStr,
            privileges: List[Privilege],
            ):
        self.name = name
        self.description = description
        self.systemPrompt = systemPrompt
        self.model = model
        self.api_url = api_url
        self.api_key = api_key
        self.privileges = privileges
    
    def calculateCost(self) -> float:
        raise NotImplementedError("Cost calculation is not implemented yet.")
    
    def hire(self) -> Agent:
        raise NotImplementedError("Agent hiring is not implemented yet.")
    
    def dismiss(self) -> bool:
        raise NotImplementedError("Agent dismissal is not implemented yet.")


AgentGroup.rootGroup = AgentGroup(name="Root", description="Root Agent Group", systemPrompt="", model="", api_url="", api_key=SecretStr(""), privileges=Privilege.FullPrivilege())
AgentGroup.AgentGroups = [AgentGroup.rootGroup]