import pytest

from cloudsite.modules.automation.contracts.public import ParserEvaluationCase, evaluate_parser_cases


def _case(resource_id, name, expected, extension="", mime_type=""):
    return ParserEvaluationCase(resource_id, name, f"/incoming/{name}", extension, mime_type, expected)


def test_evaluation_reports_exact_aggregate_and_field_rates():
    report = evaluate_parser_cases([
        _case("r1", "Cloud-App-1.2.3-windows-x64.zip", {"platform": "windows", "architecture": "x64", "version": "1.2.3", "package_form": "zip"}, "zip"),
        _case("r2", "教程合集-2026.09.10-zh.7z", {"language": "zh", "version": "2026.09.10", "package_form": "7z"}, "7z"),
    ])
    assert report["samples"] == 2
    assert report["aggregate"] == {"total": 7, "correct": 7, "unknown": 0, "incorrect": 0, "accuracy": 1.0, "unknown_rate": 0.0, "misclassification_rate": 0.0}
    assert all(item["matched"] for item in report["sample_results"])


def test_evaluation_separates_unknown_from_wrong_non_unknown_value():
    report = evaluate_parser_cases([
        _case("r1", "plain-file.bin", {"platform": "linux"}, "bin"),
        _case("r2", "tool-windows.zip", {"platform": "linux"}, "zip"),
    ])
    assert report["aggregate"]["unknown"] == 1
    assert report["aggregate"]["incorrect"] == 1
    assert report["aggregate"]["unknown_rate"] == 0.5
    assert report["aggregate"]["misclassification_rate"] == 0.5


def test_evaluation_handles_hyphenated_architecture_and_mixed_version():
    report = evaluate_parser_cases([
        _case("r1", "tool-v2.5-x86-64.tar.gz", {"architecture": "x64", "version": "2.5", "package_form": "tar_gz"}, "gz"),
    ])
    assert report["aggregate"]["correct"] == 3


def test_evaluation_rejects_empty_and_unknown_expected_fields():
    with pytest.raises(ValueError, match="at least one"):
        evaluate_parser_cases([])
    with pytest.raises(ValueError, match="unsupported"):
        evaluate_parser_cases([_case("r1", "tool.zip", {"license": "MIT"}, "zip")])
