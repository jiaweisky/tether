"""Process-wide counters and gauges for the health/metrics endpoint.

A module-level singleton lets any component (engine, connectors, app) record a
metric without threading a handle through every call.
"""

from __future__ import annotations

import time
from typing import Any


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[str, int] = {}
        self.gauges: dict[str, float] = {}
        self.started_at: float = time.monotonic()

    def inc(self, name: str, amount: int = 1) -> None:
        self.counters[name] = self.counters.get(name, 0) + amount

    def set(self, name: str, value: float) -> None:
        self.gauges[name] = value

    def reset(self) -> None:
        """Clear all counters/gauges (used between apps, mainly in tests)."""
        self.counters.clear()
        self.gauges.clear()
        self.started_at = time.monotonic()

    def uptime_s(self) -> float:
        return time.monotonic() - self.started_at

    def snapshot(self) -> dict[str, Any]:
        return {
            "uptime_s": round(self.uptime_s(), 1),
            "counters": dict(self.counters),
            "gauges": dict(self.gauges),
        }

    def prometheus(self) -> str:
        lines: list[str] = [
            "# TYPE tether_uptime_seconds gauge",
            f"tether_uptime_seconds {self.uptime_s():.1f}",
        ]

        for name, count in sorted(self.counters.items()):
            lines.append(f"# TYPE tether_{name}_total counter")
            lines.append(f"tether_{name}_total {count}")

        for name, gauge in sorted(self.gauges.items()):
            lines.append(f"# TYPE tether_{name} gauge")
            lines.append(f"tether_{name} {gauge}")

        return "\n".join(lines) + "\n"


metrics = Metrics()
