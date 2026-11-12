"""Token usage to USD, from evals/pricing.yaml. No LLM and no app imports, so tests can use it."""

from pathlib import Path

import yaml

PRICING_FILE = Path(__file__).parent / "pricing.yaml"


def load_pricing(path: Path = PRICING_FILE) -> dict[str, dict[str, float]]:
    return yaml.safe_load(path.read_text()) or {}


def cost(usage: dict[str, dict[str, int]], pricing: dict[str, dict[str, float]]) -> float | None:
    """USD for usage {model: {input, cached_input, output}}; None if a model has no price."""
    total = 0.0
    for model, counts in usage.items():
        price = pricing.get(model)
        if price is None:
            return None
        total += sum(
            counts.get(kind, 0) * price[kind] for kind in ("input", "cached_input", "output")
        )
    return total / 1_000_000


def add_usage(*usages: dict[str, dict[str, int]]) -> dict[str, dict[str, int]]:
    """Sum several {model: counts} dicts."""
    total: dict[str, dict[str, int]] = {}
    for usage in usages:
        for model, counts in usage.items():
            into = total.setdefault(model, {})
            for kind, n in counts.items():
                into[kind] = into.get(kind, 0) + n
    return total
