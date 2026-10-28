import threading
from collections import defaultdict


class RequestMetrics:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._requests: dict[tuple[str, str, int], dict[str, float | int]] = defaultdict(
            lambda: {
                "count": 0,
                "duration_seconds_total": 0.0,
                "duration_seconds_max": 0.0,
            }
        )

    def record(
        self,
        method: str,
        route: str,
        status_code: int,
        duration_seconds: float,
    ) -> None:
        key = (method, route, status_code)
        with self._lock:
            aggregate = self._requests[key]
            aggregate["count"] += 1
            aggregate["duration_seconds_total"] += duration_seconds
            aggregate["duration_seconds_max"] = max(
                float(aggregate["duration_seconds_max"]),
                duration_seconds,
            )

    def snapshot(self) -> list[dict[str, float | int | str]]:
        with self._lock:
            return [
                {
                    "method": method,
                    "route": route,
                    "status_code": status_code,
                    **aggregate,
                }
                for (method, route, status_code), aggregate in sorted(
                    self._requests.items()
                )
            ]


request_metrics = RequestMetrics()
