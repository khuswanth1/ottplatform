"""Tiny in-process counters rendered in Prometheus text format (scrape /metrics with METRICS_TOKEN)."""
import threading
from collections import defaultdict

_lock = threading.Lock()
_counters: dict[tuple[str, tuple], float] = defaultdict(float)


def inc(name: str, value: float = 1, **labels: str) -> None:
    with _lock:
        _counters[(name, tuple(sorted(labels.items())))] += value


def render() -> str:
    lines = []
    with _lock:
        for (name, labels), v in sorted(_counters.items()):
            lbl = ",".join(f'{k}="{val}"' for k, val in labels)
            lines.append(f"{name}{{{lbl}}} {v}" if lbl else f"{name} {v}")
    return "\n".join(lines) + "\n"
