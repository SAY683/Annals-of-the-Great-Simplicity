"""Regression tests for project dataset CSV import."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dataset_manager import DatasetManager


def test_add_text_csv_handles_quoted_commas_and_bom():
    csv_text = (
        "\ufefftimestamp,text,source\n"
        '2026-07-01,"第一句，包含逗号，也有\"引号\"",来源A\n'
        '2026-07-02,"第二句, with ASCII comma",来源B\n'
    )
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "input.csv"
        source.write_text(csv_text, encoding="utf-8")

        manager = DatasetManager(tmp_path / "project")
        added = manager.add_text_csv(str(source))

        assert added == 2
        assert len(manager.entries) == 2
        assert "包含逗号" in manager.entries[0]["text"]
        assert manager.entries[0]["timestamp"] == "2026-07-01"
        assert manager.entries[0]["source"] == "来源A"
        assert manager.entries[1]["text"] == "第二句, with ASCII comma"


def test_add_text_csv_is_idempotent_by_content_hash():
    csv_text = "timestamp,text,source\n2026-07-01,同一段文本,来源\n"
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        source = tmp_path / "input.csv"
        source.write_text(csv_text, encoding="utf-8")

        manager = DatasetManager(tmp_path / "project")
        assert manager.add_text_csv(str(source)) == 1
        assert manager.add_text_csv(str(source)) == 0
        assert len(manager.entries) == 1