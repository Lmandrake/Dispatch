"""Repository backends.  ``open_repository(path)`` picks one from a path."""

from stockroom.storage.base import Repository
from stockroom.storage.jsonfile import JsonFileRepository
from stockroom.storage.memory import MemoryRepository


def open_repository(path):
    """``":memory:"`` gives a MemoryRepository, anything else a JSON file."""
    if path == ":memory:":
        return MemoryRepository()
    return JsonFileRepository(path)


__all__ = ["Repository", "MemoryRepository", "JsonFileRepository", "open_repository"]
