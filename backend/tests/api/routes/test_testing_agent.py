import asyncio
import json
from time import monotonic

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes.testing_agent import fake_llm_state, router
from app.core.config import settings
from app.services.acceptance_work import AcceptanceAdmissionMiddleware, WorkBarrier


@pytest.fixture(autouse=True)
def clean_fake_state():
    fake_llm_state.configure([])
    yield
    fake_llm_state.configure([])


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


def rule(prompt="command", *, phase="agent", replies=None):
    return {"phase": phase, **({"prompt": prompt} if phase == "agent" else {}),
            "replies": replies or [{"kind": "text", "text": phase}]}


def message(role, text):
    return {"role": role, "content": [{"type": "input_text", "text": text}]}


def respond(client, inputs, **extra):
    return client.post("/testing/llm/v1/responses", json={"input": inputs, **extra})


def output_text(response):
    assert response.status_code == 200, response.text
    return response.json()["output"][0]["content"][0]["text"]


@pytest.mark.parametrize("control_role", ["system", "developer", "instructions"])
@pytest.mark.parametrize("phase,prefix", [
    ("title", "You are a title generator. Produce a title"),
    ("planner", "Extract only explicitly documented non-Compose launch instructions"),
])
def test_auxiliary_phase_wins_over_delayed_command(control_role, phase, prefix):
    with fake_llm_client() as client:
        control = client.post("/testing/llm/control", json={"rules": [
            rule(replies=[{"kind": "delay", "text": "agent", "delay_seconds": 30}]),
            rule(phase=phase),
        ]})
        assert control.json() == {"rules": 2}
        inputs = [message("user", "command")]
        extra = {}
        if control_role == "instructions":
            extra["instructions"] = prefix
        else:
            inputs.insert(0, message(control_role, prefix))
        assert output_text(respond(client, inputs, **extra)) == phase
        assert client.get("/testing/llm/requests").json()["data"][-1]["selection"] == {
            "phase": phase, "reply_index": 0, "delay_seconds": 0,
        }


def test_latest_user_only_not_history_system_assistant_or_tool_text():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [
            rule("old", replies=[{"kind": "delay", "text": "old", "delay_seconds": 30}]),
            rule("new", replies=[{"kind": "text", "text": "new"}]),
            rule(phase="title"),
        ]})
        inputs = [message("system", "old"), message("user", "old"),
                  message("assistant", "old"), {"type": "function_call_output", "output": "old"},
                  message("user", "new"), message("assistant", "old")]
        assert output_text(respond(client, inputs)) == "new"
        assert respond(client, inputs + [message("user", "unknown")]).status_code == 500
        assert respond(client, [message("system", "old")]).status_code == 500
        # A phase-looking phrase in user data must not invoke an auxiliary rule.
        assert respond(client, [message("user", "You are a title generator.")]).status_code == 500
        assert respond(client, [message("user", "new with extra text")]).status_code == 500


@pytest.mark.parametrize("content", ["café\ncommand", [
    {"type": "input_text", "text": "café"},
    {"type": "input_image", "image_url": "ignored"},
    {"type": "text", "text": "command"},
]])
def test_exact_matching_supports_string_and_multipart_unicode_content(content):
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule("café\ncommand")]})
        assert output_text(respond(client, [{"role": "user", "content": content}])) == "agent"
        assert output_text(respond(client, "café\ncommand")) == "agent"


@pytest.mark.parametrize("command", [
    '/openspec explore café "quoted"\nsecond line',
    # Shape captured from a real continued-session proposal request.
    '/openspec propose user: Proposal request\nuser: Canonical exploration\nassistant: Canonical findings',
])
def test_real_opencode_quoted_commands_match_exactly_without_broad_unquoting(command):
    wire_text = f'"{command}"'
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(wire_text)]})
        assert output_text(respond(client, [message("user", wire_text)])) == "agent"
        assert respond(client, [message("user", command)]).status_code == 500
        assert respond(client, [message("user", json.dumps(command, ensure_ascii=False))]).status_code == 500


def test_tool_followups_are_input_derived_retry_safe_and_turn_local():
    tool = {"kind": "tool", "tool_name": "bash", "tool_arguments": {"command": "true"}}
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [
            rule(replies=[tool, {"kind": "text", "text": "done"}]), rule(phase="title"),
        ]})
        initial = [message("user", "command")]
        for _ in range(2):  # Same request retried or another session: same tool.
            assert respond(client, initial).json()["output"][0]["name"] == "bash"
        assert output_text(respond(client, [message("developer", "You are a title generator.")])) == "title"
        result = {"type": "function_call_output", "call_id": "call_test", "output": "ok"}
        followup = initial + [result]
        assert output_text(respond(client, followup)) == "done"
        assert output_text(respond(client, followup)) == "done"
        # Prior-turn tool results do not advance a continued session's new command.
        assert respond(client, followup + initial).json()["output"][0]["name"] == "bash"


@pytest.mark.parametrize("script", [
    {}, {"replies": []}, {"rules": []},
    {"replies": [{"kind": "text"}], "rules": [rule()]},
    {"rules": [rule(), rule()]},
    {"rules": [{"phase": "agent", "replies": [{"kind": "text"}]}]},
    {"rules": [{**rule(phase="planner"), "prompt": "not allowed"}]},
    {"rules": [rule(replies=[{"kind": "text"}, {"kind": "text"}])]},
    {"rules": [rule(replies=[{"kind": "tool", "tool_name": "bash"}])]},
    {"rules": [rule(replies=[{"kind": "delay", "delay_seconds": -1}])]},
    {"rules": [rule(replies=[{"kind": "delay", "delay_seconds": 31}])]},
    {"rules": [rule(phase="unknown")]},
    {"rules": [rule(phase="title", replies=[{"kind": "tool"}, {"kind": "text"}])]},
    {"rules": [{"phase": "agent", "prompt": "empty", "replies": []}]},
    {"rules": [rule("")]},
])
def test_invalid_or_ambiguous_scripts_reject_without_replacing_current_rules(script):
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule()]})
        assert client.post("/testing/llm/control", json=script).status_code == 422
        assert output_text(respond(client, "command")) == "agent"


def test_reconfigure_and_reset_remove_rules_and_request_history():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule("old")]})
        assert output_text(respond(client, "old")) == "agent"
        client.post("/testing/llm/control", json={"rules": [rule("new")]})
        assert client.get("/testing/llm/requests").json() == {"data": []}
        assert respond(client, "old").status_code == 500
        assert output_text(respond(client, "new")) == "agent"
        client.post("/testing/llm/reset")
        assert fake_llm_state.baseline_verified()
        assert respond(client, "new").status_code == 500
        client.post("/testing/llm/control", json={"replies": [{"kind": "text", "text": "legacy"}]})
        assert output_text(respond(client, "anything")) == "legacy"


@pytest.mark.parametrize("kind,status", [("failure", 429), ("malformed", 200)])
def test_matched_rules_preserve_error_responses(kind, status):
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(replies=[
            {"kind": kind, "status_code": 429, "text": "limited"},
        ])]})
        response = respond(client, "command", stream=True)
        assert response.status_code == status
        assert response.json() == ({"error": {"message": "limited"}} if kind == "failure" else {"unexpected": True})


async def capture_stream(*, disconnect=False, disconnect_at=None):
    app = FastAPI()
    app.include_router(router)
    barrier = WorkBarrier()
    app.add_middleware(AcceptanceAdmissionMiddleware, barrier=barrier, prefix="/api/v1")
    body = json.dumps({"input": "command", "stream": True}).encode()
    scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
             "http_version": "1.1", "method": "POST", "scheme": "http", "path": "/testing/llm/v1/responses",
             "raw_path": b"/testing/llm/v1/responses", "root_path": "", "query_string": b"",
             "headers": [(b"content-type", b"application/json")]}
    received = False
    closed = asyncio.Event()
    frames = []

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": body}
        await closed.wait()
        return {"type": "http.disconnect"}

    async def send(event):
        if event["type"] == "http.response.body" and event.get("body"):
            frame = json.loads(event["body"].decode().removeprefix("data: "))
            frames.append((monotonic(), frame))
            if (disconnect and frame["type"] == "response.in_progress") or frame["type"] == disconnect_at:
                closed.set()

    await asyncio.wait_for(app(scope, receive, send), timeout=1)
    assert not barrier.counts()
    return frames


def test_stream_preamble_precedes_bounded_content_delay():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(replies=[
            {"kind": "delay", "text": "delayed", "delay_seconds": 0.06},
        ])]})
    frames = asyncio.run(capture_stream())
    assert [frame["type"] for _, frame in frames[:2]] == ["response.created", "response.in_progress"]
    assert frames[2][0] - frames[1][0] >= 0.05
    assert frames[-1][1]["type"] == "response.completed"
    assert [frame["sequence_number"] for _, frame in frames] == list(range(1, len(frames) + 1))


def test_stream_chunks_arrive_before_delayed_completion():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(replies=[{
            "kind": "text", "text": "partial complete", "stream_chunk_size": 8,
            "stream_chunk_delay_seconds": 0.06,
        }])]})
    frames = asyncio.run(capture_stream())
    deltas = [(timestamp, frame) for timestamp, frame in frames
              if frame["type"] == "response.output_text.delta"]
    assert [frame["delta"] for _, frame in deltas] == ["partial ", "complete"]
    assert deltas[1][0] - deltas[0][0] >= 0.05
    assert frames[-1][1]["type"] == "response.completed"
    assert [frame["sequence_number"] for _, frame in frames] == list(range(1, len(frames) + 1))


def test_disconnect_after_partial_chunk_cancels_the_remaining_stream():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(replies=[{
            "kind": "text", "text": "partial complete", "stream_chunk_size": 8,
            "stream_chunk_delay_seconds": 30,
        }])]})
    frames = asyncio.run(capture_stream(disconnect_at="response.output_text.delta"))
    deltas = [frame for _, frame in frames if frame["type"] == "response.output_text.delta"]
    assert [frame["delta"] for frame in deltas] == ["partial "]
    assert frames[-1][1]["type"] == "response.output_text.delta"


def test_disconnected_stream_ends_pending_wait_without_content_or_completion():
    with fake_llm_client() as client:
        client.post("/testing/llm/control", json={"rules": [rule(replies=[
            {"kind": "delay", "text": "stale", "delay_seconds": 30},
        ])]})
    frames = asyncio.run(capture_stream(disconnect=True))
    assert [frame["type"] for _, frame in frames] == ["response.created", "response.in_progress"]
