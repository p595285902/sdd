import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse
from pydantic import BaseModel, Field

from app.core.config import settings

router = APIRouter(prefix="/testing/llm", tags=["testing"])


class FakeLlmReply(BaseModel):
    kind: Literal["text", "tool", "failure", "malformed", "delay", "disconnect"]
    text: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    status_code: int = 500
    delay_seconds: float = Field(default=0, ge=0, le=30)


class FakeLlmScript(BaseModel):
    replies: list[FakeLlmReply] = Field(min_length=1)


class FakeTurnSettings(BaseModel):
    timeout_seconds: int = Field(ge=1, le=30)
    grace_seconds: float = Field(ge=0, le=5)


class FakeLlmState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._replies: deque[FakeLlmReply] = deque()
        self._last_reply: FakeLlmReply | None = None
        self._requests: list[dict[str, Any]] = []

    def configure(self, replies: list[FakeLlmReply]) -> None:
        with self._lock:
            self._replies = deque(replies)
            self._last_reply = None
            self._requests = []

    def take(self, request: dict[str, Any]) -> FakeLlmReply:
        with self._lock:
            self._requests.append(request)
            if self._replies:
                self._last_reply = self._replies.popleft()
            if self._last_reply is None:
                raise HTTPException(status_code=500, detail="No fake LLM reply scripted")
            return self._last_reply

    def requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._requests)


fake_llm_state = FakeLlmState()


@router.post("/control")
def configure_fake_llm(script: FakeLlmScript) -> dict[str, int]:
    fake_llm_state.configure(script.replies)
    return {"queued": len(script.replies)}


@router.get("/requests")
def read_fake_llm_requests() -> dict[str, list[dict[str, Any]]]:
    return {"data": fake_llm_state.requests()}


@router.post("/turns/control")
def configure_fake_turn_settings(control: FakeTurnSettings) -> dict[str, float]:
    settings.DEVELOP_TURN_TIMEOUT_SECONDS = control.timeout_seconds
    settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS = control.grace_seconds
    return {
        "timeout_seconds": settings.DEVELOP_TURN_TIMEOUT_SECONDS,
        "grace_seconds": settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS,
    }


def _response_object(reply: FakeLlmReply, response_id: str) -> dict[str, Any]:
    output: list[dict[str, Any]]
    if reply.kind == "tool":
        output = [
            {
                "type": "function_call",
                "id": f"fc_{uuid.uuid4().hex}",
                "call_id": f"call_{uuid.uuid4().hex}",
                "name": reply.tool_name,
                "arguments": json.dumps(reply.tool_arguments),
                "status": "completed",
            }
        ]
    else:
        output = [
            {
                "type": "message",
                "id": f"msg_{uuid.uuid4().hex}",
                "status": "completed",
                "role": "assistant",
                "content": [
                    {
                        "type": "output_text",
                        "text": reply.text,
                        "annotations": [],
                        "logprobs": [],
                    }
                ],
            }
        ]
    return {
        "id": response_id,
        "object": "response",
        "created_at": int(time.time()),
        "status": "completed",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "max_output_tokens": None,
        "metadata": {},
        "model": "acceptance-model",
        "output": output,
        "parallel_tool_calls": True,
        "previous_response_id": None,
        "reasoning": {"effort": None, "summary": None},
        "service_tier": "default",
        "store": True,
        "temperature": 1,
        "text": {"format": {"type": "text"}, "verbosity": "medium"},
        "tool_choice": "auto",
        "tools": [],
        "top_p": 1,
        "truncation": "disabled",
        "usage": {
            "input_tokens": 1,
            "input_tokens_details": {"cached_tokens": 0},
            "output_tokens": 1,
            "output_tokens_details": {"reasoning_tokens": 0},
            "total_tokens": 2,
        },
    }


def _response_events(response: dict[str, Any]) -> Iterator[str]:
    sequence = 0

    def event(event_type: str, **values: Any) -> str:
        nonlocal sequence
        sequence += 1
        return f"data: {json.dumps({'type': event_type, 'sequence_number': sequence, **values})}\n\n"

    initial_response = {**response, "status": "in_progress", "output": []}
    yield event("response.created", response=initial_response)
    yield event("response.in_progress", response=initial_response)
    completed_item = response["output"][0]
    if completed_item["type"] == "message":
        item = {**completed_item, "status": "in_progress", "content": []}
    else:
        item = {**completed_item, "status": "in_progress", "arguments": ""}
    yield event("response.output_item.added", output_index=0, item=item)
    if completed_item["type"] == "message":
        content = completed_item["content"][0]
        text = content["text"]
        yield event(
            "response.content_part.added",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            part={**content, "text": ""},
        )
        yield event(
            "response.output_text.delta",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            delta=text,
            logprobs=[],
        )
        yield event(
            "response.output_text.done",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            text=text,
        )
        yield event(
            "response.content_part.done",
            item_id=item["id"],
            output_index=0,
            content_index=0,
            part=content,
        )
    else:
        arguments = completed_item["arguments"]
        yield event(
            "response.function_call_arguments.delta",
            item_id=item["id"],
            output_index=0,
            delta=arguments,
        )
        yield event(
            "response.function_call_arguments.done",
            item_id=item["id"],
            output_index=0,
            arguments=arguments,
        )
    yield event(
        "response.output_item.done", output_index=0, item=completed_item
    )
    yield event("response.completed", response=response)


@router.post("/v1/responses", response_model=None)
async def fake_responses(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    body = await request.json()
    reply = fake_llm_state.take({"authorization": authorization, "body": body})
    if reply.delay_seconds:
        await asyncio.sleep(reply.delay_seconds)
    if reply.kind == "failure":
        return JSONResponse(
            status_code=reply.status_code,
            content={"error": {"message": reply.text or "Scripted provider failure"}},
        )
    if reply.kind == "malformed":
        return JSONResponse(content={"unexpected": True})
    if reply.kind == "disconnect":
        async def disconnect() -> AsyncIterator[bytes]:
            yield b"data: {\"type\":\"response.created\"}\n\n"
            raise RuntimeError("Scripted provider disconnect")

        return StreamingResponse(disconnect(), media_type="text/event-stream")
    response = _response_object(reply, f"resp_{uuid.uuid4().hex}")
    if body.get("stream"):
        return StreamingResponse(
            _response_events(response), media_type="text/event-stream"
        )
    return JSONResponse(content=response)
