from app.joysafeter_shared.ids import TaskId


def compute_retry_delay(retry_count: int, task_id: TaskId, base_ms: int = 2000, max_ms: int = 30000) -> float:
    delay_ms = min(base_ms * (2 ** min(retry_count, 14)), max_ms)
    jitter_ms = task_id.uuid.int % (delay_ms // 4 + 1) if delay_ms > 0 else 0
    result: float = (delay_ms + jitter_ms) / 1000.0
    return result
