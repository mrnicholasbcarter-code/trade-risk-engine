# Package boundary and migration policy

The released package is named `verdict-risk`, while its Python import namespace
remains `trade_risk_engine` for compatibility with the existing API and test
suite. The console script is `verdict-risk-benchmark` and currently points to
`trade_risk_engine.benchmark:main`.

This is deliberate: package distribution names and Python import namespaces
are independent. A future import rebrand must add a compatibility package,
fixtures, and a documented deprecation window before changing the namespace.
Do not claim that `verdict_risk` is importable until that migration is actually
implemented and verified in an isolated wheel/sdist install.

The CI contract installs only declared `dev` and `test` extras. Lint, format,
typecheck, tests, build, and package smoke must run in that same environment.
The package workflow also installs both the built wheel and source distribution
into isolated virtual environments, imports the documented compatibility
namespace, and invokes `verdict-risk-benchmark`. This verifies the published
artifacts rather than only an editable checkout.
