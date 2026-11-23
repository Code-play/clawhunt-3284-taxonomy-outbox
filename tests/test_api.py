"""HTTP smoke tests: the API commits the tag change and its event together."""

from __future__ import annotations

import os
import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from taxonomy_outbox.api.main import create_app
from taxonomy_outbox.config import Settings


@pytest.fixture()
def client(engine: Engine):
    settings = Settings(database_url=os.environ["DATABASE_URL"], publisher="memory")
    app = create_app(settings)
    with TestClient(app) as test_client:
        yield test_client
    app.state.engine.dispose()


def _headers() -> dict[str, str]:
    return {"X-Org-Id": str(uuid.uuid4()), "X-Site-Id": str(uuid.uuid4())}


def _create_tag(client: TestClient, headers: dict[str, str]) -> dict:
    response = client.post(
        "/api/v1/taxonomy/dictionaries",
        json={"code": "industry", "name": "Industry"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    dictionary_id = response.json()["id"]
    response = client.post(
        f"/api/v1/taxonomy/dictionaries/{dictionary_id}/tags",
        json={"code": "ai", "name": "Artificial Intelligence"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_activation_over_http_commits_tag_and_event(client: TestClient) -> None:
    headers = _headers()
    tag = _create_tag(client, headers)
    assert tag["status"] == "draft"

    response = client.post(f"/api/v1/taxonomy/tags/{tag['id']}/activate", headers=headers)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["event_type"] == "taxonomy.tag_activated"
    assert body["outbox_status"] == "pending"
    assert body["tag"]["status"] == "active"
    assert body["tag"]["version"] == 2

    listed = client.get("/api/v1/taxonomy/outbox", headers=headers)
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["event_type"] == "taxonomy.tag_activated"
    assert listed.json()[0]["status"] == "pending"


def test_invalid_transition_returns_409_and_writes_no_event(client: TestClient) -> None:
    headers = _headers()
    tag = _create_tag(client, headers)

    response = client.post(f"/api/v1/taxonomy/tags/{tag['id']}/deprecate", headers=headers)
    assert response.status_code == 409
    assert response.json()["error"] == "invalid_tag_transition"
    assert client.get("/api/v1/taxonomy/outbox", headers=headers).json() == []


def test_patch_updates_and_noop_patch_is_rejected(client: TestClient) -> None:
    headers = _headers()
    tag = _create_tag(client, headers)
    client.post(f"/api/v1/taxonomy/tags/{tag['id']}/activate", headers=headers)

    response = client.patch(
        f"/api/v1/taxonomy/tags/{tag['id']}",
        json={"name": "Artificial Intelligence & ML", "expected_version": 2},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["event_type"] == "taxonomy.tag_updated"

    noop = client.patch(
        f"/api/v1/taxonomy/tags/{tag['id']}",
        json={"name": "Artificial Intelligence & ML"},
        headers=headers,
    )
    assert noop.status_code == 409
    assert len(client.get("/api/v1/taxonomy/outbox", headers=headers).json()) == 2


def test_other_tenant_cannot_read_or_change_the_tag(client: TestClient) -> None:
    owner = _headers()
    tag = _create_tag(client, owner)
    intruder = _headers()

    assert client.get(f"/api/v1/taxonomy/tags/{tag['id']}", headers=intruder).status_code == 404
    assert (
        client.post(f"/api/v1/taxonomy/tags/{tag['id']}/activate", headers=intruder).status_code
        == 404
    )
    assert client.get("/api/v1/taxonomy/outbox", headers=intruder).json() == []


def test_dispatch_endpoint_publishes_the_outbox(client: TestClient) -> None:
    headers = _headers()
    tag = _create_tag(client, headers)
    client.post(f"/api/v1/taxonomy/tags/{tag['id']}/activate", headers=headers)

    response = client.post("/api/v1/taxonomy/outbox/dispatch")
    assert response.status_code == 200
    assert response.json() == {"scanned": 1, "published": 1, "failed": 0}

    dispatched = client.get("/api/v1/taxonomy/outbox?status=dispatched", headers=headers).json()
    assert len(dispatched) == 1
    assert dispatched[0]["status"] == "dispatched"
