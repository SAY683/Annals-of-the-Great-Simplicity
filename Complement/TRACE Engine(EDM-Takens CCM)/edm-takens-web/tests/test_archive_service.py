"""Archive image serving regression tests."""
from pathlib import Path
import sys
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT.parent / "edm-takens" / "src"))

from services import archive_service


def test_read_archive_image_returns_bytes_without_restore(tmp_path, monkeypatch):
    task_id = "20261018_image_test"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    payload = b"\x89PNG\r\n\x1a\narchive-image"
    with zipfile.ZipFile(archive_dir / f"{task_id}.zip", "w") as archive:
        archive.writestr("plot.png", payload)

    monkeypatch.setattr(archive_service, "ARCHIVE_DIR", str(archive_dir))
    assert archive_service.read_archive_image(task_id, "plot.png") == payload


def test_read_archive_image_rejects_path_traversal(tmp_path, monkeypatch):
    task_id = "20261018_image_test"
    archive_dir = tmp_path / "archive"
    archive_dir.mkdir()
    with zipfile.ZipFile(archive_dir / f"{task_id}.zip", "w") as archive:
        archive.writestr("plot.png", b"data")

    monkeypatch.setattr(archive_service, "ARCHIVE_DIR", str(archive_dir))
    with pytest.raises(ValueError):
        archive_service.read_archive_image(task_id, "../plot.png")