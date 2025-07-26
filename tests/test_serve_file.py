import importlib
import urllib.parse

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client(tmp_path, monkeypatch):
    output_dir = tmp_path / "out"
    uploads_dir = tmp_path / "uploads"
    output_dir.mkdir()
    uploads_dir.mkdir()
    monkeypatch.setenv("OUTPUT_FOLDER", str(output_dir))
    monkeypatch.setenv("UPLOAD_FOLDER", str(uploads_dir))
    monkeypatch.setenv("API_KEY", "test-key")

    import watermarker.api as api_module

    importlib.reload(api_module)
    return TestClient(api_module.app), output_dir


def test_serve_full_output_path(client):
    test_client, output_dir = client
    file_path = output_dir / "hello.txt"
    file_path.write_text("hello")

    encoded = urllib.parse.quote(str(file_path))
    response = test_client.get(
        f"/api/v1/files/{encoded}", headers={"X-API-Key": "test-key"}
    )
    assert response.status_code == 200
    assert response.content == b"hello"


def test_reject_outside_output_folder(client, tmp_path):
    test_client, _ = client
    outside = tmp_path / "secret.txt"
    outside.write_text("nope")

    encoded = urllib.parse.quote(str(outside))
    response = test_client.get(
        f"/api/v1/files/{encoded}", headers={"X-API-Key": "test-key"}
    )
    assert response.status_code == 404
