from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..pipelines.clean import CleanedContent

Decision = Literal["single_call", "chunk"]


@dataclass(frozen=True, slots=True)
class BudgetDecision:
    decision: Decision
    max_tokens_per_chunk: int
    context_window: int
    estimated_tokens: int
    reserved_tokens: int


class TokenBudgetPlanner:
    def __init__(self, *, reserved_tokens: int = 1500) -> None:
        # room for schema/tooling/system prompt
        self.reserved_tokens = reserved_tokens

    def decide(
        self, content: CleanedContent, *, context_window: int, max_tokens_per_chunk: int
    ) -> BudgetDecision:
        budget = max(256, context_window - self.reserved_tokens)
        if content.token_estimate <= budget:
            return BudgetDecision(
                decision="single_call",
                max_tokens_per_chunk=max_tokens_per_chunk,
                context_window=context_window,
                estimated_tokens=content.token_estimate,
                reserved_tokens=self.reserved_tokens,
            )

        return BudgetDecision(
            decision="chunk",
            max_tokens_per_chunk=min(max_tokens_per_chunk, budget),
            context_window=context_window,
            estimated_tokens=content.token_estimate,
            reserved_tokens=self.reserved_tokens,
        )
