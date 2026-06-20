"""A tiny in-process metrics registry that renders Prometheus exposition text.

Three classic instruments: a request *counter* (by method/route/status), a request
duration *histogram* (cumulative buckets), and an in-flight *gauge*. The middleware
records into it; `/metrics` renders it. Real deployments use `prometheus-client`,
but hand-rolling it once makes the wire format concrete.

Cardinality note: `route` is always the route TEMPLATE (e.g. /chat/{id}/history),
never the raw path — otherwise every id would create a new time series.
"""

# Cumulative upper bounds (seconds). An observation counts toward every bucket >= it.
_LATENCY_BUCKETS = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)


def _escape(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Metrics:
    def __init__(self) -> None:
        self._requests: dict[tuple[str, str, str], int] = {}  # (method, route, status) -> count
        self._latency_sum: dict[tuple[str, str], float] = {}
        self._latency_count: dict[tuple[str, str], int] = {}
        self._latency_bucket: dict[tuple[str, str, float], int] = {}  # (method, route, le)
        self._in_flight = 0

    def inc_in_flight(self) -> None:
        self._in_flight += 1

    def dec_in_flight(self) -> None:
        self._in_flight -= 1

    def observe(self, method: str, route: str, status: int, duration_s: float) -> None:
        request_key = (method, route, str(status))
        self._requests[request_key] = self._requests.get(request_key, 0) + 1

        latency_key = (method, route)
        self._latency_sum[latency_key] = self._latency_sum.get(latency_key, 0.0) + duration_s
        self._latency_count[latency_key] = self._latency_count.get(latency_key, 0) + 1
        for bucket in _LATENCY_BUCKETS:
            if duration_s <= bucket:
                key = (method, route, bucket)
                self._latency_bucket[key] = self._latency_bucket.get(key, 0) + 1

    def render(self) -> str:
        lines: list[str] = []

        lines.append("# HELP http_requests_total Total HTTP requests.")
        lines.append("# TYPE http_requests_total counter")
        for (method, route, status), count in sorted(self._requests.items()):
            labels = f'method="{_escape(method)}",route="{_escape(route)}",status="{status}"'
            lines.append(f"http_requests_total{{{labels}}} {count}")

        lines.append("# HELP http_requests_in_flight HTTP requests currently being served.")
        lines.append("# TYPE http_requests_in_flight gauge")
        lines.append(f"http_requests_in_flight {self._in_flight}")

        name = "http_request_duration_seconds"
        lines.append(f"# HELP {name} HTTP request latency in seconds.")
        lines.append(f"# TYPE {name} histogram")
        for method, route in sorted(self._latency_count):
            base = f'method="{_escape(method)}",route="{_escape(route)}"'
            total = self._latency_count[(method, route)]
            latency_sum = self._latency_sum[(method, route)]
            for bucket in _LATENCY_BUCKETS:
                count = self._latency_bucket.get((method, route, bucket), 0)
                lines.append(f'{name}_bucket{{{base},le="{bucket}"}} {count}')
            lines.append(f'{name}_bucket{{{base},le="+Inf"}} {total}')
            lines.append(f"{name}_sum{{{base}}} {latency_sum}")
            lines.append(f"{name}_count{{{base}}} {total}")

        return "\n".join(lines) + "\n"
