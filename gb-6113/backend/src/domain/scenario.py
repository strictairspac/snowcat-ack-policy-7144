from .admission import simulate, simulate_continuation
from .fixtures import FIXTURES
from .handoff import handoff_manifest
from .inputs import parse

CONFIG = {
    "title": "雪榆山场·压雪班同步写入窗口",
    "team": "雪榆山场 16 人夜间压雪班与机房值守",
    "description": "回放夜间压雪班的副本落盘和答复时间，识别故障时可恢复的工作凭条及降级确认风险。",
    "direction": "同步复制与降级写入",
    "mechanism": "顺序落盘离散时间模型、同步确认门槛和目标副本缺失核算。",
    "modules": ["雪道值班台", "维护剧本", "确认回放", "交班风险"],
    "unit": "维护剧本",
    "max_parameter": 500,
    "default_parameter": 25,
    "parameter_label": "可降级写入的等待时限（毫秒）",
    "facts": ["本机落盘", "副本应答", "已答复缺失"],
    "palette": 13,
    "fixture": "snow-grooming-window-1124.json",
}


def validate(payload):
    parse(payload)


def run(payload, parameter, db, context=None):
    replicas, writes, quorum, crash, promoted = parse(payload)

    if context is None and isinstance(payload, dict):
        embedded_handoff = payload.get("handoff") if isinstance(payload.get("handoff"), dict) else {}
        embedded_continuation = payload.get("continuation") if isinstance(payload.get("continuation"), dict) else {}
        inherited = (
            payload.get("inherited")
            or payload.get("inherited_writes")
            or payload.get("inherited_receipts")
            or payload.get("inherited_codes")
            or embedded_continuation.get("inherited")
            or embedded_continuation.get("inherited_codes")
            or embedded_handoff.get("inherited")
            or embedded_handoff.get("inherited_codes")
            or ()
        )
        previous_losses = (
            payload.get("previous_losses")
            or payload.get("prior_losses")
            or payload.get("handoff_losses")
            or embedded_continuation.get("losses")
            or embedded_handoff.get("losses")
            or ()
        )
        if inherited or previous_losses:
            context = {
                "inherited": inherited,
                "losses": previous_losses,
                "source_run_id": embedded_handoff.get("source_run_id") or embedded_continuation.get("source_run_id"),
                "handoff_list": embedded_handoff.get("handoff_list") or embedded_continuation.get("handoff_list") or [],
            }

    if context:
        inherited = context.get("inherited", ()) or ()
        previous_losses = context.get("losses", context.get("previous_losses", ())) or ()
        rows, metrics, continuation = simulate_continuation(
            writes,
            replicas,
            quorum,
            crash,
            promoted,
            parameter,
            inherited=inherited,
            previous_losses=previous_losses,
            handoff=context,
        )
        source = continuation.get("source_run_id")
        source_text = f"，接第 {source} 场正式交班" if source is not None else "，接续正式交班"
        summary = (
            f"严格同步在故障前可答复 {metrics['严格答复']} 笔，当前策略可答复 {metrics['策略答复']} 笔；"
            f"从{promoted}恢复时已答复但缺失 {metrics['已答复缺失']} 笔{source_text}。"
            f"本场先补齐 {metrics['继承凭条']} 笔继承凭条，交班清单保留 {metrics['交班清单损失']} 笔未结丢失记录。"
        )
        return {
            "summary": summary,
            "metrics": metrics,
            "rows": rows,
            "inherited_rows": continuation.get("inherited_rows", []),
            "new_rows": continuation.get("new_rows", []),
            "continuation": continuation,
        }

    rows, strict, planned, lost = simulate(writes, replicas, quorum, crash, promoted, parameter)
    return {
        "summary": f"严格同步在故障前可答复 {strict} 笔，当前策略可答复 {planned} 笔；从{promoted}恢复时已答复但缺失 {lost} 笔。",
        "metrics": {"严格答复": strict, "策略答复": planned, "已答复缺失": lost},
        "rows": rows,
    }


def continue_run(payload, parameter, db=None, *, inherited=(), previous_losses=(), context=None):
    """Convenience domain entry point used by continuation-specific callers."""
    continuation_context = dict(context or {})
    continuation_context.setdefault("inherited", inherited)
    continuation_context.setdefault("losses", previous_losses)
    return run(payload, parameter, db, continuation_context)


def preview_handoff(payload, parameter, run_id=None, replica=None, previous_losses=(), source_case=None):
    return handoff_manifest(
        payload,
        parameter,
        run_id=run_id,
        replica_name=replica,
        previous_losses=previous_losses,
        source_case=source_case,
    )


# Descriptive aliases for callers/tests using the requirement's language.
continue_scenario = continue_run
run_continuation = continue_run
preview_continuation = preview_handoff
