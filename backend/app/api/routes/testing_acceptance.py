import uuid
from typing import Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.core.db import engine
from app.services.acceptance_reset import ControlError, acceptance_reset

router = APIRouter(prefix="/testing/acceptance", tags=["testing"])


class ResetRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(min_length=1, max_length=63)
    reset_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
    expected_generation: int = Field(ge=0)


class ConfigurationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    run_id: str = Field(min_length=1, max_length=63)
    expected_generation: int = Field(ge=0)
    mode: Literal["available", "unavailable"]


def authenticated(request: Request, authorization: str | None = Header(default=None)) -> None:
    # Authentication runs before body parsing/validation; no database user dependency.
    try:
        acceptance_reset.authenticate(authorization, request.headers.get("X-Acceptance-Run") if request.method == "GET" else request.headers.get("X-Acceptance-Run", acceptance_reset.settings.ACCEPTANCE_RUN_ID))
        if request.query_params:
            raise ControlError(422, "Acceptance controls do not accept resource selectors")
    except ControlError as error:
        raise HTTPException(error.status_code, str(error)) from None


def _run(body: ResetRequest | ConfigurationRequest) -> dict:
    from app.api.routes.develop import preview_controller

    try:
        if body.run_id != acceptance_reset.settings.ACCEPTANCE_RUN_ID:
            raise ControlError(409, "Acceptance run identity mismatch")
        return acceptance_reset.operate(
            reset_id=body.reset_id if isinstance(body, ResetRequest) else uuid.uuid4().hex,
            expected_generation=body.expected_generation, controller=preview_controller, database=engine,
            mode=body.mode if isinstance(body, ConfigurationRequest) else None,
        )
    except ControlError as error:
        raise HTTPException(error.status_code, str(error)) from None


@router.get("/state", dependencies=[Depends(authenticated)])
def state() -> dict:
    return acceptance_reset.state()


@router.post("/reset", dependencies=[Depends(authenticated)])
def reset(body: ResetRequest) -> dict:
    return _run(body)


@router.patch("/configuration", dependencies=[Depends(authenticated)])
def configuration(body: ConfigurationRequest) -> dict:
    return _run(body)
