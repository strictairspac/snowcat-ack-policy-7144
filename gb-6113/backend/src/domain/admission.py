from .flush import flush_events
from .flush import flush_timeline


def simulate(writes, replicas, quorum, crash, promoted, timeout):
    rows = []
    strict_responses = fallback_responses = promotion_loss = 0
    for write, local_at, remote in flush_timeline(writes, replicas):
        strict_at = sorted(remote.values())[quorum - 1]
        deadline = local_at + timeout
        cutoff = min(strict_at, deadline) if write.fallback else strict_at
        strict_ok = strict_at <= crash
        planned_ok = cutoff <= crash
        fell_back = planned_ok and cutoff < strict_at
        strict_responses += strict_ok
        fallback_responses += planned_ok
        available_after_crash = remote[promoted] <= crash
        loses = planned_ok and not available_after_crash
        promotion_loss += loses
        rows.append({
            "写入号": write.code,
            "雪道": write.area,
            "本机落盘 ms": local_at if local_at <= crash else None,
            "严格答复 ms": strict_at if strict_ok else None,
            "按策略答复 ms": cutoff if planned_ok else None,
            "答复路径": "本地降级" if fell_back else ("同步确认" if planned_ok else "故障前未答复"),
            "目标落盘 ms": remote[promoted] if available_after_crash else None,
            "恢复时缺失": "已答复但缺失" if loses else ("可恢复" if available_after_crash else "未答复"),
        })
    return rows, strict_responses, fallback_responses, promotion_loss


def simulate_continuation(
    writes,
    replicas,
    quorum,
    crash,
    promoted,
    timeout,
    inherited=(),
    previous_losses=(),
    handoff=None,
):
    """Simulate a continuation drill with its ordered inherited backlog."""
    inherited = list(inherited or ())
    previous_losses = list(previous_losses or ())
    prior_loss_codes = {
        item.get("code") or item.get("写入号")
        for item in previous_losses
        if item.get("code") or item.get("写入号")
    }

    rows = []
    inherited_rows = []
    new_rows = []
    strict_responses = fallback_responses = promotion_loss = 0
    inherited_target_ready = inherited_quorum_ready = 0

    for write, local_at, remote, segment, position in flush_events(writes, replicas, inherited):
        strict_at = sorted(remote.values())[quorum - 1]
        target_at = remote[promoted]
        target_ready = target_at <= crash
        strict_ready = strict_at <= crash
        rewritten_lost_code = write.code in prior_loss_codes

        if segment == "inherited":
            inherited_target_ready += target_ready
            inherited_quorum_ready += strict_ready
            row = {
                "阶段": "补齐继承",
                "继承顺序": position + 1,
                "来源场次": getattr(write, "source_run_id", None),
                "写入号": write.code,
                "雪道": write.area,
                "本机落盘 ms": None,
                "严格答复 ms": strict_at if strict_ready else None,
                "按策略答复 ms": strict_at if strict_ready else None,
                "答复路径": "继承补齐" if strict_ready else "本场未补齐",
                "目标落盘 ms": target_at if target_ready else None,
                "恢复时缺失": "可恢复" if target_ready else "继承尚未补齐",
                "交班清单同号": rewritten_lost_code,
            }
            rows.append(row)
            inherited_rows.append(row)
            continue

        deadline = local_at + timeout
        cutoff = min(strict_at, deadline) if write.fallback else strict_at
        strict_ok = strict_ready
        planned_ok = cutoff <= crash
        fell_back = planned_ok and cutoff < strict_at
        strict_responses += strict_ok
        fallback_responses += planned_ok
        loses = planned_ok and not target_ready
        promotion_loss += loses
        row = {
            "阶段": "新写入",
            "写入号": write.code,
            "雪道": write.area,
            "本机落盘 ms": local_at if local_at <= crash else None,
            "严格答复 ms": strict_at if strict_ok else None,
            "按策略答复 ms": cutoff if planned_ok else None,
            "答复路径": "本地降级" if fell_back else ("同步确认" if planned_ok else "故障前未答复"),
            "目标落盘 ms": target_at if target_ready else None,
            "恢复时缺失": "已答复但缺失" if loses else ("可恢复" if target_ready else "未答复"),
            "交班清单同号": rewritten_lost_code,
        }
        rows.append(row)
        new_rows.append(row)

    metrics = {
        "严格答复": strict_responses,
        "策略答复": fallback_responses,
        "已答复缺失": promotion_loss,
        "继承凭条": len(inherited),
        "继承目标副本已补齐": inherited_target_ready,
        "继承达确认门槛": inherited_quorum_ready,
        "交班清单损失": len(previous_losses),
    }
    continuation = {
        "handoff_id": (handoff or {}).get("handoff_id") if isinstance(handoff, dict) else None,
        "source_run_id": (handoff or {}).get("source_run_id") if isinstance(handoff, dict) else None,
        "inherited_count": len(inherited),
        "inherited_codes": [item.get("code") if isinstance(item, dict) else item for item in inherited],
        "inherited_rows": inherited_rows,
        "new_rows": new_rows,
        "loss_count": len(previous_losses),
        "losses": previous_losses,
        "交班清单": previous_losses,
        "handoff_list": (handoff or {}).get("handoff_list", []) if isinstance(handoff, dict) else [],
    }
    return rows, metrics, continuation


# Concise domain-language alias.
continue_simulation = simulate_continuation
