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
