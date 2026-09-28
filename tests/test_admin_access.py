from fastapi.testclient import TestClient

from app.main import app


def test_admin_token_protects_teacher_and_settings(monkeypatch):
    monkeypatch.setenv("COGNITUTOR_ADMIN_TOKEN", "course-secret")
    client = TestClient(app)
    for path in ("/api/class/demo-class/dashboard", "/api/system/model-settings", "/api/questions/bank"):
        assert client.get(path).status_code == 403
        assert client.get(path, headers={"X-Admin-Token": "wrong"}).status_code == 403
        assert client.get(path, headers={"X-Admin-Token": "course-secret"}).status_code == 200
    assert client.post("/api/documents", json={"title": "note", "content": "content"}).status_code == 403
