# Contributing to verdict-risk

Thank you for your interest in contributing to `verdict-risk`! The released
distribution is `verdict-risk`; the compatible Python namespace remains
`trade_risk_engine` until a separately documented migration is completed.
Precision, correctness, and determinism are paramount.

## Code of Conduct

This project follows our [Code of Conduct](CODE_OF_CONDUCT.md). By participating, you are expected to uphold this code.

## Getting Started

### Prerequisites

- Python 3.11+
- `uv` (recommended) or `pip` + `venv`
- `make` (for Makefile targets)

### Development Setup

```bash
# Clone the repository
git clone https://github.com/mrnicholasbcarter-code/verdict-risk.git
cd verdict-risk

# Create virtual environment (recommended: uv)
uv sync --dev
# Or with pip:
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# Verify setup
pytest tests/
```

## Development Workflow

### Branch Naming

- `feature/<short-description>` - New features
- `fix/<short-description>` - Bug fixes
- `docs/<short-description>` - Documentation updates
- `refactor/<short-description>` - Refactoring
- `perf/<short-description>` - Performance improvements

### Commit Messages

We follow [Conventional Commits](https://www.conventionalcommits.org/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`, `chore`

Examples:
```
feat(engine): add margin call evaluator
fix(math): handle subnormal floats in drawdown calc
docs(readme): add installation instructions
test(property): add hypothesis test for boundary conditions
```

### Pull Request Process

1. **Fork** the repository and create your branch from `main`
2. **Make your changes** following the guidelines below
3. **Run tests locally** - All tests must pass
4. **Submit a PR** using the PR template
5. **Code review** - Address feedback
6. **Merge** - Squash and merge after approval

## Code Standards

### Mathematical Correctness (CRITICAL)

This is a **mathematically deterministic risk engine**. The following rules are non-negotiable:

- **No I/O in the engine core** (`src/trade_risk_engine/engine.py`)
- **No random number generation** in deterministic paths
- **No time-dependent calculations** in the core
- **Floating-point comparisons** MUST use `pytest.approx()` or `math.isclose()`
- **No raw `==` on floats** - ever
- **Use `Decimal`** for financial calculations where precision is critical
- **Boundary conditions** tested with `pytest.approx(rel=1e-9)`

### Code Style

- **Formatter**: `ruff format`
- **Linter**: `ruff check`
- **Type checker**: `mypy src/`
- **Line length**: 100 characters
- **Imports**: Sorted with `ruff` (stdlib, third-party, local)

### Architecture

- **Pure functions** preferred - no side effects
- **Immutable data structures** - use `msgspec.Struct` (frozen=True)
- **Type hints** required on all public functions
- **Single responsibility** - each function does one thing
- **No global mutable state**

### Project Structure

```
src/trade_risk_engine/
├── engine.py      # Core risk engine (PURE - NO I/O)
├── gates.py       # Kill-switch boundaries
├── state.py       # Immutable state structures
└── __init__.py    # Public API exports
tests/
├── test_property.py        # Property-based tests (Hypothesis)
├── test_precision_drift.py # IEEE 754 precision tests
└── conftest.py             # pytest configuration
```

## Testing Requirements

### Mandatory Test Coverage

- **100% line coverage** minimum
- **Property-based tests** for all mathematical functions (Hypothesis)
- **Precision drift tests** for floating-point boundaries
- **Edge case tests**: NaN, infinity, subnormal, zero, max/min values

### Running Tests

```bash
# All tests
pytest tests/

# With coverage
pytest --cov=src/trade_risk_engine --cov-report=term-missing

# Property-based tests only
pytest tests/test_property.py -v

# Precision drift tests only
pytest tests/test_precision_drift.py -v

# Type checking
mypy src/

# Linting
ruff check .

# Formatting check
ruff format --check .
```

### Writing Tests

```python
# GOOD - uses pytest.approx for float comparison
def test_drawdown_calculation():
    result = calculate_drawdown(100.0, 95.0)
    assert result == pytest.approx(0.05, rel=1e-9)

# GOOD - uses math.isclose
def test_drawdown_calculation_isclose():
    result = calculate_drawdown(100.0, 95.0)
    assert math.isclose(result, 0.05, rel_tol=1e-9)

# BAD - raw float comparison
def test_drawdown_calculation_BAD():
    result = calculate_drawdown(100.0, 95.0)
    assert result == 0.05  # WRONG!
```

## Documentation

- Update `README.md` for user-facing changes
- Update docstrings for public APIs
- Add examples for new features
- Keep `CHANGELOG.md` updated (maintainers handle releases)

## Release Process

Releases are managed by maintainers:

1. Update version in `pyproject.toml`
2. Update `CHANGELOG.md`
3. Create git tag: `git tag v0.x.y`
4. Push tag: `git push origin v0.x.y`
5. GitHub Actions builds and publishes to PyPI

## Getting Help

- **Issues**: [GitHub Issues](https://github.com/mrnicholasbcarter-code/verdict-risk/issues)
- **Discussions**: [GitHub Discussions](https://github.com/mrnicholasbcarter-code/verdict-risk/discussions)
- **Security**: See [SECURITY.md](SECURITY.md)

## License

By contributing, you agree that your contributions will be licensed under the project's MIT License.
