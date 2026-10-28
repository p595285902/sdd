from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.testing_agent import router
from app.core.config import settings


def fake_llm_client() -> TestClient:
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


def test_fake_llm_scripts_streaming_text_and_records_request() -> None:
    with fake_llm_client() as client:
        control = client.post(
            "/testing/llm/control",
            json={"replies": [{"kind": "text", "text": "Explored"}]},
        )
        response = client.post(
            "/testing/llm/v1/responses",
            headers={"Authorization": "Bearer provider-key"},
            json={"model": "acceptance-model", "stream": True, "input": []},
        )
        requests = client.get("/testing/llm/requests")

    assert control.json() == {"queued": 1}
    assert response.status_code == 200
    assert "response.output_text.delta" in response.text
    assert "Explored" in response.text
    assert requests.json()["data"][0]["authorization"] == "Bearer provider-key"


def test_fake_llm_scripts_tool_call() -> None:
    with fake_llm_client() as client:
        client.post(
            "/testing/llm/control",
            json={
                "replies": [
                    {
                        "kind": "tool",
                        "tool_name": "write",
                        "tool_arguments": {
                            "filePath": "/workspace/README.md",
                            "content": "test",
                        },
                    }
                ]
            },
        )
        response = client.post(
            "/testing/llm/v1/responses",
            json={"model": "acceptance-model", "stream": False, "input": []},
        )

    output = response.json()["output"][0]
    assert output["type"] == "function_call"
    assert output["name"] == "write"


def test_fake_llm_scripts_provider_failure() -> None:
    with fake_llm_client() as client:
        client.post(
            "/testing/llm/control",
            json={
                "replies": [
                    {"kind": "failure", "status_code": 429, "text": "limited"}
                ]
            },
        )
        response = client.post(
            "/testing/llm/v1/responses",
            json={"model": "acceptance-model", "input": []},
        )

    assert response.status_code == 429
    assert response.json() == {"error": {"message": "limited"}}


def test_reset_clears_fake_replies_requests_and_turn_settings() -> None:
    with fake_llm_client() as client:
        client.post(
            "/testing/llm/control",
            json={"replies": [{"kind": "text", "text": "old reply"}]},
        )
        client.post(
            "/testing/llm/v1/responses",
            json={"model": "acceptance-model", "input": []},
        )
        client.post(
            "/testing/llm/turns/control",
            json={"timeout_seconds": 1, "grace_seconds": 2},
        )
        assert client.post("/testing/llm/reset").json() == {"reset": True}
        assert client.get("/testing/llm/requests").json() == {"data": []}
        response = client.post(
            "/testing/llm/v1/responses",
            json={"model": "acceptance-model", "input": []},
        )
        assert response.status_code == 500
        assert settings.DEVELOP_TURN_TIMEOUT_SECONDS == 15
        assert settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS == 0.3
