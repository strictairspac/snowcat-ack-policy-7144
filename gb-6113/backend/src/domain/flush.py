from dataclasses import dataclass


def finish_at(start, service_ms, outages):
    """Transfer only in available windows, carrying partial progress across breaks."""
    time = start
    remaining = service_ms
    for outage_start, outage_end in outages:
        if outage_end <= time:
            continue
        if time < outage_start:
            available = outage_start - time
            if available >= remaining:
                return time + remaining
            remaining -= available
        time = outage_end
    return time + remaining


@dataclass(frozen=True)
class InheritedReceipt:
    code: str
    area: str = ""
    fallback: bool = False
    source_run_id: int | None = None
    original_run_id: int | None = None


def _receipt(item):
    if isinstance(item, str):
        return InheritedReceipt(code=item)
    if isinstance(item, dict):
        return InheritedReceipt(
            code=item["code"],
            area=item.get("area", ""),
            fallback=bool(item.get("fallback", False)),
            source_run_id=item.get("source_run_id"),
            original_run_id=item.get("original_run_id", item.get("source_run_id")),
        )
    return InheritedReceipt(
        code=item.code,
        area=getattr(item, "area", ""),
        fallback=getattr(item, "fallback", False),
        source_run_id=getattr(item, "source_run_id", None),
        original_run_id=getattr(item, "original_run_id", None),
    )


def flush_events(writes, replicas, inherited=()):
    """Yield replication events, running the inherited backlog before new writes.

    The inherited segment starts at the continuation clock's zero and uses this
    scenario's outage windows.  Replica availability then naturally blocks new
    writes until the backlog has been served in its original order.
    """
    available = {item.name: 0 for item in replicas}

    for position, raw_receipt in enumerate(inherited):
        receipt = _receipt(raw_receipt)
        adjusted = {}
        for item in replicas:
            finished = finish_at(available[item.name], item.flush_ms, item.outages)
            adjusted[item.name] = finished
            available[item.name] = finished
        yield receipt, 0, adjusted, "inherited", position

    previous_local = 0
    for write in writes:
        local_at = max(previous_local, write.arrival) + write.local_ms
        previous_local = local_at
        adjusted = {}
        for item in replicas:
            earliest = max(local_at, available[item.name])
            adjusted[item.name] = finish_at(earliest, item.flush_ms, item.outages)
            available[item.name] = adjusted[item.name]
        yield write, local_at, adjusted, "new", None


def flush_timeline(writes, replicas, inherited=()):
    for write, local_at, adjusted, _segment, _position in flush_events(writes, replicas, inherited):
        yield write, local_at, adjusted
