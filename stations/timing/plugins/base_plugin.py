"""
Base plugin class for timing system hardware integrations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class CrossingEvent:
    """Represents a transponder crossing event"""

    transponder_id: str
    timestamp: datetime
    raw_time: float  # From transponder (seconds since start)
    signal_strength: int = 0

    def to_dict(self):
        """Convert to dictionary for JSON serialization"""
        return {
            "transponder_id": self.transponder_id,
            "timestamp": self.timestamp.isoformat(),
            "raw_time": self.raw_time,
            "signal_strength": self.signal_strength,
        }


class TimingPlugin(ABC):
    """
    Abstract base class for timing hardware plugins.

    Each plugin implements integration with specific timing hardware
    (e.g., TAG Heuer, MyLaps, etc.)
    """

    def __init__(self, config: dict):
        """
        Initialize plugin with configuration.

        Args:
            config: Plugin-specific configuration dictionary
        """
        self.config = config
        self.is_connected = False
        self.is_reading = False

    @abstractmethod
    async def connect(self) -> bool:
        """
        Establish connection to timing hardware.

        Returns:
            True if connection successful, False otherwise
        """
        pass

    @abstractmethod
    async def disconnect(self):
        """Disconnect from timing hardware"""
        pass

    @abstractmethod
    async def start_reading(self):
        """Begin reading transponder crossings"""
        pass

    @abstractmethod
    async def stop_reading(self):
        """Stop reading and cleanup"""
        pass

    @abstractmethod
    def get_status(self) -> dict:
        """
        Return current plugin status.

        Returns:
            Dictionary with status information
        """
        pass

    async def on_crossing(self, crossing: CrossingEvent):
        """
        Callback when a crossing is detected.
        Override this in daemon to handle crossings.

        Args:
            crossing: The crossing event
        """
        print(f"Crossing detected: {crossing}")
