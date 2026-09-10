"""Domain ports — ABC interfaces for dependency inversion.

The domain layer depends ONLY on these interfaces.
Infrastructure adapters provide concrete implementations.
"""

from abc import ABC, abstractmethod
from typing import Any


class EventBusPort(ABC):
    """Abstract event bus interface."""

    @abstractmethod
    def subscribe(self, event_name: str, callback) -> None:
        """Subscribe a callback to a named event."""
        ...

    @abstractmethod
    def unsubscribe(self, event_name: str, callback) -> None:
        """Remove a callback subscription."""
        ...

    @abstractmethod
    def publish(self, event_name: str, payload: Any = None) -> None:
        """Publish an event with optional payload."""
        ...

    @abstractmethod
    def get_subscribers(self, event_name: str) -> list:
        """Return list of subscribers for an event."""
        ...

    @abstractmethod
    def clear(self) -> None:
        """Remove all subscriptions."""
        ...
