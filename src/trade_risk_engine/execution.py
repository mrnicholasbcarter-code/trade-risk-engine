"""Paper trading adapter guardrails.

The paper adapter is intentionally non-executable. It can consume risk alerts,
but any attempt to place a live order raises immediately so examples cannot
accidentally cross the paper/live boundary.
"""

from __future__ import annotations

from typing import Never

from .webhook import RiskEvent


class PaperExecutionAdapter:
    """Alert-only execution adapter for paper trading examples."""

    __slots__ = ()

    def handle_alert(self, event: RiskEvent) -> None:
        """Accept a risk alert without producing any order side effects."""
        del event

    def submit_order(self, *args: object, **kwargs: object) -> Never:
        """Refuse live order placement from paper-mode code paths."""
        del args, kwargs
        raise RuntimeError("Live order placement is disabled in the paper execution adapter")
