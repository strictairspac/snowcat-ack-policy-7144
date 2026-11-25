from typing import Annotated

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Response

from src.config.resources import engine
from src.controllers.access import identity, operator
from src.controllers.workbench import continue_from_run, continue_handoff, create_handoff
from src.schemas.handoffs import HandoffInput
from src.services import handoffs

router = APIRouter(prefix="/handoffs", tags=["Handoffs"])


def _continue_response(response: Response, result):
    run, handoff, state = result
    body = {
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
        body["detail"] = "该来源批次已有一份正式交班和续演批次"
        return body
    response.status_code = 202 if state in {"created", "retried"} else 200
    return body


@router.post("/continue")
@router.post("/submit")
def continue_from_handoff_body(
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    body = body or {}
    source_run_id = (
        body.get("source_run_id")
        or body.get("source_id")
        or body.get("run_id")
        or body.get("from_run_id")
        or body.get("parent_run_id")
        or body.get("parent_id")
    )
    if source_run_id is None:
        raise HTTPException(422, "source_run_id 不能为空")
    return _continue_response(response, continue_from_run(int(source_run_id), body, user, idempotency_key))


@router.get("", dependencies=[Depends(identity)])
def list_handoffs():
    with engine.connect() as db:
        return handoffs.list_entries(db)


@router.post("", status_code=201)
def register_handoff(form: HandoffInput, response: Response, user=Depends(operator)):
    if form.source_run_id is None:
        from fastapi import HTTPException
        raise HTTPException(422, "source_run_id 不能为空")
    handoff, created = create_handoff(form.source_run_id, form, user)
    response.status_code = 201 if created else 200
    return handoff


@router.get("/{handoff_id}", dependencies=[Depends(identity)])
def handoff_detail(handoff_id: int):
    with engine.connect() as db:
        return handoffs.get(db, handoff_id)


@router.post("/{handoff_id}/continue")
def continue_handoff_route(
    handoff_id: int,
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    return _continue_response(response, continue_handoff(handoff_id, body or {}, user, idempotency_key))


@router.post("/{handoff_id}/runs")
def create_handoff_run_route(
    handoff_id: int,
    response: Response,
    body: Annotated[dict | None, Body()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
    user=Depends(operator),
):
    return _continue_response(response, continue_handoff(handoff_id, body or {}, user, idempotency_key))
