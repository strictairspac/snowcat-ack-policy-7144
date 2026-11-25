from .admission import simulate
from .fixtures import FIXTURES
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


def run(payload, parameter, db):
    replicas, writes, quorum, crash, promoted = parse(payload)
    rows, strict, planned, lost = simulate(writes, replicas, quorum, crash, promoted, parameter)
    return {
        "summary": f"严格同步在故障前可答复 {strict} 笔，当前策略可答复 {planned} 笔；从{promoted}恢复时已答复但缺失 {lost} 笔。",
        "metrics": {"严格答复": strict, "策略答复": planned, "已答复缺失": lost},
        "rows": rows,
    }
