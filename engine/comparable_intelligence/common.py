"""Shared helpers for the Comparable Intelligence Layer.

Every CIL output uses the same tri-part envelope — ``result``, ``explanation``
and ``assumptions_used`` — plus an ``advisory`` flag and a non-opinion
``basis``. This exists for long-term auditability and reproducibility: a reader
can see *what* the result was, *why* it occurred, and *which* assumptions,
policies, hierarchy definitions and configuration values contributed. No CIL
output ever carries a value/price/adopted-value conclusion.
"""

from typing import Any, Dict, List, Mapping, Sequence


def is_number(value) -> bool:
    """True for real ints/floats (bools excluded)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    """Constrain a value to ``[low, high]``."""
    return max(low, min(high, float(value)))


def build_envelope(*, result: Any, explanation: Sequence[str],
                   assumptions_used: Mapping, basis: str,
                   advisory: bool = True) -> Dict:
    """Assemble the standard CIL output envelope.

    ``result`` is the (supporting, subordinate) computed output; ``explanation``
    is the human-readable reasoning (the headline of an explainability-first
    output); ``assumptions_used`` captures the configuration/policy/values that
    produced the result, for reproducibility. ``advisory`` is always True for
    advisory outputs and ``basis`` states the non-opinion nature explicitly.
    """
    explanation_list: List[str] = list(explanation)
    return {
        "result": result,
        "explanation": explanation_list,
        "assumptions_used": dict(assumptions_used),
        "advisory": advisory,
        "basis": basis,
    }
