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


def flush_timeline(writes, replicas):
    available = {item.name: 0 for item in replicas}
    previous_local = 0
    for write in writes:
        local_at = max(previous_local, write.arrival) + write.local_ms
        previous_local = local_at
        adjusted = {}
        for item in replicas:
            earliest = max(local_at, available[item.name])
            adjusted[item.name] = finish_at(earliest, item.flush_ms, item.outages)
        available.update(adjusted)
        yield write, local_at, adjusted
