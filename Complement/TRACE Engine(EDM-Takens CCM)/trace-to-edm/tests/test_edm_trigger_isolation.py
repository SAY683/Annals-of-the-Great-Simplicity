"""Regression tests for trace-to-edm EDM dataset isolation."""

from pathlib import Path
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import edm_trigger


def test_copy_to_edm_data_uses_project_specific_filename(tmp_path, monkeypatch):
    project_csv = tmp_path / "projects" / "proj-a" / "narrative_meta_trajectories.csv"
    project_csv.parent.mkdir(parents=True)
    project_csv.write_text("time_step,ate\n1,0.1\n", encoding="utf-8")
    edm_data = tmp_path / "edm-data"
    monkeypatch.setattr(edm_trigger, "EDM_DATA_DIR", edm_data)

    trigger = edm_trigger.EDMTrigger(csv_path=project_csv)
    target = trigger.copy_to_edm_data()

    assert target.name == "trace_to_edm_proj-a.csv"
    assert target.exists()
    assert not (edm_data / "narrative_meta_trajectories.csv").exists()

    captured = {}

    def fake_api(method, endpoint, data=None):
        captured.update({"method": method, "endpoint": endpoint, "data": data})
        return {"job_id": "job-test", "status": "pending"}

    monkeypatch.setattr(trigger, "_api_call", fake_api)
    result = trigger.submit_job(target_col="ate", q=3)

    assert result["job_id"] == "job-test"
    assert captured["data"]["filename"] == "trace_to_edm_proj-a.csv"