from .flush import flush_events
from .inputs import parse


def _case_label(source_case):
    if not source_case:
        return None, None, None
    if isinstance(source_case, dict):
        return source_case.get("id"), source_case.get("code"), source_case.get("title")
    return getattr(source_case, "id", None), getattr(source_case, "code", None), getattr(source_case, "title", None)


def _loss_entry(write, *, run_id, replica, ack_at, target_at, source_case):
    case_id, case_code, case_title = _case_label(source_case)
    return {
        "loss_id": f"run-{run_id}:{write.code}" if run_id is not None else f"draft:{write.code}",
        "code": write.code,
        "写入号": write.code,
        "area": write.area,
        "雪道": write.area,
        "replica": replica,
        "副本": replica,
        "ack_at_ms": ack_at,
        "答复 ms": ack_at,
        "target_flush_ms": target_at,
        "目标落盘 ms": target_at,
        "lost_in_run_id": run_id,
        "source_run_id": run_id,
        "case_id": case_id,
        "lost_in_case_code": case_code,
        "lost_in_case_title": case_title,
        "lost_in_scenario": case_code or case_title or run_id,
        # Keep the Chinese assertion surface explicit.  The numeric field is
        # convenient for tests and links; the label is convenient for people.
        "丢失场次": run_id,
        "丢失场次标签": (
            f"第 {run_id} 场" + (f"（{case_code}）" if case_code else "")
            if run_id is not None else "未保存场次"
        ),
        "状态": "已答复但丢失",
    }


def handoff_manifest(
    payload,
    parameter,
    run_id=None,
    replica_name=None,
    previous_losses=(),
    source_case=None,
    inherited=(),
):
    """Build the durable hand-off ledger from a completed fault batch.

    Only receipts whose write reached the selected replica at or before the
    failure are inherited.  ``inherited`` is the backlog used by the source
    batch itself; including it here preserves the ordering/outage delays when
    deriving the next official hand-off.  Acknowledged writes missing from
    that replica are loss records and are never de-duplicated by receipt code:
    a same-number rewrite creates a new write, while the old loss remains in
    ``losses``.
    """
    replicas, writes, quorum, crash, promoted = parse(payload)
    selected = replica_name or promoted
    names = {item.name for item in replicas}
    if selected not in names:
        raise ValueError("交班副本必须是剧本中已登记的备机")

    inherited = list(inherited or ())
    inherited_receipts = []
    new_losses = []
    inherited_codes = []
    lost_codes = []

    events = flush_events(writes, replicas, inherited)
    for position, (write, local_at, remote, segment, backlog_position) in enumerate(events):
        target_at = remote[selected]
        persisted = target_at <= crash

        if persisted:
            original_run_id = getattr(write, "original_run_id", None)
            if original_run_id is None and isinstance(inherited[backlog_position] if segment == "inherited" and backlog_position is not None else None, dict):
                original_run_id = inherited[backlog_position].get("original_run_id")
            inherited_receipts.append({
                "code": write.code,
                "写入号": write.code,
                "area": write.area,
                "雪道": write.area,
                "fallback": getattr(write, "fallback", False),
                "sequence": position,
                "segment": segment,
                "source_run_id": run_id,
                "original_run_id": original_run_id or run_id,
                "selected_replica": selected,
                "目标落盘 ms": target_at,
            })
            inherited_codes.append(write.code)

        # Inherited backlog events were not newly acknowledged by this batch.
        if segment != "new":
            continue

        strict_at = sorted(remote.values())[quorum - 1]
        deadline = local_at + parameter
        cutoff = min(strict_at, deadline) if write.fallback else strict_at
        planned_ok = cutoff <= crash

        if planned_ok and not persisted:
            lost_codes.append(write.code)
            new_losses.append(_loss_entry(
                write, run_id=run_id, replica=selected, ack_at=cutoff,
                target_at=target_at, source_case=source_case,
            ))

    losses = [dict(item) for item in (previous_losses or ())]
    losses.extend(new_losses)

    ledger = []
    for item in inherited_receipts:
        ledger.append({
            "kind": "inherited",
            "类型": "继承凭条",
            "code": item["code"],
            "写入号": item["code"],
            "source_run_id": run_id,
            "丢失场次": None,
        })
    for item in losses:
        ledger.append({
            "kind": "lost",
            "类型": "已答复但丢失",
            "code": item.get("code") or item.get("写入号"),
            "写入号": item.get("code") or item.get("写入号"),
            "source_run_id": item.get("lost_in_run_id") or item.get("source_run_id"),
            "lost_in_run_id": item.get("lost_in_run_id") or item.get("source_run_id"),
            "丢失场次": item.get("丢失场次", item.get("lost_in_run_id")),
        })

    prior_loss_codes = sorted({
        item.get("code") or item.get("写入号")
        for item in losses
        if item.get("code") or item.get("写入号")
    })

    return {
        "schema": "night-handoff-v1",
        "official": True,
        "source_run_id": run_id,
        "replica": selected,
        "selected_replica": selected,
        "failure_at": crash,
        "parameter": parameter,
        "inherited": inherited_receipts,
        "继承凭条": inherited_receipts,
        "inherited_codes": inherited_codes,
        "继承凭条号": inherited_codes,
        # ``receipts`` is a concise alias for callers that only need order.
        "receipts": inherited_codes,
        "new_losses": new_losses,
        "new_lost_codes": lost_codes,
        "losses": losses,
        # The business phrase maps directly to the unresolved loss ledger.
        "交班清单": losses,
        "lost_codes": [item.get("code") or item.get("写入号") for item in losses],
        "prior_loss_codes": prior_loss_codes,
        "handoff_list": ledger,
        "items": ledger,
    }


# Common domain-language aliases.
build_handoff = handoff_manifest
create_manifest = handoff_manifest
