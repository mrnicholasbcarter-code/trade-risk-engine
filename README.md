<div align="center">
  <h1>Trade Risk Engine</h1>
  <p><strong>Deterministic, Pure-Functional Capital Protection Evaluator</strong></p>
  <img src="https://img.shields.io/badge/build-passing-brightgreen" alt="Build Status" />
  <img src="https://img.shields.io/badge/fuzzing-fast--check-blue" alt="Fuzzing" />
</div>

## Architecture

This engine evaluates capital execution targets entirely in-memory, relying on statically typed arrays to guarantee sub-millisecond execution times.

```mermaid
graph TD
    A[Order Signal] --> B{Exposure Evaluator}
    B -->|Acceptable| C{Drawdown Kill Switch}
    B -->|Violation| F[REJECT]
    C -->|Safe| D[EXECUTE]
    C -->|Breached| F[REJECT]
```

## Testing Protocol
Unit tests are written using `hypothesis` against 1,000+ randomized property parameters to guarantee integer overflow conditions never crash the evaluation loops.
