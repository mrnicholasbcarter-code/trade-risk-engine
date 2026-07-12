# AI Agent Constraints & Architectural Context (.claude.md)

**Target Ecosystem:** Execution Guardrails & Capital Protection
**Language:** Python 3.10+
**Primary Directive:** Mathematically deterministic risk evaluation.

## Execution Rules
- Under no circumstances should an AI agent implement a network request or I/O operation inside `/src/trade_risk_engine/engine.py`.
- The engine must remain computationally pure. State -> Evaluator -> Boolean.

## Floating Point Drift
When modifying the kill switch boundaries in `gates.py`, utilize `pytest.approx()` inside the test harness to account for IEEE 754 precision drift. Do not write raw `==` assertions for float evaluations.
