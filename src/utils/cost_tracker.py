"""Cost tracking for DeepSeek API calls."""

from __future__ import annotations

import threading
from dataclasses import dataclass

_INPUT_PRICE_PER_1M = 0.14
_OUTPUT_PRICE_PER_1M = 0.28


@dataclass
class _CallRecord:
    node: str
    input_tokens: int
    output_tokens: int
    cost: float


class CostTracker:
    """Track LLM API costs across a session or application lifetime."""

    def __init__(
        self,
        input_price_per_1m: float = _INPUT_PRICE_PER_1M,
        output_price_per_1m: float = _OUTPUT_PRICE_PER_1M,
    ):
        self.input_price = input_price_per_1m
        self.output_price = output_price_per_1m
        self._calls: list[_CallRecord] = []
        self._lock = threading.Lock()

    def record_call(
        self, node: str, input_tokens: int, output_tokens: int
    ) -> float:
        cost = (
            input_tokens * self.input_price / 1_000_000
            + output_tokens * self.output_price / 1_000_000
        )
        with self._lock:
            self._calls.append(_CallRecord(node, input_tokens, output_tokens, cost))
        return cost

    @property
    def total_tokens(self) -> int:
        with self._lock:
            return sum(c.input_tokens + c.output_tokens for c in self._calls)

    @property
    def total_cost(self) -> float:
        with self._lock:
            return sum(c.cost for c in self._calls)

    def get_summary(self) -> dict:
        with self._lock:
            calls = list(self._calls)
        return {
            "calls": len(calls),
            "total_input_tokens": sum(c.input_tokens for c in calls),
            "total_output_tokens": sum(c.output_tokens for c in calls),
            "total_cost": round(sum(c.cost for c in calls), 6),
            "by_node": {
                node: {
                    "calls": sum(1 for c in calls if c.node == node),
                    "tokens": sum(c.input_tokens + c.output_tokens for c in calls if c.node == node),
                    "cost": round(sum(c.cost for c in calls if c.node == node), 6),
                }
                for node in set(c.node for c in calls)
            },
        }

    def reset(self) -> None:
        with self._lock:
            self._calls.clear()


cost_tracker = CostTracker()
