"""Structured logging, request correlation, and in-process metrics.

Stdlib only — no agent, no sidecar. Logs go to stdout as JSON (which is what
App Runner, Container Apps, and `docker logs` all expect), and metrics are
exposed at /metrics in Prometheus text format so any scraper can read them.
"""
import json
import logging
import os
import threading
import time
import uuid
from collections import defaultdict
from contextvars import ContextVar

# Set per request so every log line emitted while handling it can be correlated.
request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

LOG_LEVEL = os.environ.get("LOG_LEVEL", "INFO").upper()
JSON_LOGS = os.environ.get("JSON_LOGS", "1") not in ("0", "false", "False")

# Latency buckets in seconds. The upper ones are deliberately generous: some
# endpoints fan out to an external price API and take tens of seconds.
BUCKETS = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, value in getattr(record, "extra_fields", {}).items():
            payload[key] = value
        return json.dumps(payload)


def setup_logging() -> None:
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter() if JSON_LOGS
        else logging.Formatter("%(levelname)s %(name)s %(message)s")
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(LOG_LEVEL)
    # uvicorn installs its own access log; ours already records every request.
    logging.getLogger("uvicorn.access").disabled = True


class Metrics:
    """Counters and latency histograms, safe to mutate from request threads."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.counters: dict[tuple[str, tuple], int] = defaultdict(int)
        self.hist_buckets: dict[tuple[str, tuple], list[int]] = {}
        self.hist_sum: dict[tuple[str, tuple], float] = defaultdict(float)
        self.hist_count: dict[tuple[str, tuple], int] = defaultdict(int)
        self.started = time.time()

    @staticmethod
    def _key(name: str, labels: dict | None) -> tuple[str, tuple]:
        return name, tuple(sorted((labels or {}).items()))

    def inc(self, name: str, labels: dict | None = None, by: int = 1) -> None:
        with self._lock:
            self.counters[self._key(name, labels)] += by

    def observe(self, name: str, seconds: float, labels: dict | None = None) -> None:
        key = self._key(name, labels)
        with self._lock:
            if key not in self.hist_buckets:
                self.hist_buckets[key] = [0] * len(BUCKETS)
            for i, edge in enumerate(BUCKETS):
                if seconds <= edge:
                    self.hist_buckets[key][i] += 1
            self.hist_sum[key] += seconds
            self.hist_count[key] += 1

    def snapshot(self) -> dict:
        """Plain dict of current values — used by tests and /metrics.json."""
        with self._lock:
            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "counters": {
                    _render(name, labels): value
                    for (name, labels), value in self.counters.items()
                },
                "latency": {
                    _render(name, labels): {
                        "count": self.hist_count[(name, labels)],
                        "sum": round(self.hist_sum[(name, labels)], 4),
                        "avg": round(
                            self.hist_sum[(name, labels)]
                            / max(self.hist_count[(name, labels)], 1), 4
                        ),
                    }
                    for (name, labels) in self.hist_count
                },
            }

    def prometheus(self) -> str:
        """Prometheus text exposition format."""
        lines = [
            "# HELP app_uptime_seconds Seconds since process start",
            "# TYPE app_uptime_seconds gauge",
            f"app_uptime_seconds {round(time.time() - self.started, 1)}",
        ]
        with self._lock:
            by_name: dict[str, list] = defaultdict(list)
            for (name, labels), value in self.counters.items():
                by_name[name].append((labels, value))
            for name, entries in sorted(by_name.items()):
                lines += [f"# TYPE {name} counter"]
                for labels, value in sorted(entries):
                    lines.append(f"{_render(name, labels)} {value}")

            for (name, labels) in sorted(self.hist_count):
                lines += [f"# TYPE {name} histogram"]
                cumulative = self.hist_buckets[(name, labels)]
                for edge, count in zip(BUCKETS, cumulative):
                    lines.append(
                        f"{_render(name, labels, extra=('le', str(edge)))} {count}"
                    )
                lines.append(
                    f"{_render(name, labels, extra=('le', '+Inf'))} "
                    f"{self.hist_count[(name, labels)]}"
                )
                lines.append(f"{_render(name + '_sum', labels)} "
                             f"{round(self.hist_sum[(name, labels)], 4)}")
                lines.append(f"{_render(name + '_count', labels)} "
                             f"{self.hist_count[(name, labels)]}")
        return "\n".join(lines) + "\n"


def _render(name: str, labels: tuple, extra: tuple | None = None) -> str:
    pairs = list(labels) + ([extra] if extra else [])
    if not pairs:
        return name
    inner = ",".join(f'{k}="{v}"' for k, v in pairs)
    return f"{name}{{{inner}}}"


metrics = Metrics()


def new_request_id() -> str:
    return uuid.uuid4().hex[:12]
