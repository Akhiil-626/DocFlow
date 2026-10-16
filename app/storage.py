from abc import ABC, abstractmethod
from pathlib import Path


class Storage(ABC):
    """Abstract storage interface for reading, saving, and deleting files."""

    @abstractmethod
    def save(self, key: str, data: bytes) -> str:
        """Save file data at key and return the key."""
        pass

    @abstractmethod
    def read(self, key: str) -> bytes:
        """Read and return file data for the given key."""
        pass

    @abstractmethod
    def delete(self, key: str) -> None:
        """Delete file at the given key."""
        pass


class LocalStorage(Storage):
    """Local filesystem storage implementation rooted at base_dir."""

    def __init__(self, base_dir: str | Path):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _resolve_path(self, key: str) -> Path:
        """Resolve the target path safely, preventing directory traversal attacks."""
        # Strip leading slashes to prevent root-relative path resolution
        clean_key = key.lstrip("/\\")
        target_path = (self.base_dir / clean_key).resolve()

        # Strict containment check
        try:
            target_path.relative_to(self.base_dir)
        except ValueError as err:
            raise ValueError(f"Path traversal detected: '{key}' escapes storage root") from err

        return target_path

    def save(self, key: str, data: bytes) -> str:
        target_path = self._resolve_path(key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(data)
        return key

    def read(self, key: str) -> bytes:
        target_path = self._resolve_path(key)
        if not target_path.is_file():
            raise FileNotFoundError(f"File not found: '{key}'")
        return target_path.read_bytes()

    def delete(self, key: str) -> None:
        target_path = self._resolve_path(key)
        if target_path.is_file():
            target_path.unlink()
