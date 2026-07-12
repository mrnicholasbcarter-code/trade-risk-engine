++ /home/nick/trade-risk-engine/SECURITY.md
# Security Policy

## Supported Versions

We take security seriously. Below are the versions currently receiving security updates.

| Version | Supported          |
| ------- | ------------------ |
| 0.1.x   | :white_check_mark: |
| < 0.1.0 | :x:                |

## Reporting a Vulnerability

We take the security of `trade-risk-engine` seriously. If you believe you have found a security vulnerability, please report it to us as described below.

### How to Report

**Please do NOT report security vulnerabilities through public GitHub issues.**

Instead, please report them via:

1. **GitHub Security Advisories** (Preferred): Use the [Security Advisory](https://github.com/mrnicholasbcarter-code/trade-risk-engine/security/advisories/new) tab to privately report the vulnerability.
2. **Email**: Send details to security@mrnicholasbcarter-code.com

### What to Include

Please include the following information in your report:

- **Description**: A clear description of the vulnerability
- **Impact**: What an attacker could achieve by exploiting this vulnerability
- **Reproduction Steps**: Step-by-step instructions to reproduce the issue
- **Proof of Concept**: If applicable, a minimal code example demonstrating the vulnerability
- **Affected Versions**: Which versions are affected (if known)
- **Suggested Fix**: If you have a suggested fix, please include it

### What to Expect

- **Acknowledgment**: We will acknowledge receipt within 48 hours
- **Assessment**: We will assess the vulnerability within 5 business days
- **Fix Timeline**: Critical vulnerabilities will be patched within 7 days; high/medium within 30 days
- **Credit**: We will credit you in the security advisory (unless you prefer anonymity)

## Security Considerations for trade-risk-engine

This library implements mathematically deterministic risk evaluation for trading systems. Security considerations include:

### Floating-Point Precision
- All floating-point comparisons MUST use `pytest.approx()` or `math.isclose()`
- IEEE 754 compliance is mandatory for all financial calculations
- No raw `==` comparisons for float values

### Input Validation
- All public API inputs must be validated
- NaN, infinity, and subnormal values must be handled explicitly
- Input ranges must be bounded and documented

### Determinism
- The risk engine MUST be mathematically deterministic
- No I/O operations in the core engine (`src/trade_risk_engine/engine.py`)
- No random number generation in deterministic paths
- No time-dependent calculations

### Dependency Security
- All dependencies are scanned via GitHub Dependabot weekly
- Security advisories are monitored via GitHub CodeQL
- Minimum dependency versions are pinned where security is critical

## Responsible Disclosure

We follow responsible disclosure practices. We ask that you give us reasonable time to address the issue before public disclosure. We will keep you informed of our progress.

## Security Contacts

- **Primary**: Nicholas Carter (@mrnicholasbcarter-code)
- **Security Email**: security@mrnicholasbcarter-code.com

## Recognition

We appreciate responsible disclosure. Contributors who report valid security issues will be acknowledged in our Security Advisories (unless anonymity is requested).
