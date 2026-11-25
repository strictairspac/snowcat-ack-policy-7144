from time import time

from pydantic import BaseModel, ConfigDict, Field
from src.constants.job_state import JobState


class RunInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter: int = Field(strict=True, ge=1)
    source_run_id: int | None = None
    source_id: int | None = None
    from_run_id: int | None = None
    parent_run_id: int | None = None
    parent_id: int | None = None
    handoff_id: int | None = None
    replica: str | None = Field(default=None, max_length=48)
    selected_replica: str | None = Field(default=None, max_length=48)
    idempotency_key: str | None = Field(default=None, max_length=96)


class RunEntry(BaseModel):
    id: int
    case_id: int
    case_title: str
    status: JobState
    parameter: int
    actor: str
    created_at: int
    finished_at: int | None
    result: dict | None
    failure: str | None
    digest: str | None
    handoff_id: int | None = None
    source_run_id: int | None = None
    parent_run_id: int | None = None
    state: str | None = None
