"""Deterministic effort and spend reservations shared by every model stage."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass


class BudgetExceeded(RuntimeError):
    pass


@dataclass(frozen=True)
class EffortPolicy:
    effort: str
    max_requests: int
    parallel_requests: int
    deadline_seconds: int
    input_tokens: int
    output_tokens: int
    max_cost_usd: float


POLICIES = {
    "quick": EffortPolicy("quick", 4, 2, 15, 32768, 8192, 0.05),
    "standard": EffortPolicy("standard", 8, 3, 40, 65536, 16384, 0.20),
    "deep": EffortPolicy("deep", 14, 4, 90, 131072, 32768, 0.50),
}


def initial_budget(effort: str, max_cost_usd: float | None = None) -> dict:
    policy = POLICIES.get(effort)
    if not policy:
        raise BudgetExceeded("Unknown effort policy")
    limit = policy.max_cost_usd if max_cost_usd is None else max_cost_usd
    if not math.isfinite(limit) or limit <= 0 or limit > policy.max_cost_usd:
        raise BudgetExceeded("Requested spend exceeds the effort policy")
    return {
        "policy": {**asdict(policy), "max_cost_usd": limit},
        "requests": 0,
        "input_reserved": 0,
        "output_reserved": 0,
        "cost_reserved": 0.0,
        "input_used": 0,
        "output_used": 0,
        "cost_used": 0.0,
        "usage_unknown": False,
    }


def reserve(budget: dict, *, input_tokens: int, output_tokens: int, cost_usd: float) -> dict:
    if (
        type(input_tokens) is not int
        or type(output_tokens) is not int
        or input_tokens < 0
        or output_tokens <= 0
        or not math.isfinite(cost_usd)
        or cost_usd < 0
    ):
        raise BudgetExceeded("Invalid usage reservation")
    policy = budget["policy"]
    if budget["requests"] + 1 > policy["max_requests"]:
        raise BudgetExceeded("Model request budget reached")
    if budget["input_used"] + budget["input_reserved"] + input_tokens > policy["input_tokens"]:
        raise BudgetExceeded("Input token budget reached")
    if budget["output_used"] + budget["output_reserved"] + output_tokens > policy["output_tokens"]:
        raise BudgetExceeded("Output token budget reached")
    if budget["cost_used"] + budget["cost_reserved"] + cost_usd > policy["max_cost_usd"] + 1e-12:
        raise BudgetExceeded("Spend budget reached")
    return {
        **budget,
        "requests": budget["requests"] + 1,
        "input_reserved": budget["input_reserved"] + input_tokens,
        "output_reserved": budget["output_reserved"] + output_tokens,
        "cost_reserved": budget["cost_reserved"] + cost_usd,
    }


def reconcile(budget: dict, reservation: dict, usage: dict | None) -> dict:
    # Missing usage stays charged at the full reserved ceiling, including
    # ambiguous failures. Never release spend because the provider was silent.
    consumed = usage or reservation
    for key in ("input_tokens", "output_tokens"):
        if type(consumed.get(key)) is not int or consumed[key] < 0:
            raise BudgetExceeded("Invalid provider usage")
    cost = consumed.get("cost_usd")
    if type(cost) not in {int, float} or not math.isfinite(cost) or cost < 0:
        raise BudgetExceeded("Invalid provider cost")
    # Provider overages are recorded, never hidden. No later stage may reserve
    # after caps have been exceeded; the adapter also limits each output call.
    return {
        **budget,
        "input_reserved": max(0, budget["input_reserved"] - reservation["input_tokens"]),
        "output_reserved": max(0, budget["output_reserved"] - reservation["output_tokens"]),
        "cost_reserved": max(0.0, budget["cost_reserved"] - reservation["cost_usd"]),
        "input_used": budget["input_used"] + consumed["input_tokens"],
        "output_used": budget["output_used"] + consumed["output_tokens"],
        "cost_used": budget["cost_used"] + cost,
        "usage_unknown": budget["usage_unknown"] or usage is None,
    }
