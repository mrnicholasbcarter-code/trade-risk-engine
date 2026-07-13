"""Reproducible latency benchmarking helpers for the risk engine.

The benchmark is intentionally small and self-contained so that latency reports
can be regenerated from the exact same implementation path that evaluates trades
in production. The reported percentiles are descriptive, not contractual.
"""

from __future__ import annotations

import argparse
import json
import math
import time
from collections.abc import Sequence
from dataclasses import dataclass
from statistics import fmean

from .engine import RiskAuthority
from .state import Position, RiskContext

DEFAULT_CAVEATS = (
    "Python timing includes interpreter, allocation, and tracing overhead, so it is not directly comparable to native systems.",
    "Do not compare these numbers to Rust/C benchmarks without matching hardware, workload shape, and observability settings.",
    "Percentiles are reproducible for a fixed sample set, but live perf_counter measurements naturally vary run to run.",
)


@dataclass(frozen=True, slots=True)
class BenchmarkReport:
    """Percentile latency summary for a single benchmark run."""

    iterations: int
    warmup_iterations: int
    samples_ns: tuple[int, ...]
    p50_ns: int
    p95_ns: int
    p99_ns: int
    min_ns: int
    max_ns: int
    mean_ns: float
    caveats: tuple[str, ...] = DEFAULT_CAVEATS

    @classmethod
    def from_samples(
        cls, samples_ns: Sequence[int], iterations: int, warmup_iterations: int
    ) -> BenchmarkReport:
        ordered = tuple(sorted(int(sample) for sample in samples_ns))
        if not ordered:
            raise ValueError("samples_ns must not be empty")
        return cls(
            iterations=iterations,
            warmup_iterations=warmup_iterations,
            samples_ns=ordered,
            p50_ns=_percentile(ordered, 50.0),
            p95_ns=_percentile(ordered, 95.0),
            p99_ns=_percentile(ordered, 99.0),
            min_ns=ordered[0],
            max_ns=ordered[-1],
            mean_ns=fmean(ordered),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "iterations": self.iterations,
            "warmup_iterations": self.warmup_iterations,
            "samples_ns": list(self.samples_ns),
            "p50_ns": self.p50_ns,
            "p95_ns": self.p95_ns,
            "p99_ns": self.p99_ns,
            "min_ns": self.min_ns,
            "max_ns": self.max_ns,
            "mean_ns": self.mean_ns,
            "caveats": list(self.caveats),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True)

    def to_markdown(self) -> str:
        caveats = "\n".join(f"- {item}" for item in self.caveats)
        return (
            "# Trade Risk Engine Latency Benchmark\n\n"
            f"- Iterations: {self.iterations}\n"
            f"- Warmup iterations: {self.warmup_iterations}\n"
            f"- Samples: {len(self.samples_ns)}\n"
            f"- p50: {self.p50_ns} ns\n"
            f"- p95: {self.p95_ns} ns\n"
            f"- p99: {self.p99_ns} ns\n"
            f"- Mean: {self.mean_ns:.2f} ns\n"
            f"- Min / max: {self.min_ns} ns / {self.max_ns} ns\n\n"
            "## Caveats\n\n"
            f"{caveats}\n"
        )


def run_latency_benchmark(
    iterations: int = 1000,
    warmup_iterations: int = 100,
) -> BenchmarkReport:
    """Measure the hot path latency of ``RiskAuthority.evaluate_trade``."""

    if iterations < 1:
        raise ValueError("iterations must be >= 1")
    if warmup_iterations < 0:
        raise ValueError("warmup_iterations must be >= 0")

    ctx = RiskContext(latency_budget_us=1_000_000)
    open_positions: list[Position] = []

    for _ in range(warmup_iterations):
        RiskAuthority.evaluate_trade(
            ctx=ctx,
            daily_realized_pnl=0.0,
            equity=10_000.0,
            target_family="BENCH",
            proposed_cost=100.0,
            open_positions=open_positions,
            expected_value=1.0,
        )

    samples_ns: list[int] = []
    for _ in range(iterations):
        start_ns = time.perf_counter_ns()
        RiskAuthority.evaluate_trade(
            ctx=ctx,
            daily_realized_pnl=0.0,
            equity=10_000.0,
            target_family="BENCH",
            proposed_cost=100.0,
            open_positions=open_positions,
            expected_value=1.0,
        )
        samples_ns.append(time.perf_counter_ns() - start_ns)

    return BenchmarkReport.from_samples(
        samples_ns, iterations=iterations, warmup_iterations=warmup_iterations
    )


def _percentile(samples_ns: Sequence[int], percentile: float) -> int:
    if percentile <= 0:
        return int(samples_ns[0])
    if percentile >= 100:
        return int(samples_ns[-1])
    rank = max(0, math.ceil((percentile / 100.0) * len(samples_ns)) - 1)
    return int(samples_ns[rank])


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Benchmark trade-risk-engine latency")
    parser.add_argument("--iterations", type=int, default=1000)
    parser.add_argument("--warmup-iterations", type=int, default=100)
    parser.add_argument("--json", action="store_true", help="Emit JSON instead of markdown")
    args = parser.parse_args(list(argv) if argv is not None else None)

    report = run_latency_benchmark(
        iterations=args.iterations,
        warmup_iterations=args.warmup_iterations,
    )
    if args.json:
        print(report.to_json())
    else:
        print(report.to_markdown())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
