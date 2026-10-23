"""Shared measurement boundary for offline and live agent evaluations."""

from dataclasses import dataclass
from time import perf_counter
from typing import Callable


@dataclass(frozen=True)
class EvaluationOutcome:
    result: dict | None
    error: Exception | None
    checks: dict
    failure_diagnostic: dict | None
    elapsed_s: float
    token_usage: dict | None

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(value is True for value in self.checks.values())


@dataclass(frozen=True)
class EvaluationHarness:
    score: Callable[[dict, dict, Exception | None], dict]
    diagnose: Callable[[dict | None, Exception | None, dict], dict | None]
    usage_context: Callable | None = None

    def run_case(self, case: dict, invoke: Callable[[], dict]) -> EvaluationOutcome:
        started = perf_counter()
        result, error = None, None
        model_usage = {}
        if self.usage_context is None:
            try:
                result = invoke()
            except Exception as exc:
                error = exc
        else:
            with self.usage_context() as usage:
                try:
                    result = invoke()
                except Exception as exc:
                    error = exc
            model_usage = dict(usage.usage_metadata)
        checks = self.score(case, result or {}, error)
        input_tokens = sum(item.get("input_tokens", 0) for item in model_usage.values())
        output_tokens = sum(item.get("output_tokens", 0) for item in model_usage.values())
        return EvaluationOutcome(
            result=result, error=error, checks=checks,
            failure_diagnostic=self.diagnose(result, error, checks),
            elapsed_s=round(perf_counter() - started, 3),
            token_usage={"input_tokens": input_tokens, "output_tokens": output_tokens,
                         "total_tokens": input_tokens + output_tokens,
                         "by_model": model_usage} if model_usage else None,
        )
