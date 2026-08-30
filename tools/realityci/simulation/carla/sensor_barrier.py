"""Bounded exact-frame synchronization for CARLA sensor callbacks."""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Any


class SensorSynchronizationError(TimeoutError):
    pass


@dataclass(frozen=True)
class SensorFrame:
    sensor_id: str
    frame_id: int
    payload: Any


class SensorBarrier:
    def __init__(self, required_sensor_ids: tuple[str, ...], max_queue: int = 32) -> None:
        if not required_sensor_ids or len(set(required_sensor_ids)) != len(required_sensor_ids):
            raise ValueError("required_sensor_ids must be non-empty and unique")
        if max_queue < 2:
            raise ValueError("max_queue must be at least two")
        self.required_sensor_ids = required_sensor_ids
        self.max_queue = max_queue
        self._queues: dict[str, deque[SensorFrame]] = defaultdict(lambda: deque(maxlen=max_queue))
        self._condition = threading.Condition()
        self.stale_discard_count = 0

    def push(self, sensor_id: str, frame_id: int, payload: Any) -> None:
        if sensor_id not in self.required_sensor_ids:
            return
        with self._condition:
            queue = self._queues[sensor_id]
            if queue and frame_id <= queue[-1].frame_id:
                if any(item.frame_id == frame_id for item in queue):
                    return
            queue.append(SensorFrame(sensor_id, frame_id, payload))
            self._condition.notify_all()

    def collect_exact_frame(self, frame_id: int, timeout_s: float = 1.0) -> dict[str, Any]:
        deadline = time.monotonic() + timeout_s
        with self._condition:
            while True:
                result: dict[str, Any] = {}
                missing: list[str] = []
                for sensor_id in self.required_sensor_ids:
                    queue = self._queues[sensor_id]
                    while queue and queue[0].frame_id < frame_id:
                        queue.popleft()
                        self.stale_discard_count += 1
                    match = next((item for item in queue if item.frame_id == frame_id), None)
                    if match is None:
                        missing.append(sensor_id)
                    else:
                        result[sensor_id] = match.payload
                if not missing:
                    for sensor_id in self.required_sensor_ids:
                        queue = self._queues[sensor_id]
                        while queue and queue[0].frame_id <= frame_id:
                            queue.popleft()
                    return result
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise SensorSynchronizationError(
                        f"frame {frame_id} missing exact sensor frames: {', '.join(missing)}"
                    )
                self._condition.wait(remaining)
