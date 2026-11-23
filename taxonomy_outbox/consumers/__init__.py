"""Example consumers that subscribe to tag lifecycle events."""

from .base import BaseConsumer
from .matching_engine import MatchingEngineConsumer
from .search_index import SearchIndexConsumer

__all__ = ["BaseConsumer", "MatchingEngineConsumer", "SearchIndexConsumer"]
