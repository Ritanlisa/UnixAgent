#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from abc import ABC, abstractmethod
from typing import Any, Optional
from enum import Enum

## Virtual Base Class for Privilege Management

class Privilege(ABC):
    def __init__(self, *args, **kwargs):
        self.__writeprotection = True
        pass
    
    @abstractmethod
    def __str__(self) -> str:
        """Return a string representation of the privilege."""
        return ""
    
    @abstractmethod
    def __repr__(self) -> str:
        """Return a string representation of the privilege for debugging purposes."""
        return self.__str__()

    @abstractmethod
    def to_dict(self) -> dict:
        """Return a string representation of the privilege for Agent Usage, listing its attributes with dictionary."""
        return {}

    @staticmethod
    @abstractmethod
    def create(data: dict) -> Optional['Privilege']:
        """Create a Privilege instance from a dictionary."""
        pass

    ## Privilege Comparison Operators

    @abstractmethod
    def __lt__(self, other: 'Privilege') -> bool:
        """Check if this privilege is less than another privilege."""
        pass

    @abstractmethod
    def __eq__(self, other: object) -> bool:
        """Check if this privilege is equal to another privilege."""
        if not isinstance(other, Privilege):
            return False
        return True

    @abstractmethod
    def __hash__(self) -> int:
        """Return a hash value for the privilege."""
        return hash(frozenset(self.to_dict().items()))
    
    ## Read-only attributes protection after initialization

    def __setattr__(self, name: str, value: Any) -> None:
        """Set an attribute of the privilege must be forbidden after initialization."""
        if not getattr(self, '__writeprotection', False):
            return super().__setattr__(name, value)
        else:
            raise AttributeError
    
    def __delattr__(self, name: str) -> None:
        """Delete an attribute of the privilege must be forbidden after initialization."""
        if not getattr(self, '__writeprotection', False):
            return super().__delattr__(name)
        else:
            raise AttributeError
    
    ## Define other comparison operators based on the less than & equal to operators

    def __le__(self, other: 'Privilege'):
        """Check if this privilege is less than or equal to another privilege."""
        return self.__lt__(other) or self.__eq__(other)
    
    def __gt__(self, other: 'Privilege'):
        """Check if this privilege is greater than another privilege."""
        return other.__lt__(self)
    
    def __ge__(self, other: 'Privilege'):
        """Check if this privilege is greater than or equal to another privilege."""
        return other.__lt__(self) or self.__eq__(other)

    def __ne__(self, other: object):
        """Check if this privilege is not equal to another privilege."""
        return not self.__eq__(other)
