"""Route registration/contract tests for history, archive and export modules."""
import os
import sys
from pathlib import Path

os.environ.setdefault("EDM_API_KEY", "history-route-test-key")

WEB_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(WEB_ROOT / "backend"))
sys.path.insert(0, str(WEB_ROOT.parent / "edm-takens" / "src"))

from fastapi.testclient import TestClient  # noqa: E402

import api  # noqa: E402


def _client() -> TestClient:
    return TestClient(api.app, headers={"X-API-Key": os.environ["EDM_API_KEY"]})


def test_history_and_archive_lists_are_registered():
    client = _client()
    assert client.get("/api/history").status_code == 200
    assert client.get("/api/archives").status_code == 200


def test_export_routes_are_registered_and_return_404_for_missing_task():
    client = _client()
    for suffix in ("json", "csv", "md", "html"):
        response = client.get(f"/api/history/__missing__/export/{suffix}")
        assert response.status_code == 404, (suffix, response.status_code, response.text)


def test_openapi_contains_split_route_groups():
    schema = _client().get("/openapi.json").json()
    paths = schema["paths"]
    assert "/api/history" in paths
    assert "/api/archives" in paths
    assert "/api/history/{task_id}/export/md" in paths
    assert "/api/history/{task_id}/export/html" in paths