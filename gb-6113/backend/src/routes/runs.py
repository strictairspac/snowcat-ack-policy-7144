from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response

from src.config.resources import engine
from src.constants.job_state import JobState
from src.controllers.access import identity, operator, reviewer
from src.controllers.workbench import continue_from_run, new_review, retry_run
from src.schemas.reviews import ReviewEntry, ReviewInput
from src.schemas.runs import RunEntry
from src.services import handoffs, reviews, runs
from src.utils.serial import canonical_json

router = APIRouter(prefix="/runs", tags=["Execution"])


@router.get("", response_model=list[RunEntry], dependencies=[Depends(identity)])
def list_runs():
    with engine.connect() as db:
        return runs.list_entries(db)


@router.get("/{run_id}", response_model=RunEntry, dependencies=[Depends(identity)])
def run_detail(run_id: int):
    with engine.connect() as db:
        return runs.get(db, run_id)


def _continuation_body(response: Response, result):
    run, handoff, state = result
    payload = {
        **(run or {}),
        "handoff": handoff,
        "official_handoff": handoff,
        "handoff_id": handoff["id"] if handoff else None,
        "source_run_id": handoff["source_run_id"] if handoff else None,
        "parent_run_id": handoff["source_run_id"] if handoff else None,
        "continuation_run_id": run.get("id") if run else None,
        "state": state,
        "replayed": state != "created",
        "official": True,
    }
    if state == "conflict":
        response.status_code = 409
        payload["detail"] = "该故障批次已有一份正式交班；请沿用其续演批次，勿再新增批次"
        return payload
    response.status_code = 202 if state in {"created", "retried"} else 200
    return payload


@router.get("/{run_id}/handoff/preview", dependencies=[Depends(identity)])
def preview_run_handoff(run_id: int, replica: str | None = None):
    with engine.connect() as db:
        return handoffs.preview(db, run_id, replica)


@router.post("/{run_id}/handoff/preview", dependencies=[Depends(operator)])
def preview_run_handoff_post(run_id: int, body: dict | None = Body(default=None)):
    replica = (body or {}).get("replica") or (body or {}).get("selected_replica")
    with engine.connect() as db:
        return handoffs.preview(db, run_id, replica)


@router.get("/{run_id}/handoff", dependencies=[Depends(identity)])
def run_handoff(run_id: int):
    with engine.connect() as db:
        handoff = handoffs.get_for_source(db, run_id)
        if handoff is None:
            raise HTTPException(404, "该批次尚未形成正式交班")
        return handoff


@router.post("/{run_id}/handoff")
def create_run_handoff(
    run_id: int,
    response: Response,
    form: dict | None = Body(default=None),
    user=Depends(operator),
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    from src.controllers.workbench import create_handoff as create_official_handoff
    from src.schemas.handoffs import HandoffInput

    data = HandoffInput(**(form or {}))
    if idempotency_key and not data.idempotency_key:
        data.idempotency_key = idempotency_key
    handoff, created = create_official_handoff(run_id, data, user)
    response.status_code = 201 if created else 200
    return handoff


@router.post("/{run_id}/continue")
def continue_run_route(
    run_id: int,
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    parameter: int | None = None,
    replica: str | None = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    body = dict(body or {})
    if parameter is not None:
        body.setdefault("parameter", parameter)
    if replica is not None:
        body.setdefault("replica", replica)
    return _continuation_body(response, continue_from_run(run_id, body, user, idempotency_key))


@router.post("/{run_id}/continuation")
def continuation_alias_route(
    run_id: int,
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    return _continuation_body(response, continue_from_run(run_id, body or {}, user, idempotency_key))


@router.post("/{run_id}/next")
def next_alias_route(
    run_id: int,
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    return _continuation_body(response, continue_from_run(run_id, body or {}, user, idempotency_key))


@router.post("/{run_id}/retry", response_model=RunEntry, status_code=202)
def retry_run_route(run_id: int, user=Depends(operator)):
    return retry_run(run_id, user)


@router.post("/{run_id}/rerun", response_model=RunEntry, status_code=202)
def rerun_alias_route(run_id: int, user=Depends(operator)):
    return retry_run(run_id, user)


@router.get("/{run_id}/review", response_model=ReviewEntry | None, dependencies=[Depends(identity)])
def review_detail(run_id: int):
    with engine.connect() as db:
        runs.get(db, run_id)
        return reviews.get(db, run_id)


@router.post("/{run_id}/review", response_model=ReviewEntry, status_code=201)
def sign(run_id: int, form: ReviewInput, user=Depends(reviewer)):
    return new_review(run_id, form, user)


@router.get("/{run_id}/export", dependencies=[Depends(identity)])
def export(run_id: int):
    with engine.connect() as db:
        run = runs.get(db, run_id)
        if run["status"] != JobState.DONE:
            raise HTTPException(409, "没有可导出的执行结果")
        run["review"] = reviews.get(db, run_id)
        run["handoff"] = handoffs.get_for_source(db, run_id)
        run["incoming_handoff"] = handoffs.get_for_continuation(db, run_id)
    return Response(canonical_json(run), media_type="application/json", headers={
        "Content-Disposition": f"attachment; filename=evidence-{run_id}.json",
    })
