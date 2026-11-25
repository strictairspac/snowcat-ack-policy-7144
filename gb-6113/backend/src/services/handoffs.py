from time import time

from fastapi import HTTPException
from sqlalchemy import select, update

from src.constants.job_state import JobState
from src.domain import scenario
from src.domain.handoff import handoff_manifest
from src.models.cases import cases
from src.models.handoffs import handoffs
from src.models.runs import runs
from src.schemas.cases import CaseInput
from src.services import audit, cases as case_service, runs as run_service
from src.utils.serial import content_digest


def _lock(db, statement):
    # SQLite accepts the statement but has no portable row-lock syntax.  The
    # source-row unique constraint remains the final correctness guard.
    if db.dialect.name in {"postgresql", "mysql", "mariadb"}:
        return statement.with_for_update()
    return statement


def get(db, handoff_id):
    row = db.execute(select(handoffs).where(handoffs.c.id == handoff_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "正式交班记录不存在")
    return dict(row)


def get_for_source(db, source_run_id):
    row = db.execute(
        select(handoffs).where(handoffs.c.source_run_id == source_run_id)
    ).mappings().first()
    return dict(row) if row else None


def get_for_continuation(db, continuation_run_id):
    row = db.execute(
        select(handoffs).where(handoffs.c.continuation_run_id == continuation_run_id)
    ).mappings().first()
    return dict(row) if row else None


def list_entries(db):
    rows = db.execute(select(handoffs).order_by(handoffs.c.id.desc()).limit(100)).mappings()
    return [dict(row) for row in rows]


def normalize_body(body):
    return dict(body or {})


def _selected_replica(body):
    return body.get("replica") or body.get("selected_replica") or body.get("target_replica")


def _idempotency_key(body, header_key=None):
    key = header_key or body.get("idempotency_key") or body.get("idempotencyKey") or body.get("client_token")
    if key is not None:
        key = str(key).strip()
        if not key:
            return None
        if len(key) > 96:
            raise HTTPException(422, "幂等键不能超过 96 个字符")
    return key or None


def _parameter(body):
    parameter = body.get("parameter")
    if parameter is None:
        parameter = body.get("timeout")
    if parameter is None:
        parameter = scenario.CONFIG["default_parameter"]
    if type(parameter) is not int or isinstance(parameter, bool):
        raise HTTPException(422, "parameter 必须是整数")
    if not 1 <= parameter <= scenario.CONFIG["max_parameter"]:
        raise HTTPException(422, f"parameter 必须是 1 到 {scenario.CONFIG['max_parameter']} 的整数")
    return parameter


def _has_script(body):
    return any(body.get(key) is not None for key in ("case_id", "payload", "script", "scenario", "next_payload")) or (
        "writes" in body and "standbys" in body
    )


def _script(body):
    if body.get("case_id") is not None:
        return None, int(body["case_id"])

    payload = body.get("payload")
    if payload is None:
        payload = body.get("script") or body.get("scenario") or body.get("next_payload")
    if payload is None and isinstance(body, dict) and "writes" in body and "standbys" in body:
        # Allow the scenario document itself to be POSTed.
        payload = {key: value for key, value in body.items() if key not in {"parameter", "timeout"}}
    if payload is None:
        raise HTTPException(422, "请提供续演剧本 payload，或选择已有 case_id")
    if not isinstance(payload, dict):
        raise HTTPException(422, "续演剧本必须是 JSON 对象")
    try:
        scenario.validate(payload)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    return payload, None


def request_digest(source_run_id, parameter, replica, payload=None, case_id=None):
    payload_digest = content_digest(payload) if payload is not None else None
    return content_digest({
        "source_run_id": source_run_id,
        "parameter": parameter,
        "replica": replica,
        "payload_digest": payload_digest,
        "case_id": case_id,
    })


def _incoming_context(db, source_run_id):
    incoming = get_for_continuation(db, source_run_id)
    if not incoming:
        return [], []
    manifest = incoming.get("manifest") or {}
    return manifest.get("inherited", []) or [], manifest.get("losses", []) or []


def _previous_losses(db, source_run_id):
    return _incoming_context(db, source_run_id)[1]


def preview(db, source_run_id, replica=None):
    source = run_service.get(db, source_run_id)
    if source["status"] != JobState.DONE:
        raise HTTPException(409, "只有执行成功的故障批次才能办理正式交班")
    source_case = case_service.get(db, source["case_id"])
    inherited, previous_losses = _incoming_context(db, source_run_id)
    try:
        return handoff_manifest(
            source_case["payload"],
            source["parameter"],
            run_id=source_run_id,
            replica_name=replica,
            previous_losses=previous_losses,
            source_case=source_case,
            inherited=inherited,
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc


def create_handoff(db, source_run_id, actor, body=None, header_key=None):
    body = normalize_body(body)
    key = _idempotency_key(body, header_key)
    requested_replica = _selected_replica(body)

    db.execute(_lock(db, select(runs).where(runs.c.id == source_run_id)))
    source = run_service.get(db, source_run_id)
    if source["status"] != JobState.DONE:
        raise HTTPException(409, "只有执行成功的故障批次才能办理正式交班")

    existing = get_for_source(db, source_run_id)
    if existing:
        if key and existing.get("idempotency_key") and key != existing["idempotency_key"]:
            raise HTTPException(409, "该批次已有另一个幂等键对应的正式交班")
        return existing, False

    if key:
        same_key = db.execute(select(handoffs).where(handoffs.c.idempotency_key == key)).mappings().first()
        if same_key:
            raise HTTPException(409, "幂等键已用于其他批次的正式交班")

    manifest = preview(db, source_run_id, requested_replica)
    now = int(time())
    change = db.execute(insert_handoff().values(
        source_run_id=source_run_id,
        continuation_run_id=None,
        replica=manifest["replica"],
        idempotency_key=key,
        request_digest=None,
        official=True,
        manifest=manifest,
        actor=actor,
        created_at=now,
        updated_at=now,
    ))
    handoff_id = change.inserted_primary_key[0]
    audit.record(db, "official_handoff", actor, "handoff", handoff_id)
    return get(db, handoff_id), True


def insert_handoff():
    # Indirection keeps imports/readability straightforward.
    from sqlalchemy import insert
    return insert(handoffs)


def _create_continuation_run(db, source_run_id, body, actor, parameter, payload, case_id):
    if case_id is None:
        title = (body.get("title") or "").strip() or f"续演资料 · 接第 {source_run_id} 场"
        description = body.get("description") or ""
        case = case_service.create(db, CaseInput(
            title=title[:120], description=description[:420], payload=payload
        ), actor)
        case_id = case["id"]
    else:
        case_service.get(db, case_id)
    return run_service.enqueue(db, case_id, parameter, actor)


def submit_continuation(db, source_run_id, actor, body=None, header_key=None):
    """Create or replay the unique official continuation for a source run.

    Returns ``(run, handoff, state)`` where state is one of created, replayed,
    retried or conflict.  The caller's transaction wraps this function.
    """
    body = normalize_body(body)
    key = _idempotency_key(body, header_key)
    parameter = _parameter(body)
    requested_replica = _selected_replica(body)
    script_provided = _has_script(body)
    payload = case_id = None
    if script_provided:
        payload, case_id = _script(body)

    db.execute(_lock(db, select(runs).where(runs.c.id == source_run_id)))
    source = run_service.get(db, source_run_id)
    if source["status"] != JobState.DONE:
        raise HTTPException(409, "只有执行成功的故障批次才能续演；失败批次请使用失败重试")

    if key:
        same_key = db.execute(select(handoffs).where(handoffs.c.idempotency_key == key)).mappings().first()
        if same_key and same_key["source_run_id"] != source_run_id:
            raise HTTPException(409, "幂等键已用于其他批次的正式交班")

    existing = get_for_source(db, source_run_id)
    if existing is None:
        if not script_provided:
            raise HTTPException(422, "请提供续演剧本 payload，或选择已有 case_id")
        manifest = preview(db, source_run_id, requested_replica)
        replica = manifest["replica"]
        digest = request_digest(source_run_id, parameter, replica, payload=payload, case_id=case_id)
        run = _create_continuation_run(db, source_run_id, body, actor, parameter, payload, case_id)
        now = int(time())
        change = db.execute(insert_handoff().values(
            source_run_id=source_run_id,
            continuation_run_id=run["id"],
            replica=replica,
            idempotency_key=key,
            request_digest=digest,
            official=True,
            manifest=manifest,
            actor=actor,
            created_at=now,
            updated_at=now,
        ))
        handoff_id = change.inserted_primary_key[0]
        audit.record(db, "official_handoff", actor, "handoff", handoff_id)
        return run_service.get(db, run["id"]), get(db, handoff_id), "created"

    if key and not existing.get("idempotency_key"):
        db.execute(update(handoffs).where(handoffs.c.id == existing["id"]).values(idempotency_key=key))
        existing = get(db, existing["id"])
    if key and existing.get("idempotency_key") and key != existing["idempotency_key"]:
        return None, existing, "conflict"

    replica = requested_replica or existing["replica"]
    digest = request_digest(source_run_id, parameter, replica, payload=payload, case_id=case_id)

    if not existing.get("continuation_run_id"):
        if not script_provided:
            raise HTTPException(422, "正式交班已建立，请提供续演剧本或 case_id")
        run = _create_continuation_run(db, source_run_id, body, actor, parameter, payload, case_id)
        db.execute(update(handoffs).where(handoffs.c.id == existing["id"]).values(
            continuation_run_id=run["id"],
            request_digest=digest,
            updated_at=int(time()),
        ))
        audit.record(db, "continue_run", actor, "handoff", existing["id"])
        return run_service.get(db, run["id"]), get(db, existing["id"]), "created"

    run = run_service.get(db, existing["continuation_run_id"])
    same_request = (
        not script_provided
        or not existing.get("request_digest")
        or existing["request_digest"] == digest
    )
    if not same_request:
        return run, existing, "conflict"

    should_retry = body.get("retry") is True or (body.get("retry_failed", True) is not False)
    if run["status"] == JobState.FAILED and should_retry:
        db.execute(update(runs).where(runs.c.id == run["id"]).values(
            status=JobState.QUEUED, failure=None, finished_at=None,
        ))
        audit.record(db, "retry_run", actor, "run", run["id"])
        return run_service.get(db, run["id"]), get(db, existing["id"]), "retried"

    return run, existing, "replayed"


def submit_for_handoff(db, handoff_id, actor, body=None, header_key=None):
    handoff = get(db, handoff_id)
    return submit_continuation(db, handoff["source_run_id"], actor, body, header_key)
