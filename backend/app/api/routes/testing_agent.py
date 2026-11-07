import asyncio
import json
import time
import uuid
from collections import deque
from collections.abc import AsyncIterator, Iterator
from threading import Lock
from typing import Any, Literal

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, Field, model_validator

from app.core.config import settings
from app.services.acceptance_work import CompletionStreamingResponse, current_work

router = APIRouter(prefix="/testing/llm", tags=["testing"])


class FakeLlmReply(BaseModel):
    kind: Literal["text", "tool", "failure", "malformed", "delay", "disconnect"]
    text: str = ""
    tool_name: str = ""
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    status_code: int = 500
    delay_seconds: float = Field(default=0, ge=0, le=30)
    stream_chunk_size: int = Field(default=0, ge=0, le=100_000)
    stream_chunk_delay_seconds: float = Field(default=0, ge=0, le=30)


class FakeLlmRule(BaseModel):
    phase: Literal["agent", "title", "planner"]
    prompt: str | None = Field(default=None, min_length=1)
    replies: list[FakeLlmReply] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_rule(self) -> FakeLlmRule:
        if (self.phase == "agent") != (self.prompt is not None):
            raise ValueError("Only agent rules require an exact latest-user prompt")
        if any(reply.kind != "tool" for reply in self.replies[:-1]):
            raise ValueError("Only tool replies may precede the terminal reply")
        if self.replies[-1].kind == "tool":
            raise ValueError("A matched rule must end with a non-tool reply")
        if self.phase != "agent" and len(self.replies) != 1:
            raise ValueError("Title and planner rules require one reply")
        return self


class FakeLlmScript(BaseModel):
    # Queue mode is retained for existing isolated testing fixtures. Full-suite
    # scenarios use rules exclusively; the two modes cannot silently mix.
    replies: list[FakeLlmReply] = Field(default_factory=list)
    rules: list[FakeLlmRule] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_script(self) -> FakeLlmScript:
        if bool(self.replies) == bool(self.rules):
            raise ValueError("Configure either replies or rules, not both")
        keys = [(rule.phase, rule.prompt) for rule in self.rules]
        if len(set(keys)) != len(keys):
            raise ValueError("Duplicate fake LLM rule")
        return self


def _content_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part["text"] for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
            and part.get("type") in ("input_text", "text")
        )
    return ""


def _request_match(body: dict[str, Any]) -> tuple[str, str, int]:
    inputs = body.get("input", [])
    if isinstance(inputs, str):
        inputs = [{"role": "user", "content": inputs}]
    if not isinstance(inputs, list):
        inputs = []
    messages = [item for item in inputs if isinstance(item, dict)]
    controls = [body.get("instructions", "")] + [
        _content_text(item.get("content")) for item in messages
        if item.get("role") in ("system", "developer")
    ]
    # Inspect control messages only: user text and old conversation history may
    # contain these phrases too. Auxiliary phases always win over agent matching.
    if any(isinstance(text, str) and text.startswith("You are a title generator.") for text in controls):
        return "title", "", 0
    if any(isinstance(text, str) and text.startswith("Extract only explicitly documented non-Compose") for text in controls):
        return "planner", "", 0
    latest = next((index for index in range(len(messages) - 1, -1, -1)
                   if messages[index].get("role") == "user"), None)
    if latest is None:
        return "agent", "", 0
    prompt = _content_text(messages[latest].get("content"))
    tool_outputs = sum(item.get("type") == "function_call_output" for item in messages[latest + 1:])
    return "agent", prompt, tool_outputs


class FakeTurnSettings(BaseModel):
    timeout_seconds: int = Field(ge=1, le=30)
    grace_seconds: float = Field(ge=0, le=5)


class FakeLlmState:
    def __init__(self) -> None:
        self._lock = Lock()
        self._replies: deque[FakeLlmReply] = deque()
        self._last_reply: FakeLlmReply | None = None
        self._rules: dict[tuple[str, str | None], FakeLlmRule] = {}
        self._requests: list[dict[str, Any]] = []

    def configure(self, replies: list[FakeLlmReply], *, rules: list[FakeLlmRule] | None = None) -> None:
        with self._lock:
            self._replies = deque(replies)
            self._last_reply = None
            self._rules = {(rule.phase, rule.prompt): rule for rule in rules or []}
            self._requests = []

    def take(self, request: dict[str, Any]) -> FakeLlmReply:
        with self._lock:
            self._requests.append(request)
            if self._rules:
                phase, prompt, tool_outputs = _request_match(request["body"])
                rule = self._rules.get((phase, prompt if phase == "agent" else None))
                if rule is None:
                    raise HTTPException(status_code=500, detail=f"No fake LLM rule matched {phase} input")
                # Selection is derived from this turn's tool results, not request
                # order. Retries and identical prompts in other sessions are safe.
                index = min(tool_outputs, len(rule.replies) - 1)
                reply = rule.replies[index]
                request["selection"] = {"phase": phase, "reply_index": index, "delay_seconds": reply.delay_seconds}
                return reply
            if self._replies:
                self._last_reply = self._replies.popleft()
            if self._last_reply is None:
                raise HTTPException(status_code=500, detail="No fake LLM reply scripted")
            return self._last_reply

    def baseline_verified(self) -> bool:
        with self._lock:
            return not self._rules and not self._replies and self._last_reply is None and not self._requests

    def requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._requests)


fake_llm_state = FakeLlmState()


@router.post("/control")
def configure_fake_llm(script: FakeLlmScript) -> dict[str, int]:
    fake_llm_state.configure(script.replies, rules=script.rules)
    return {"rules": len(script.rules)} if script.rules else {"queued": len(script.replies)}


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


@router.post("/reset")
def reset_acceptance_state() -> dict[str, bool]:
    fake_llm_state.configure([])
    settings.DEVELOP_TURN_TIMEOUT_SECONDS = 15
    settings.DEVELOP_TURN_PRESENCE_GRACE_SECONDS = 0.3
    return {"reset": True}


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


def _response_events(response: dict[str, Any], *, chunk_size: int = 0) -> Iterator[str]:
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
        chunks = [text] if not chunk_size else [
            text[offset:offset + chunk_size] for offset in range(0, len(text), chunk_size)
        ]
        for chunk in chunks:
            yield event(
                "response.output_text.delta",
                item_id=item["id"],
                output_index=0,
                content_index=0,
                delta=chunk,
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


async def _wait_for_reply(
    reply: FakeLlmReply, request: Request, *, delay_seconds: float | None = None,
) -> bool:
    work = current_work.get()
    deadline = time.monotonic() + (reply.delay_seconds if delay_seconds is None else delay_seconds)
    while True:
        if (work is not None and work.cancelled.is_set()) or await request.is_disconnected():
            return False
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return True
        await asyncio.sleep(min(0.05, remaining))


async def _delayed_response_events(reply: FakeLlmReply, response: dict[str, Any], request: Request) -> AsyncIterator[str]:
    emitted_text = False
    for index, event in enumerate(_response_events(response, chunk_size=reply.stream_chunk_size)):
        # OpenCode may establish its step checkpoint from the initial events.
        # Delay content, never the created/in_progress streaming preamble.
        if index == 2 and not await _wait_for_reply(reply, request):
            return
        if json.loads(event.removeprefix("data: "))["type"] == "response.output_text.delta":
            if emitted_text and not await _wait_for_reply(
                reply, request, delay_seconds=reply.stream_chunk_delay_seconds,
            ):
                return
            emitted_text = True
        yield event


@router.post("/v1/responses", response_model=None)
async def fake_responses(
    request: Request,
    authorization: str | None = Header(default=None),
) -> Response:
    body = await request.json()
    reply = fake_llm_state.take({"authorization": authorization, "body": body})
    if body.get("stream") and reply.kind in ("text", "tool", "delay"):
        response = _response_object(reply, f"resp_{uuid.uuid4().hex}")
        return CompletionStreamingResponse(
            _delayed_response_events(reply, response, request), media_type="text/event-stream"
        )
    if not await _wait_for_reply(reply, request):
        return JSONResponse(status_code=503, content={"error": {"message": "Acceptance provider request cancelled"}})
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

        return CompletionStreamingResponse(disconnect(), media_type="text/event-stream")
    return JSONResponse(content=_response_object(reply, f"resp_{uuid.uuid4().hex}"))
