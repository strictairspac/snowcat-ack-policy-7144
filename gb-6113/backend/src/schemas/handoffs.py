from pydantic import BaseModel, ConfigDict, Field


class HandoffInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    source_run_id: int | None = None
    replica: str | None = Field(default=None, max_length=48)
    selected_replica: str | None = Field(default=None, max_length=48)
    idempotency_key: str | None = Field(default=None, max_length=96)


class ContinuationInput(BaseModel):
    model_config = ConfigDict(extra="allow")

    parameter: int | None = Field(default=None, strict=True, ge=1)
    timeout: int | None = Field(default=None, strict=True, ge=1)
    payload: dict | None = None
    script: dict | None = None
    scenario: dict | None = None
    next_payload: dict | None = None
    case_id: int | None = None
    replica: str | None = Field(default=None, max_length=48)
    selected_replica: str | None = Field(default=None, max_length=48)
    title: str | None = Field(default=None, min_length=2, max_length=120)
    description: str | None = Field(default="", max_length=420)
    idempotency_key: str | None = Field(default=None, max_length=96)
    retry: bool = False
    retry_failed: bool = True
