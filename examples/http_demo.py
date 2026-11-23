"""End-to-end HTTP demo against a running API instance.

Start the server first::

    uvicorn taxonomy_outbox.api.main:app --port 18084

then run ``python examples/http_demo.py``. It creates one dictionary, three
tags, performs the four lifecycle operations, and prints the outbox before and
after dispatching one relay batch.
"""

from __future__ import annotations

import json
import uuid

import httpx

BASE_URL = "http://127.0.0.1:18084"
HEADERS = {
    "X-Org-Id": str(uuid.uuid4()),
    "X-Site-Id": str(uuid.uuid4()),
    "X-Trace-Id": "demo-trace-0001",
}


def show(step: str, response: httpx.Response) -> None:
    payload = {"step": step, "status": response.status_code}
    try:
        payload["body"] = response.json()
    except ValueError:
        payload["body"] = response.text
    print(json.dumps(payload, ensure_ascii=False))


def main() -> None:
    with httpx.Client(base_url=BASE_URL, headers=HEADERS, timeout=10, trust_env=False) as client:
        show("healthz", client.get("/healthz"))

        dictionary = client.post(
            "/api/v1/taxonomy/dictionaries",
            json={"code": "industry", "name": "Industry"},
        )
        show("create_dictionary", dictionary)
        dictionary_id = dictionary.json()["id"]

        tag_ids: dict[str, str] = {}
        for code, name in (
            ("ai", "Artificial Intelligence"),
            ("ml", "Machine Learning"),
            ("nlp", "Natural Language Processing"),
        ):
            response = client.post(
                f"/api/v1/taxonomy/dictionaries/{dictionary_id}/tags",
                json={"code": code, "name": name},
            )
            show(f"create_tag:{code}", response)
            tag_ids[code] = response.json()["id"]

        show("activate:ai", client.post(f"/api/v1/taxonomy/tags/{tag_ids['ai']}/activate"))
        show(
            "update:ai",
            client.patch(
                f"/api/v1/taxonomy/tags/{tag_ids['ai']}",
                json={"name": "AI & Machine Learning", "description": "AI related tags"},
            ),
        )
        show("activate:ml", client.post(f"/api/v1/taxonomy/tags/{tag_ids['ml']}/activate"))
        show(
            "merge:ml->ai",
            client.post(
                f"/api/v1/taxonomy/tags/{tag_ids['ml']}/merge",
                json={"target_tag_id": tag_ids["ai"]},
            ),
        )
        show("activate:nlp", client.post(f"/api/v1/taxonomy/tags/{tag_ids['nlp']}/activate"))
        show("deprecate:nlp", client.post(f"/api/v1/taxonomy/tags/{tag_ids['nlp']}/deprecate"))

        show("outbox:pending", client.get("/api/v1/taxonomy/outbox?status=pending"))
        show("dispatch", client.post("/api/v1/taxonomy/outbox/dispatch"))
        show("outbox:dispatched", client.get("/api/v1/taxonomy/outbox?status=dispatched"))


if __name__ == "__main__":
    main()
