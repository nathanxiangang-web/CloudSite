"""Deterministic A1 parser evaluation over administrator-provided fixtures."""
from __future__ import annotations

from dataclasses import dataclass

from ..domain.resource_name_parser import UNKNOWN, parse_resource_name

EVALUATED_FIELDS = ("platform", "architecture", "language", "version", "package_form")


@dataclass(frozen=True)
class ParserEvaluationCase:
    resource_id: str
    name: str
    path: str
    extension: str
    mime_type: str
    expected: dict[str, str]


def evaluate_parser_cases(cases: list[ParserEvaluationCase]) -> dict:
    """Return exact accuracy, unknown, and misclassification metrics.

    Every explicitly expected field contributes one observation. An unknown
    actual value is reported separately from a non-unknown wrong value.
    """

    if not cases:
        raise ValueError("at least one evaluation case is required")
    totals = {field: {"total": 0, "correct": 0, "unknown": 0, "incorrect": 0} for field in EVALUATED_FIELDS}
    sample_results: list[dict] = []
    for case in cases:
        result = parse_resource_name(case.resource_id, case.name, case.path, case.extension, case.mime_type)
        mismatches: list[str] = []
        for field, expected in case.expected.items():
            if field not in totals:
                raise ValueError(f"unsupported expected field: {field}")
            actual = getattr(result, field)
            metric = totals[field]
            metric["total"] += 1
            if actual == expected:
                metric["correct"] += 1
            elif actual == UNKNOWN:
                metric["unknown"] += 1
                mismatches.append(field)
            else:
                metric["incorrect"] += 1
                mismatches.append(field)
        sample_results.append({"resource_id": case.resource_id, "matched": not mismatches, "mismatched_fields": mismatches})

    def rates(metric: dict[str, int]) -> dict:
        total = metric["total"]
        return {
            **metric,
            "accuracy": metric["correct"] / total if total else 0.0,
            "unknown_rate": metric["unknown"] / total if total else 0.0,
            "misclassification_rate": metric["incorrect"] / total if total else 0.0,
        }

    aggregate = {key: sum(metric[key] for metric in totals.values()) for key in ("total", "correct", "unknown", "incorrect")}
    return {
        "samples": len(cases),
        "aggregate": rates(aggregate),
        "fields": {field: rates(metric) for field, metric in totals.items()},
        "sample_results": sample_results,
    }
