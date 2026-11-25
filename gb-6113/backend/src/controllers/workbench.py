from redis.exceptions import RedisError
from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError

from src.config.resources import cache, engine
from src.services import cases, handoffs, reviews, runs


def wake_run(run_id):
    try:
        cache.lpush("workbench:wake", str(run_id))
        cache.ltrim("workbench:wake", 0, 99)
    except RedisError:
        # The database holds the durable queue. The worker also polls it.
        pass


def new_case(data, user):
    with engine.begin() as db:
        return cases.create(db, data, user["username"])


def new_run(case_id, data, user):
    source_run_id = (
        getattr(data, "source_run_id", None)
        or getattr(data, "source_id", None)
        or getattr(data, "from_run_id", None)
        or getattr(data, "parent_run_id", None)
        or getattr(data, "parent_id", None)
    )
    handoff_id = getattr(data, "handoff_id", None)
    if source_run_id is not None or handoff_id is not None:
        body = {
            "case_id": case_id,
            "parameter": data.parameter,
            "replica": getattr(data, "replica", None),
            "selected_replica": getattr(data, "selected_replica", None),
            "idempotency_key": getattr(data, "idempotency_key", None),
        }
        if handoff_id is not None:
            run, handoff, state = continue_handoff(handoff_id, body, user)
        else:
            run, handoff, state = continue_from_run(source_run_id, body, user, body["idempotency_key"])
        if state == "conflict":
            raise HTTPException(409, "该故障批次已有一份正式交班；请沿用其续演批次，勿再新增批次")
        return {
            **run,
            "handoff_id": handoff["id"],
            "source_run_id": handoff["source_run_id"],
            "parent_run_id": handoff["source_run_id"],
            "state": state,
        }

    with engine.begin() as db:
        run = runs.enqueue(db, case_id, data.parameter, user["username"])
    wake_run(run["id"])
    return run


def retry_run(run_id, user):
    with engine.begin() as db:
        run, changed = runs.retry(db, run_id, user["username"])
    if changed:
        wake_run(run["id"])
    return run


def create_handoff(source_run_id, data, user):
    body = data.model_dump(exclude_unset=True) if hasattr(data, "model_dump") else dict(data or {})
    with engine.begin() as db:
        return handoffs.create_handoff(
            db, source_run_id, user["username"], body=body,
            header_key=body.get("idempotency_key"),
        )


def _replay_after_integrity(source_run_id=None, handoff_id=None):
    with engine.connect() as db:
        if handoff_id is not None:
            handoff = handoffs.get(db, handoff_id)
            source_run_id = handoff["source_run_id"]
        else:
            handoff = handoffs.get_for_source(db, source_run_id)
        if handoff is None:
            return None, None, "integrity_error"
        run = runs.get(db, handoff["continuation_run_id"]) if handoff.get("continuation_run_id") else None
        return run, handoff, "replayed"


def continue_from_run(source_run_id, body, user, idempotency_key=None):
    try:
        with engine.begin() as db:
            run, handoff, state = handoffs.submit_continuation(
                db, source_run_id, user["username"], body=body, header_key=idempotency_key,
            )
    except IntegrityError:
        # Concurrent formal hand-offs can race the unique constraint before the
        # source-row lock is acquired on some backends.  Re-read the winner.
        run, handoff, state = _replay_after_integrity(source_run_id=source_run_id)
        if state == "integrity_error":
            raise
    if state in {"created", "retried"} and run is not None:
        wake_run(run["id"])
    return run, handoff, state


def continue_handoff(handoff_id, body, user, idempotency_key=None):
    try:
        with engine.begin() as db:
            handoff = handoffs.get(db, handoff_id)
            source_run_id = handoff["source_run_id"]
            run, handoff, state = handoffs.submit_continuation(
                db, source_run_id, user["username"], body=body, header_key=idempotency_key,
            )
    except IntegrityError:
        run, handoff, state = _replay_after_integrity(handoff_id=handoff_id)
        if state == "integrity_error":
            raise
    if state in {"created", "retried"} and run is not None:
        wake_run(run["id"])
    return run, handoff, state


def new_review(run_id, data, user):
    with engine.begin() as db:
        return reviews.sign(db, run_id, data, user["username"])
