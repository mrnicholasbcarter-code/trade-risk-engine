# Verdict Risk — Zero-Allocation Capital Protection Evaluator

> Deterministic, pure-functional capital protection evaluator for quantitative trading. Designed to run directly inside order-routing hot paths, `verdict-risk` verifies trading signals against complex risk parameters from memory, guaranteeing sub-millisecond latencies under strict execution constraints.

---

## Core Philosophy

Traditional trade risk systems suffer execution drift, concurrency race conditions, network-induced latency spikes. `verdict-risk` solves these problems by splitting risk evaluation into a pure, mathematical computation layer separate from state management and network I/O.

| Layer | Responsibility | Latency Budget |
|-------|----------------|----------------|
| **Pure Math** (this crate) | Drawdown gates, position limits, correlation bounds, Kelly sizing | **< 50 µs** |
| **State Management** | Redis/Postgres persistence, audit logging | < 1 ms |
| **Network I/O** | Broker APIs, market data feeds | Variable |

---

## Key Features

| Feature | Description |
|---------|-------------|
| **Zero-allocation hot path** | `msgspec`-encoded structs, no GC pressure on evaluation |
| **Deterministic gates** | Same inputs → same outputs, always |
| **Sub-millisecond latency** | Pure Python hot path, no locks or I/O |
| **Stateless gates** | Drawdown, position, correlation, Kelly — no external deps |
| **Stateful desk controls** | Daily loss limits, sector exposure, factor models (optional Redis) |
| **OpenTelemetry native** | Spans, metrics, logs for every evaluation |
| **Property-based testing** | Hypothesis fuzzing + formal verification of mathematical properties |

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                            VERDICT RISK                                      │
├─────────────────────────────────────────────────────────────────────────────┤
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    STATELESS RISK GATES (Pure Math)                    │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │  │
│  │  │  Drawdown    │ │  Position    │ │  Correlation │ │  Kelly       │  │  │
│  │  │  Gate        │ │  Limit Gate  │ │  Gate        │ │  Sizing      │  │  │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
│  ┌────────────────────────────────────────────────────────────────────────┐  │
│  │                    STATEFUL DESK CONTROLS (Optional)                   │  │
│  │  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐  │  │
│  │  │  Daily Loss  │ │  Sector      │ │  Factor      │ │  Paper       │  │  │
│  │  │  Limit       │ │  Exposure    │ │  Model       │ │  Execution   │  │  │
│  │  └──────────────┘ └──────────────┘ └──────────────┘ └──────────────┘  │  │
│  └────────────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## Installation

```bash
pipx install verdict-risk
```

Requires Python 3.10+ (3.11 recommended).

The distribution is `verdict-risk`; the compatible Python import namespace is
currently `trade_risk_engine`. See [the package boundary policy](docs/package-boundary.md)
before relying on a future `verdict_risk` import.

---

## API Reference

### Stateless Risk Gates

```python
from trade_risk_engine import Position, RiskAuthority, RiskContext

decision = RiskAuthority.evaluate_trade(
    ctx=RiskContext(max_daily_drawdown_pct=0.10),
    daily_realized_pnl=-5_000,
    equity=100_000,
    target_family="BTC-USD",
    proposed_cost=1_000,
    open_positions=[
        Position(
            ticker="BTC-USD-1",
            family="BTC-USD",
            cost_basis=500,
            current_value=500,
            is_resolved=False,
        )
    ],
)
assert decision.approved
```

### Stateful Desk Controls

```python
from trade_risk_engine import KillSwitch, RiskAuthority

authority = RiskAuthority(kill_switch=KillSwitch())
# Stateful controls are opt-in and remain local to the authority.
```

---

## Configuration

```yaml
# ~/.verdict/risk_config.yaml
drawdown_gate:
  max_drawdown_pct: 0.10
  lookback_days: 30

position_limits:
  default_max_usd: 50000
  per_symbol:
    "BTC-USD": 100000
    "ETH-USD": 50000

correlation:
  max_correlation: 0.7
  lookback_window: 100

kelly:
  enabled: true
  conservative_fraction: 0.5  # Half-Kelly

desk_controls:
  daily_loss_limit_usd: 5000
  sector_exposure_pct: 0.30
  paper_slippage_bps: 5
  paper_latency_ms: 100
```

---

## Telemetry

Every evaluation emits OpenTelemetry spans:

```python
from opentelemetry import trace
from trade_risk_engine import RiskAuthority, RiskContext

tracer = trace.get_tracer("verdict-risk")
with tracer.start_as_current_span("risk.evaluation") as span:
    result = RiskAuthority.evaluate_trade(
        ctx=RiskContext(max_daily_drawdown_pct=0.10),
        daily_realized_pnl=-5_000,
        equity=100_000,
        target_family="BTC-USD",
        proposed_cost=1_000,
        open_positions=[],
    )
    span.set_attribute("risk.approved", result.approved)
    span.set_attribute("risk.reason", result.reason_code)
```

---

## Testing & Fuzzing

```bash
# Run tests with property-based fuzzing
pytest tests/ -v --hypothesis-show-statistics

# Benchmarks
python -m trade_risk_engine.benchmark --iterations 1000 --warmup-iterations 100
```

### Mathematical Properties Verified

| Property | Test |
|----------|------|
| Drawdown gate monotonicity | `drawdown(a) >= drawdown(b) if a <= a)` |
| Kelly optimality | `f* = (bp - q)/b` matches analytic solution |
| Correlation gate symmetry | `corr(A,B) == corr(B,A)` |
| Position limit idempotence | `gate(x); gate(x) == gate(x)` |

---

## Performance

| Operation | Latency (p50) | Latency (p99) | Throughput |
|-----------|---------------|---------------|------------|
| Drawdown gate | 12 µs | 35 µs | 80,000 ops/s |
| Position limit | 8 µs | 22 µs | 120,000 ops/s |
| Correlation gate | 45 µs | 120 µs | 22,000 ops/s |
| Kelly sizing | 15 µs | 40 µs | 65,000 ops/s |

*Historical benchmark snapshot; rerun the benchmark on your hardware before
using these figures as an operational bound.*

---

## Links

- **Verdict Core**: https://github.com/verdict/verdict-core
- **Verdict Edge**: https://github.com/verdict/verdict-edge
- **Verdict Backtest**: https://github.com/verdict/verdict-backtest
- **RuVector**: https://github.com/ruvnet/ruvector
- **Ruflo**: https://github.com/ruvnet/claude-flow

---

## License

MIT — see [LICENSE](LICENSE)
