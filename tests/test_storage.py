from pathlib import Path

import pytest

from app.storage import LocalStorage


def test_storage_save_read_delete(tmp_path: Path):
    """Test standard save, read, and delete operations of LocalStorage."""
    storage = LocalStorage(tmp_path)
    key = "tenant_123/file.pdf"
    content = b"%PDF-1.4 sample content"

    saved_key = storage.save(key, content)
    assert saved_key == key

    read_content = storage.read(key)
    assert read_content == content

    storage.delete(key)
    with pytest.raises(FileNotFoundError):
        storage.read(key)


def test_storage_path_traversal_prevention(tmp_path: Path):
    """Test that attempting to escape base_dir via directory traversal raises ValueError."""
    storage = LocalStorage(tmp_path)

    # Attempt to write outside upload directory
    with pytest.raises(ValueError, match="Path traversal detected"):
        storage.save("../escape.txt", b"evil content")

    with pytest.raises(ValueError, match="Path traversal detected"):
        storage.save("../../etc/passwd", b"evil content")

    with pytest.raises(ValueError, match="Path traversal detected"):
        storage.read("../../etc/passwd")

    with pytest.raises(ValueError, match="Path traversal detected"):
        storage.delete("../../../some_secret")
