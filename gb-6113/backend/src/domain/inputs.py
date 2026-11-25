from dataclasses import dataclass


@dataclass(frozen=True)
class Standby:
    name: str
    flush_ms: int
    outages: tuple


@dataclass(frozen=True)
class Write:
    code: str
    area: str
    arrival: int
    local_ms: int
    fallback: bool


def integer(value, low, high, label):
    if type(value) is not int or not low <= value <= high:
        raise ValueError(f"{label}必须是 {low} 到 {high} 的整数")
    return value


def span_list(items):
    if not isinstance(items, list) or len(items) > 25:
        raise ValueError("中断窗须为不超过 25 段 [开始,结束] 的数组")
    periods = []
    for item in items:
        if not isinstance(item, list) or len(item) != 2:
            raise ValueError("中断窗须是 [开始,结束]")
        start = integer(item[0], 0, 100_000, "中断开始")
        end = integer(item[1], start + 1, 100_000, "中断结束")
        if periods and start < periods[-1][1]:
            raise ValueError("中断窗按开始时间排列且不得重叠")
        periods.append((start, end))
    return tuple(periods)


def name(value, label):
    if not isinstance(value, str) or not 1 <= len(value) <= 48 or not value.strip():
        raise ValueError(f"{label}须为 1 到 48 字的非空文本")
    return value


def standby_list(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 4:
        raise ValueError("配置 1 到 4 台备机")
    replicas = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"name", "flush_ms", "outages"}:
            raise ValueError("备机字段为 name、flush_ms、outages")
        replicas.append(Standby(
            name(item["name"], "备机名"),
            integer(item["flush_ms"], 1, 500, "每条远端持久化耗时"),
            span_list(item["outages"]),
        ))
    if len({replica.name for replica in replicas}) != len(replicas):
        raise ValueError("备机名称重复")
    return replicas


def write_list(items):
    if not isinstance(items, list) or not 1 <= len(items) <= 200:
        raise ValueError("配置 1 到 200 条班次写入")
    writes = []
    for item in items:
        if not isinstance(item, dict) or set(item) != {"code", "area", "arrival", "local_ms", "fallback"}:
            raise ValueError("写入字段为 code、area、arrival、local_ms、fallback")
        if type(item["fallback"]) is not bool:
            raise ValueError("fallback 必须是布尔值")
        writes.append(Write(
            name(item["code"], "班次写入号"), name(item["area"], "雪道"),
            integer(item["arrival"], 0, 100_000, "到达时间"),
            integer(item["local_ms"], 1, 500, "本机持久化耗时"),
            item["fallback"],
        ))
    if len({item.code for item in writes}) != len(writes):
        raise ValueError("写入号重复")
    return sorted(writes, key=lambda item: item.arrival)


def parse(payload):
    if not isinstance(payload, dict):
        raise ValueError("请输入同步写入剧本")
    replicas = standby_list(payload.get("standbys"))
    writes = write_list(payload.get("writes"))
    quorum = integer(payload.get("quorum"), 1, len(replicas), "同步确认数")
    crash = integer(payload.get("failure_at"), 1, 100_000, "主机故障点")
    promotion = name(payload.get("promotion"), "恢复来源")
    if promotion not in {replica.name for replica in replicas}:
        raise ValueError("恢复来源必须是已登记备机")
    return replicas, writes, quorum, crash, promotion
